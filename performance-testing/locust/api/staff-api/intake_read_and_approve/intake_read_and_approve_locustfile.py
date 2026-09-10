from __future__ import annotations

import random
import uuid

from locust import tag, task

from shared.base_user import LocustUser
from shared.config import (
    INTAKE_SEARCH_HIT_RATE,
    INTAKE_SEARCH_PAGE_SIZE,
    REGISTER_FARMER,
    SEARCH_TERMS,
    STAFF_API_BASE,
)
from shared.response_utils import safe_json
from shared.slo_shape import SLOStepRampShape
from intake_read_and_approve_helpers import (
    actionable_task,
    extract_awe_request_id,
    pending_submissions,
    response_payload,
    search_term_candidates,
    sort_pending_oldest_first,
    total_pages,
)

INTAKE_ARTIFACT_TYPE = "registry.intake_form"


class IntakeReadAndApproveRampShape(SLOStepRampShape):
    """Step 1 ramp-to-failure for intake_read_and_approve -- see
    shared/slo_shape.py and documentation/staff-api/test-scenarios.md §4/§5."""


class IntakeReadAndApproveUser(LocustUser):
    """Approves FINAL+PENDING intake submissions found via search.

    ~INTAKE_SEARCH_HIT_RATE of tasks search for real work (pool anchors,
    then broad '' fallback) and approve oldest-first. The remaining ~20%
    deliberately search a unique miss-token so empty-result latency is
    measured without approving. Matches intake_create's 80/20 embed rate.

    Two concurrent users landing on the same search term converge on the same
    oldest-first pending pool and race AWE for the same task (observed as
    submit_task_decision AWE-007 "already completed"). Those envelope
    ERRORs are expected business rejections and are counted as Locust
    successes (see is_expected_business_error). _terms_in_use
    is a class-level set -- shared across every user greenlet in this one
    Locust process (Locust users are gevent greenlets, not OS threads, and
    this file is always run single-process, `locust -f ...` with no
    --processes/--master/--worker -- see locust-staff-api.sh -- so a plain
    in-memory set is safe with no lock and needs no cross-process coordination
    here). A term is claimed for the whole processing pass, not just the
    search, and released in a finally so a mid-batch exception can't leak it.
    """

    host = STAFF_API_BASE

    # Shared across all IntakeReadAndApproveUser greenlets in this process.
    _terms_in_use: set[str] = set()

    def on_start(self):
        super().on_start()
        self.search_terms = list(SEARCH_TERMS)
        random.shuffle(self.search_terms)
        self._term_index = 0
        self._claimed_term: str | None = None
        self.search_text = self.search_terms[0] if self.search_terms else ""
        print(f"\nDEBUG SEARCH_TERM initial -> {self.search_text!r}\n")

    @tag("intake", "write")
    @task
    def read_and_approve_pending_intakes(self):
        self._get_intake_form_submissions_summary()

        # ~20%: exercise empty search path only (no approve).
        if random.random() >= INTAKE_SEARCH_HIT_RATE:
            self.search_text = f"xmiss{uuid.uuid4().hex[:12]}"
            search_response_json = safe_json(self._search_in_intake_form_submissions(1))
            pending = pending_submissions(search_response_json)
            print(
                f"\nDEBUG intentional miss term={self.search_text!r} -> "
                f"{len(pending)} PENDING (expect 0)\n"
            )
            return

        page1_json = self._find_search_with_pending()
        if page1_json is None:
            print(
                "\nDEBUG search_in_intake_form_submissions -> "
                "no FINAL+PENDING submissions for any unclaimed search term (incl. broad '')\n"
            )
            return

        try:
            all_pending: list[dict] = []
            current_page = 1
            pages_total = total_pages(page1_json)
            while current_page <= pages_total:
                search_response_json = (
                    page1_json if current_page == 1 else safe_json(self._search_in_intake_form_submissions(current_page))
                )
                pages_total = total_pages(search_response_json)
                all_pending.extend(pending_submissions(search_response_json))
                current_page += 1

            ordered = sort_pending_oldest_first(all_pending)
            print(f"\nDEBUG approving {len(ordered)} FINAL+PENDING intakes oldest-first (term={self.search_text!r})\n")
            for submission in ordered:
                self._process_submission(submission["submission_id"])
        finally:
            # Release even on an exception mid-batch, so the term doesn't
            # stay claimed forever and starve every other user of it.
            if self._claimed_term is not None:
                self._terms_in_use.discard(self._claimed_term)
                self._claimed_term = None

    def _find_search_with_pending(self) -> dict | None:
        """Probe page 1 for each candidate term until FINAL+PENDING results appear.

        Skips any term another user currently has claimed (self._terms_in_use)
        -- two users both working the same term converge on the same
        oldest-first pending pool and race AWE for the same task. Claims the
        winning term for the caller (read_and_approve_pending_intakes releases
        it in a finally once this user's whole batch is processed) so no other
        user can pick it up mid-batch either.

        Reuses the successful page-1 response so the task does not double-fetch.
        Empty search_text is last resort: API skips ILIKE and returns all
        submissions for the register -- also claimed exclusively, same reason.
        """
        candidates = search_term_candidates(self.search_terms, self._term_index)
        for term in candidates:
            if term in self._terms_in_use:
                print(f"\nDEBUG search term={term!r} already claimed by another user, skipping\n")
                if term and self.search_terms:
                    self._term_index = (self._term_index + 1) % len(self.search_terms)
                continue
            self.search_text = term
            search_response_json = safe_json(self._search_in_intake_form_submissions(1))
            pending = pending_submissions(search_response_json)
            print(
                f"\nDEBUG search_in_intake_form_submissions term={term!r} -> "
                f"{len(pending)} FINAL+PENDING on page 1 "
                f"(payload_len={len(response_payload(search_response_json) or [])})\n"
            )
            if pending:
                if term and self.search_terms:
                    self._term_index = self.search_terms.index(term)
                self._terms_in_use.add(term)
                self._claimed_term = term
                return search_response_json
            if term and self.search_terms:
                self._term_index = (self._term_index + 1) % len(self.search_terms)
        return None

    def _process_submission(self, submission_id: str):
        submission_response_json = safe_json(self._get_intake_form_submission(submission_id))

        self._get_intake_form_documents(submission_id)
        self._get_deduplication_intake_form_register_results(submission_id)
        self._get_deduplication_intake_form_intake_form_results(submission_id)

        awe_request_id = extract_awe_request_id(submission_response_json)
        if not awe_request_id:
            return

        tasks_response_json = safe_json(self._list_tasks_for_request(awe_request_id))
        task = actionable_task(tasks_response_json)
        if not task:
            return

        self._submit_task_decision(
            task_id=task["id"],
            artifact_id=submission_id,
            current_stage=task.get("stage_order") or 1,
        )

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
    # search_in_intake_form_submissions (g2p_intake_form_data_controller)
    # ------------------------------------------------------------------
    def _search_in_intake_form_submissions(self, current_page: int):
        payload = self.build_request(
            request_payload={"register_id": REGISTER_FARMER},
            pagination_request={
                "current_page": current_page,
                "page_size": INTAKE_SEARCH_PAGE_SIZE,
                "search_text": self.search_text,
                "filter_by": {
                    "draft_status": {"eq": "FINAL"},
                    "approval_status": {"eq": "PENDING"},
                },
            },
        )
        return self._post(
            STAFF_API_BASE,
            "/intake-form-data/search_in_intake_form_submissions",
            payload,
            name="search_in_intake_form_submissions",
        )

    # ------------------------------------------------------------------
    # get_intake_form_submission (g2p_intake_form_data_controller)
    # ------------------------------------------------------------------
    def _get_intake_form_submission(self, submission_id: str):
        payload = self.build_request(request_payload={"submission_id": submission_id})
        return self._post(
            STAFF_API_BASE,
            "/intake-form-data/get_intake_form_submission",
            payload,
            name="get_intake_form_submission",
        )

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
                "artifact_type": INTAKE_ARTIFACT_TYPE,
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
    # get_intake_form_documents (g2p_document_controller)
    # ------------------------------------------------------------------
    def _get_intake_form_documents(self, submission_id: str):
        payload = self.build_request(request_payload={"submission_id": submission_id})
        return self._post(
            STAFF_API_BASE,
            "/documents/get_intake_form_documents",
            payload,
            name="get_intake_form_documents",
        )

    # ------------------------------------------------------------------
    # get_deduplication_intake_form_register_results (g2p_intake_form_data_controller)
    # ------------------------------------------------------------------
    def _get_deduplication_intake_form_register_results(self, submission_id: str):
        payload = self.build_request(request_payload={"submission_id": submission_id})
        return self._post(
            STAFF_API_BASE,
            "/intake-form-data/get_deduplication_intake_form_register_results",
            payload,
            name="get_deduplication_intake_form_register_results",
        )

    # ------------------------------------------------------------------
    # get_deduplication_intake_form_intake_form_results (g2p_intake_form_data_controller)
    # ------------------------------------------------------------------
    def _get_deduplication_intake_form_intake_form_results(self, submission_id: str):
        payload = self.build_request(request_payload={"submission_id": submission_id})
        return self._post(
            STAFF_API_BASE,
            "/intake-form-data/get_deduplication_intake_form_intake_form_results",
            payload,
            name="get_deduplication_intake_form_intake_form_results",
        )
