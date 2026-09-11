from __future__ import annotations

import random
import uuid

from locust import tag, task

from shared.base_user import LocustUser
from shared.config import (
    DOCUMENT_UPLOAD_BUCKET,
    FARMER_INTAKE_FORM_ID,
    FARMER_INTAKE_TAB_ID,
    INTAKE_SEARCH_HIT_RATE,
    INTAKE_SEARCH_TERM_HITS,
    INTAKE_SEARCH_TERMS,
    REGISTER_FARMER,
    STAFF_API_BASE,
)
from shared.term_pool import claim_create_term
from shared.document_helpers import build_document_attachments, build_document_upload_files, extract_document_ids
from shared.response_utils import safe_json
from shared.slo_shape import SLOStepRampShape
from intake_create_helpers import (
    SECTION_DEFS,
    build_section_payload,
    choose_household_id,
    choose_random_attribute_override,
    extract_submission_id,
    extract_tab_sections,
    merge_with_accumulated,
    new_row_ids,
    order_sections_for_parent_links,
)


class IntakeCreateRampShape(SLOStepRampShape):
    """Step 1 ramp-to-failure for intake_create -- see shared/slo_shape.py
    and documentation/staff-api/test-scenarios.md §4/§5."""


class IntakeCreateUser(LocustUser):
    """Submits a full farmer_ingestion_intake form, one section at a time.

    Sections (and their order) come from get_all_sections at run time; one of
    9 attributes is randomized per invocation (everything else in its section
    keeps a standard baseline value). All sections share one submission_id,
    captured from the first save_intake_form_submission response.

    Search-text: each submission claims a least-used exported term whose
    DB hit count plus this-process creates stays under 2000.
    ~INTAKE_SEARCH_HIT_RATE of submissions embed that term; the rest embed
    a unique miss-token so empty-result searches stay realistic.
    """

    host = STAFF_API_BASE
    _embed_counts: dict[str, int] = {}

    def on_start(self):
        super().on_start()
        self.search_text = ""

    def _search_anchor_for_create(self) -> str:
        """Pool term ~80% of the time; unique miss-token otherwise."""
        if INTAKE_SEARCH_TERMS and random.random() < INTAKE_SEARCH_HIT_RATE:
            self.search_text = claim_create_term(
                INTAKE_SEARCH_TERMS, self._embed_counts, INTAKE_SEARCH_TERM_HITS
            )
            return self.search_text
        return f"xmiss{uuid.uuid4().hex[:10]}"

    @tag("intake", "write")
    @task
    def intake_create(self):
        self._get_intake_form_submissions_summary()

        render_response = self._render_intake_form()
        print(f"\nDEBUG render_response -> {safe_json(render_response)}\n")
        tab_sections = extract_tab_sections(safe_json(render_response), FARMER_INTAKE_TAB_ID)
        section_ids = order_sections_for_parent_links(
            [section["section_id"] for section in tab_sections]
        )
        documents_required_by_section = {
            section["section_id"]: bool(section.get("documents_required")) for section in tab_sections
        }
        print(f"\nDEBUG section_ids -> {section_ids}\n")
        if not section_ids:
            return

        attribute_name, section_with_override, value = choose_random_attribute_override()
        household_id = choose_household_id()
        row_ids = new_row_ids()
        search_anchor = self._search_anchor_for_create()
        print(f"\nDEBUG CREATE search_anchor -> {search_anchor!r}\n")

        submission_id = None
        accumulated_by_register: dict = {}
        for section_id in section_ids:
            section_def = SECTION_DEFS.get(section_id)
            print(f"\nDEBUG SECTION ID in LOOP ==> section_id -> {section_id}\n")
            if not section_def:
                continue

            own_payload = build_section_payload(
                section_id,
                attribute_name,
                section_with_override,
                value,
                household_id,
                search_anchor=search_anchor,
                row_ids=row_ids,
            )
            section_payload = merge_with_accumulated(
                section_def["section_register_id"], own_payload, accumulated_by_register
            )

            documents = None
            if documents_required_by_section.get(section_id):
                upload_response_json = safe_json(self._upload_documents())
                document_ids = extract_document_ids(upload_response_json)
                print(f"\nDEBUG {section_id} requires documents -> uploaded {document_ids}\n")
                documents = build_document_attachments(document_ids)

            save_response = self._save_intake_form_submission(
                submission_id=submission_id,
                section_id=section_id,
                section_register_id=section_def["section_register_id"],
                section_payload=[section_payload],
                documents=documents,
            )
            save_response_json = safe_json(save_response)
            response_status = save_response_json.get("response_header", {}).get("response_status")
            if response_status == "ERROR":
                print(
                    f"\nDEBUG ERROR for {section_id} -> payload={section_payload} "
                    f"response={save_response_json}\n"
                )
                return
            print(f"\nDEBUG {section_id} -> {response_status}\n")

            if submission_id is None:
                submission_id = extract_submission_id(save_response_json)
                if not submission_id:
                    return

        if not submission_id:
            return

        self._get_intake_form_submission(submission_id)
        self._finalize_intake_form_submission(submission_id)

    # ------------------------------------------------------------------
    # get_intake_form_submissions_summary (g2p_intake_form_data_controller)
    # ------------------------------------------------------------------
    def _get_intake_form_submissions_summary(self):
        payload = self.build_request(request_payload={})
        return self._post(
            STAFF_API_BASE,
            "/intake-form-data/get_intake_form_submissions_summary",
            payload,
            name="get_intake_form_submissions_summary",
        )

    # ------------------------------------------------------------------
    # render_intake_form (g2p_intake_form_metadata_controller) — full tab +
    # section structure for the form in one call, filtered to FARMER_INTAKE_TAB_ID.
    # ------------------------------------------------------------------
    def _render_intake_form(self):
        payload = self.build_request(request_payload={"form_id": FARMER_INTAKE_FORM_ID})
        return self._post(
            STAFF_API_BASE, "/intake-form-metadata/render_intake_form", payload, name="render_intake_form"
        )

    # ------------------------------------------------------------------
    # upload_documents (g2p_document_controller) — raw multipart, not the
    # usual JSON G2PRequest envelope. Same document(s) uploaded for every
    # section with documents_required=True.
    # ------------------------------------------------------------------
    def _upload_documents(self):
        return self._post_multipart(
            STAFF_API_BASE,
            "/documents/upload_documents",
            files=build_document_upload_files(),
            data={"bucket": DOCUMENT_UPLOAD_BUCKET},
            name="upload_documents",
        )

    # ------------------------------------------------------------------
    # save_intake_form_submission (g2p_intake_form_data_controller) — one call per section
    # ------------------------------------------------------------------
    def _save_intake_form_submission(self, submission_id, section_id, section_register_id, section_payload, documents=None):
        payload = self.build_request(
            request_payload={
                "submission_id": submission_id,
                "section_id": section_id,
                "section_payload": section_payload,
                "section_register_id": section_register_id,
                "form_id": FARMER_INTAKE_FORM_ID,
                "register_id": REGISTER_FARMER,
                "documents": documents,
            },
        )
        return self._post(
            STAFF_API_BASE,
            "/intake-form-data/save_intake_form_submission",
            payload,
            name="save_intake_form_submission",
        )

    # ------------------------------------------------------------------
    # get_intake_form_submission (g2p_intake_form_data_controller)
    # ------------------------------------------------------------------
    def _get_intake_form_submission(self, submission_id):
        payload = self.build_request(request_payload={"submission_id": submission_id})
        return self._post(
            STAFF_API_BASE,
            "/intake-form-data/get_intake_form_submission",
            payload,
            name="get_intake_form_submission",
        )

    # ------------------------------------------------------------------
    # finalize_intake_form_submission (g2p_intake_form_data_controller)
    # ------------------------------------------------------------------
    def _finalize_intake_form_submission(self, submission_id):
        payload = self.build_request(request_payload={"submission_id": submission_id})
        return self._post(
            STAFF_API_BASE,
            "/intake-form-data/finalize_intake_form_submission",
            payload,
            name="finalize_intake_form_submission",
        )
