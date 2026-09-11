from __future__ import annotations

import random

from locust import tag, task

from shared.base_user import LocustUser
from shared.config import (
    CR_FIELD_BY_SECTION,
    CR_SEARCH_TERM_HITS,
    DOCUMENT_UPLOAD_BUCKET,
    REGISTER_FARMER,
    SEARCH_PAGE_SIZE,
    SEARCH_TERM_HITS,
    SEARCH_TERMS,
    STAFF_API_BASE,
)
from shared.term_pool import claim_create_term
from shared.document_helpers import build_document_attachments, build_document_upload_files, extract_document_ids
from shared.response_utils import safe_json
from shared.slo_shape import SLOStepRampShape
from cr_create_helpers import (
    api_enum_attribute_id,
    attribute_value_options,
    build_change_payload,
    build_section_metadata,
    choose_internal_record_id,
    extract_ordered_tab_ids,
    extract_tab_section_ids,
    generate_new_value,
    old_field_value,
    response_error_code,
    response_status,
    section_ui_schema_from_tab_sections,
    static_enum_options,
    total_pages,
)


class CrCreateRampShape(SLOStepRampShape):
    """Step 1 ramp-to-failure for cr_create -- see shared/slo_shape.py and
    documentation/staff-api/test-scenarios.md §4/§5."""


