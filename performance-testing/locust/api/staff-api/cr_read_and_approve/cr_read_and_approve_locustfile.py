from __future__ import annotations

import random

from locust import tag, task

from shared.base_user import LocustUser
from shared.config import CR_SEARCH_PAGE_SIZE, REGISTER_FARMER, SEARCH_TERMS, STAFF_API_BASE
from shared.response_utils import safe_json
from shared.slo_shape import SLOStepRampShape
from cr_read_and_approve_helpers import (
    actionable_task,
    extract_awe_request_id,
    pending_change_requests,
    response_error_code,
    response_payload,
    response_status,
    search_term_candidates,
    sort_pending_oldest_first,
    total_pages,
)

CR_ARTIFACT_TYPE = "registry.change_request"


class CrReadAndApproveRampShape(SLOStepRampShape):
    """Step 1 ramp-to-failure for cr_read_and_approve -- see
    shared/slo_shape.py and documentation/staff-api/test-scenarios.md §4/§5."""


class CrReadAndApproveUser(LocustUser):
    """Pages through every change request still PENDING approval and runs each one
    through the full read-and-approve sequence: get_change_request,
    get_deduplication_register_results, get_deduplication_change_request_results,
    list_tasks_for_request, submit_task_decision. Continues, page by page, until
    the search is exhausted.

    No client-side check_change_request_sequence pre-check -- multiple pending
    CRs on the same section are no longer possible, so it can't block. Still
    processes oldest-first (see sort_pending_oldest_first): submit_task_decision
    still enforces the equivalent internal_record_id-scoped check server-side.

    Two concurrent users landing on the same search term converge on the same
    oldest-first pending pool and race AWE for the same task (same failure
    mode as intake_read_and_approve: submit_task_decision AWE-007 "already
    completed"). Those envelope ERRORs are expected business rejections and
    are counted as Locust successes (see is_expected_business_error).
    _terms_in_use is a class-level set -- shared across every
    user greenlet in this one Locust process (Locust users are gevent
    greenlets, not OS threads, and this file is always run single-process,
    `locust -f ...` with no --processes/--master/--worker -- see
    locust-staff-api.sh -- so a plain in-memory set is safe with no lock and
    needs no cross-process coordination here). A term is claimed for the
    whole processing pass, not just the search, and released in a finally so
    a mid-batch exception can't leak it.
    """

    host = STAFF_API_BASE

    # Shared across all CrReadAndApproveUser greenlets in this process.
    _terms_in_use: set[str] = set()

    def on_start(self):
        super().on_start()
        # Shuffle so concurrent users spread across anchors; rotation below
        # recovers when the sticky term has no pending CRs (common when
        # cr_create mostly edited non-farmer sections). See
        # cr_read_and_approve_helpers.search_term_candidates.
        self.search_terms = list(SEARCH_TERMS)
        random.shuffle(self.search_terms)
        self._term_index = 0
        self._claimed_term: str | None = None
        self.search_text = self.search_terms[0] if self.search_terms else ""
        print(f"\nDEBUG SEARCH_TERM initial -> {self.search_text!r}\n")

    @tag("change_request", "write")
    @task
    def read_and_approve_change_requests(self):
        self._get_register_change_request_summary_data()

        page1_json = self._find_search_with_pending()
        if page1_json is None:
            print("\nDEBUG search_in_change_request -> no PENDING CRs for any unclaimed search term (incl. broad '')\n")
            return

        try:
            # Collect every PENDING CR across pages, then approve oldest first.
            # API search order is created_at DESC; processing that order hits
            # approval_decision_blocked for newer CRs on the same record.
            all_pending: list[dict] = []
            current_page = 1
            pages_total = total_pages(page1_json)
            while current_page <= pages_total:
                search_response_json = (
                    page1_json if current_page == 1 else safe_json(self._search_in_change_request(current_page))
                )
                pages_total = total_pages(search_response_json)
                all_pending.extend(pending_change_requests(search_response_json))
                current_page += 1

            ordered = sort_pending_oldest_first(all_pending)
            print(f"\nDEBUG approving {len(ordered)} PENDING CRs oldest-first\n")
            for change_request in ordered:
                self._process_change_request(change_request)
        finally:
            # Release even on an exception mid-batch, so the term doesn't
            # stay claimed forever and starve every other user of it.
            if self._claimed_term is not None:
                self._terms_in_use.discard(self._claimed_term)
                self._claimed_term = None

    def _find_search_with_pending(self) -> dict | None:
        """Probe page 1 for each candidate term until PENDING results appear.

        Skips any term another user currently has claimed (self._terms_in_use)
        -- two users both working the same term converge on the same
        oldest-first pending pool and race AWE for the same task. Claims the
        winning term for the caller (read_and_approve_change_requests releases
        it in a finally once this user's whole batch is processed) so no other
        user can pick it up mid-batch either.

        Reuses the successful page-1 response so the task does not double-fetch.
        Advances self._term_index so the next task starts near the last hit.
        """
        candidates = search_term_candidates(self.search_terms, self._term_index)
        for term in candidates:
            if term in self._terms_in_use:
                print(f"\nDEBUG search term={term!r} already claimed by another user, skipping\n")
                if term and self.search_terms:
                    self._term_index = (self._term_index + 1) % len(self.search_terms)
                continue
            self.search_text = term
            search_response_json = safe_json(self._search_in_change_request(1))
            pending = pending_change_requests(search_response_json)
            print(
                f"\nDEBUG search_in_change_request term={term!r} -> "
                f"{len(pending)} PENDING on page 1 "
                f"(payload_len={len(response_payload(search_response_json) or [])})\n"
            )
            if pending:
                # Keep sticky on the matching anchor (not "") when possible so
                # subsequent tasks stay on a real Register-Search term.
                if term and self.search_terms:
                    self._term_index = self.search_terms.index(term)
                self._terms_in_use.add(term)
                self._claimed_term = term
                return search_response_json
            # Only advance among real anchors; "" is last-resort and not sticky.
            if term and self.search_terms:
                self._term_index = (self._term_index + 1) % len(self.search_terms)
        return None

    def _process_change_request(self, change_request: dict):
        change_request_id = change_request["change_request_id"]
        section_id = change_request.get("section_id")

        self._get_change_request_documents(change_request_id)
        if section_id:
            self._get_section_ui_schema(section_id)
        change_request_response_json = safe_json(self._get_change_request(change_request_id))

        self._get_deduplication_change_request_results(change_request_id)
        self._get_deduplication_register_results(change_request_id)

        awe_request_id = extract_awe_request_id(change_request_response_json)
        if not awe_request_id:
            return

        tasks_response_json = safe_json(self._list_tasks_for_request(awe_request_id))
        task = actionable_task(tasks_response_json)
        if not task:
            return

        decision_response_json = safe_json(
            self._submit_task_decision(
                task_id=task["id"],
                artifact_id=change_request_id,
                current_stage=task.get("stage_order") or 1,
            )
        )
        print(
            f"\nDEBUG DECISION RESULT for {change_request_id} -> "
            f"{response_status(decision_response_json)} {response_error_code(decision_response_json) or ''}\n"
        )

    # ------------------------------------------------------------------
    # get_register_change_request_summary_data (g2p_register_change_request_controller)
    # ------------------------------------------------------------------
    def _get_register_change_request_summary_data(self):
        payload = self.build_request(request_payload={})
        return self._post(
            STAFF_API_BASE,
            "/change-requests/get_register_change_request_summary_data",
            payload,
            name="get_register_change_request_summary_data",
        )

    # ------------------------------------------------------------------
    # search_in_change_request (g2p_register_change_request_controller)
    # ------------------------------------------------------------------
    def _search_in_change_request(self, current_page: int):
        payload = self.build_request(
            request_payload={},
            pagination_request={
                "current_page": current_page,
                "page_size": CR_SEARCH_PAGE_SIZE,
                "search_text": self.search_text,
                "filter_by": {
                    "approval_status": {"eq": "PENDING"},
                    "register_id": {"eq": REGISTER_FARMER},
                },
            },
        )
        return self._post(
            STAFF_API_BASE, "/change-requests/search_in_change_request", payload, name="search_in_change_request"
        )

    # ------------------------------------------------------------------
    # get_change_request_documents (g2p_document_controller)
    # ------------------------------------------------------------------
    def _get_change_request_documents(self, change_request_id: str):
        payload = self.build_request(request_payload={"change_request_id": change_request_id})
        return self._post(
            STAFF_API_BASE,
            "/documents/get_change_request_documents",
            payload,
            name="get_change_request_documents",
        )

    # ------------------------------------------------------------------
    # get_section_ui_schema (g2p_register_section_metadata_controller)
    # ------------------------------------------------------------------
    def _get_section_ui_schema(self, section_id: str):
        payload = self.build_request(request_payload={"section_id": section_id, "register_id": REGISTER_FARMER})
        return self._post(
            STAFF_API_BASE, "/register-section-metadata/get_section_ui_schema", payload, name="get_section_ui_schema"
        )

    # ------------------------------------------------------------------
    # get_change_request (g2p_register_change_request_controller)
    # ------------------------------------------------------------------
    def _get_change_request(self, change_request_id: str):
        payload = self.build_request(request_payload={"change_request_id": change_request_id})
        return self._post(STAFF_API_BASE, "/change-requests/get_change_request", payload, name="get_change_request")

    # ------------------------------------------------------------------
    # list_tasks_for_request (g2p_awe_proxy_controller)
    # ------------------------------------------------------------------
    def _list_tasks_for_request(self, awe_request_id: str):
        payload = self.build_request(request_payload={"request_id": awe_request_id})
        return self._post(
            STAFF_API_BASE,
            "/awe/list_tasks_for_request",
            payload,
            name="list_tasks_for_request",
        )

    # ------------------------------------------------------------------
    # submit_task_decision (g2p_awe_proxy_controller)
    # ------------------------------------------------------------------
    def _submit_task_decision(self, task_id: str, artifact_id: str, current_stage: int):
        payload = self.build_request(
            request_payload={
                "task_id": task_id,
                "action": "approve",
                "artifact_id": artifact_id,
                "artifact_type": CR_ARTIFACT_TYPE,
                "current_stage": current_stage,
            },
        )
        return self._post(
            STAFF_API_BASE,
            "/awe/submit_task_decision",
            payload,
            name="submit_task_decision",
        )

    # ------------------------------------------------------------------
    # get_deduplication_register_results (g2p_register_data_controller)
    # ------------------------------------------------------------------
    def _get_deduplication_register_results(self, change_request_id: str):
        payload = self.build_request(request_payload={"change_request_id": change_request_id})
        return self._post(
            STAFF_API_BASE,
            "/register-data/get_deduplication_register_results",
            payload,
            name="get_deduplication_register_results",
        )

    # ------------------------------------------------------------------
    # get_deduplication_change_request_results (g2p_register_data_controller)
    # ------------------------------------------------------------------
    def _get_deduplication_change_request_results(self, change_request_id: str):
        payload = self.build_request(request_payload={"change_request_id": change_request_id})
        return self._post(
            STAFF_API_BASE,
            "/register-data/get_deduplication_change_request_results",
            payload,
            name="get_deduplication_change_request_results",
        )
