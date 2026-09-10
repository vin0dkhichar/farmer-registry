"""Pure parsing/selection helpers for the intake read-and-approve flow.

Kept separate from intake_read_and_approve_locustfile.py so the business
logic of paging through search results and picking out pending submissions
can be read (and tested) independently of the actual HTTP calls.
"""
from __future__ import annotations

from typing import Any, Optional


def response_payload(response_json: dict) -> Any:
    return (response_json or {}).get("response_body", {}).get("response_payload")


def total_pages(search_response_json: dict) -> int:
    pagination = (search_response_json or {}).get("response_body", {}).get("pagination_response") or {}
    return pagination.get("number_of_pages") or 1


def pending_submissions(search_response_json: dict) -> list[dict]:
    """FINAL+PENDING submissions on this page (full result dicts).

    search_in_intake_form_submissions now defaults to those statuses (and Locust
    sends the same filter_by), matching register search's ACTIVE default.
    Local filter remains so a mixed page cannot approve drafts or done rows.
    """
    submissions = response_payload(search_response_json) or []
    return [
        submission
        for submission in submissions
        if submission.get("draft_status") == "FINAL"
        and submission.get("approval_status") == "PENDING"
        and submission.get("submission_id")
    ]


def pending_submission_ids(search_response_json: dict) -> list[str]:
    """submission_ids of submissions on this page ready to approve."""
    return [submission["submission_id"] for submission in pending_submissions(search_response_json)]


def sort_pending_oldest_first(pending: list[dict]) -> list[dict]:
    """Oldest FINAL+PENDING submissions first (by first_created_at).

    Default search order is last_updated_at DESC, so page-order processing
    tends to hit newest drafts/approvals first. Prefer creation order for a
    stable approve queue.
    """
    return sorted(
        pending,
        key=lambda row: (
            row.get("first_created_at") or row.get("created_at") or "",
            row.get("submission_id") or "",
        ),
    )


def search_term_candidates(
    search_terms: list[str],
    start_index: int = 0,
    max_anchor_probes: int = 10,
) -> list[str]:
    """Ordered search texts to try on the ~80% hit path.

    Probe up to max_anchor_probes pool anchors (aligned with intake_create's
    sticky embeds), then "" — empty search_text skips ILIKE and returns all
    submissions for the register. The ~20% miss path does NOT use this list;
    it searches a unique xmiss* token instead (see locustfile).
    """
    terms = [term for term in search_terms if term]
    if not terms:
        return [""]
    start = start_index % len(terms)
    rotated = terms[start:] + terms[:start]
    return rotated[:max_anchor_probes] + [""]


def extract_awe_request_id(submission_response_json: dict) -> Optional[str]:
    """awe_request_id off get_intake_form_submission's response -- the id
    list_tasks_for_request needs, distinct from submission_id itself."""
    payload = response_payload(submission_response_json) or {}
    return payload.get("awe_request_id")


def actionable_task(list_tasks_response_json: dict) -> Optional[dict]:
    """First open/claimed task from list_tasks_for_request's response.items --
    the one submit_task_decision should act on."""
    payload = response_payload(list_tasks_response_json) or {}
    items = payload.get("data", {}).get("items") or []
    for item in items:
        if item.get("status") in ("open", "claimed") and item.get("id"):
            return item
    return None