class CrCreateUser(LocustUser):
    """Creates change requests against Farmer register records.

    Search a random page -> pick a record -> for every tab, pick one
    configured section (CR_FIELD_BY_SECTION) -> modify that section's one
    known field -> route to the core or non-core change-request endpoint
    based on is_core_section.
    """

    host = STAFF_API_BASE

    # Process-wide create counts: seed_hits (from perf-seed) + these stay
    # under PERF_SEED_HIT_MAX so one term does not collect >2k new CRs.
    _term_usage_counts: dict[str, int] = {}
    _embed_counts: dict[str, int] = {}

    def on_start(self):
        super().on_start()
        self.search_text = ""

    def _claim_register_term(self) -> str:
        return claim_create_term(SEARCH_TERMS, self._term_usage_counts, SEARCH_TERM_HITS)

    def _claim_embed_term(self) -> str:
        return claim_create_term(SEARCH_TERMS, self._embed_counts, CR_SEARCH_TERM_HITS)

    @tag("change_request", "write")
    @task
    def create_change_requests(self):
        self.search_text = self._claim_register_term()
        print(f"\nDEBUG SEARCH_TERM register -> {self.search_text}\n")
        self._get_register_summary_data()

        page1_response = self._search_in_a_register(current_page=1)
        pages_total = total_pages(safe_json(page1_response))
        chosen_page = random.randint(1, pages_total)
        search_response = page1_response if chosen_page == 1 else self._search_in_a_register(current_page=chosen_page)

        internal_record_id = choose_internal_record_id(safe_json(search_response))
        print(f"\nDEBUG SEARCH -> page {chosen_page}/{pages_total}, chosen internal_record_id -> {internal_record_id}\n")
        if not internal_record_id:
            return

        self._get_subject_record(internal_record_id)

        section_metadata = build_section_metadata(safe_json(self._get_all_sections()))

        tabs_response = self._get_all_tabs()
        tab_ids = extract_ordered_tab_ids(safe_json(tabs_response))
        print(f"\nDEBUG TABS -> {tab_ids}\n")
        if not tab_ids:
            return

        for tab_id in tab_ids:
            self._create_change_request_for_tab(internal_record_id, tab_id, section_metadata)

    def _create_change_request_for_tab(self, internal_record_id: str, tab_id: str, section_metadata: dict):
        tab_sections_response_json = safe_json(self._get_tab_sections(tab_id))
        tab_section_ids = extract_tab_section_ids(tab_sections_response_json)
        configured_section_ids = [sid for sid in tab_section_ids if sid in CR_FIELD_BY_SECTION]
        if not configured_section_ids:
            print(f"\nDEBUG TAB {tab_id} -> no configured section, skipping\n")
            return

        section_id = random.choice(configured_section_ids)
        meta = section_metadata.get(section_id, {})
        is_core = bool(meta.get("is_core_section"))
        section_register_id = meta.get("section_register_id")
        print(f"\nDEBUG TAB {tab_id} -> chosen section {section_id} ({'CORE' if is_core else 'NON-CORE'})\n")

        field_name = CR_FIELD_BY_SECTION[section_id]
        tab_records_response = self._get_tab_records(internal_record_id, tab_id)
        record_internal_id, old_value = old_field_value(safe_json(tab_records_response), section_register_id, field_name)
        if not record_internal_id:
            print(f"\nDEBUG section {section_id} -> no record to edit, skipping\n")
            return

        schema_response_json = section_ui_schema_from_tab_sections(tab_sections_response_json, section_id)
        enum_options = static_enum_options(schema_response_json, field_name)
        print(f"\nDEBUG static_enum_options for {field_name} -> {enum_options}\n")
        if enum_options is None:
            attribute_id = api_enum_attribute_id(schema_response_json, field_name)
            print(f"\nDEBUG api_enum_attribute_id for {field_name} -> {attribute_id}\n")
            if attribute_id:
                attribute_values_response_json = safe_json(self._get_attribute_values(attribute_id))
                print(f"\nDEBUG get_attribute_values({attribute_id}) response -> {attribute_values_response_json}\n")
                enum_options = attribute_value_options(attribute_values_response_json)
        will_embed = (
            enum_options is None
            and field_name not in ("link_internal_record_id", "head_count", "functional_record_id")
        )
        embed_term = self._claim_embed_term() if will_embed else ""
        new_value = generate_new_value(
            field_name, old_value, enum_options, search_anchor=embed_term or None
        )
        print(f"\nDEBUG FIELD {field_name} -> old={old_value!r} new={new_value!r} embed={embed_term!r}\n")

        documents = None
        if meta.get("documents_required"):
            upload_response_json = safe_json(self._upload_documents())
            document_ids = extract_document_ids(upload_response_json)
            print(f"\nDEBUG section {section_id} requires documents -> uploaded {document_ids}\n")
            documents = build_document_attachments(document_ids)

        change_payload = build_change_payload(record_internal_id, field_name, new_value)
        if is_core:
            cr_response = self._create_change_request_for_core_data(
                tab_id, section_id, section_register_id, internal_record_id, change_payload, documents
            )
        else:
            cr_response = self._create_change_request(
                tab_id, section_id, section_register_id, internal_record_id, change_payload, documents
            )
        cr_response_json = safe_json(cr_response)
        print(
            f"\nDEBUG CR RESULT for {section_id} ({'CORE' if is_core else 'NON-CORE'}) -> "
            f"{response_status(cr_response_json)} {response_error_code(cr_response_json) or ''}\n"
        )

    # ------------------------------------------------------------------
    # 1 — get_register_summary_data (g2p_register_data_controller)
    # ------------------------------------------------------------------
    def _get_register_summary_data(self):
        payload = self.build_request(request_payload={"register_id": REGISTER_FARMER})
        return self._post(
            STAFF_API_BASE, "/register-data/get_register_summary_data", payload, name="get_register_summary_data"
        )

    # ------------------------------------------------------------------
    # 2 — search_in_a_register (g2p_register_data_controller)
    # ------------------------------------------------------------------
    def _search_in_a_register(self, current_page: int):
        payload = self.build_request(
            request_payload={"register_id": REGISTER_FARMER},
            pagination_request={
                "current_page": current_page,
                "page_size": SEARCH_PAGE_SIZE,
                "search_text": self.search_text,
            },
        )
        return self._post(STAFF_API_BASE, "/register-data/search_in_a_register", payload, name="search_in_a_register")

    # ------------------------------------------------------------------
    # 3 — get_subject_record (g2p_register_data_controller)
    # ------------------------------------------------------------------
    def _get_subject_record(self, internal_record_id: str):
        payload = self.build_request(
            request_payload={"subject_register_id": REGISTER_FARMER, "subject_record_id": internal_record_id},
        )
        return self._post(STAFF_API_BASE, "/register-data/get_subject_record", payload, name="get_subject_record")

    # ------------------------------------------------------------------
    # 4 — get_all_sections (g2p_register_section_metadata_controller) — register-wide, for is_core_section
    # ------------------------------------------------------------------
    def _get_all_sections(self):
        payload = self.build_request(request_payload={"register_id": REGISTER_FARMER})
        return self._post(
            STAFF_API_BASE, "/register-section-metadata/get_all_sections", payload, name="get_all_sections"
        )

    # ------------------------------------------------------------------
    # 5 — get_all_tabs (g2p_register_tab_metadata_controller)
    # ------------------------------------------------------------------
    def _get_all_tabs(self):
        payload = self.build_request(request_payload={"register_id": REGISTER_FARMER})
        return self._post(STAFF_API_BASE, "/register-tab-metadata/get_all_tabs", payload, name="get_all_tabs")

    # ------------------------------------------------------------------
    # 5a — get_sections (g2p_register_tab_metadata_controller) — sections for one tab
    # ------------------------------------------------------------------
    def _get_tab_sections(self, tab_id: str):
        payload = self.build_request(request_payload={"tab_id": tab_id})
        return self._post(STAFF_API_BASE, "/register-tab-metadata/get_sections", payload, name="get_tab_sections")

    # ------------------------------------------------------------------
    # 5b — get_tab_records (g2p_register_data_controller)
    # ------------------------------------------------------------------
    def _get_tab_records(self, internal_record_id: str, tab_id: str):
        payload = self.build_request(
            request_payload={
                "subject_register_id": REGISTER_FARMER,
                "subject_record_id": internal_record_id,
                "tab_id": tab_id,
            },
        )
        return self._post(STAFF_API_BASE, "/register-data/get_tab_records", payload, name="get_tab_records")

    # ------------------------------------------------------------------
    # 5c — get_attribute_values (g2p_attribute_controller) — allowed values for API-sourced enum fields
    # ------------------------------------------------------------------
    def _get_attribute_values(self, attribute_id: str):
        payload = self.build_request(request_payload={"attribute_id": attribute_id})
        return self._post(STAFF_API_BASE, "/attributes/get_attribute_values", payload, name="get_attribute_values")

    # ------------------------------------------------------------------
    # 5d — upload_documents (g2p_document_controller) — raw multipart, not the
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
    # 5e — create_change_request (g2p_register_change_request_controller) — non-core sections
    # ------------------------------------------------------------------
    def _create_change_request(
        self,
        tab_id: str,
        section_id: str,
        section_register_id: str,
        subject_internal_record_id: str,
        change_payload: list,
        documents: list | None = None,
    ):
        payload = self.build_request(
            request_payload={
                "register_id": REGISTER_FARMER,
                "tab_id": tab_id,
                "section_id": section_id,
                "section_register_id": section_register_id,
                # The subject Farmer's own id — the server looks this up inside
                # register_id's own table (REGISTER_FARMER), not section_register_id's.
                # The record actually being edited (which may live in a different
                # register, e.g. Land/Crop) is change_payload[].internal_record_id.
                "internal_record_id": subject_internal_record_id,
                "change_payload": change_payload,
                "documents": documents,
            },
        )
        return self._post(STAFF_API_BASE, "/change-requests/create_change_request", payload, name="create_change_request")

    # ------------------------------------------------------------------
    # 5f — create_change_request_for_core_data (g2p_change_request_core_controller) — core sections; routes to
    # this or 5e (mutually exclusive) based on section_metadata's is_core_section
    # ------------------------------------------------------------------
    def _create_change_request_for_core_data(
        self,
        tab_id: str,
        section_id: str,
        section_register_id: str,
        subject_internal_record_id: str,
        change_payload: list,
        documents: list | None = None,
    ):
        payload = self.build_request(
            request_payload={
                "register_id": REGISTER_FARMER,
                "tab_id": tab_id,
                "section_id": section_id,
                "section_register_id": section_register_id,
                "internal_record_id": subject_internal_record_id,
                "change_payload": change_payload,
                "documents": documents,
            },
        )
        return self._post(
            STAFF_API_BASE,
            "/change-requests-core-data/create_change_request_for_core_data",
            payload,
            name="create_change_request_for_core_data",
        )
