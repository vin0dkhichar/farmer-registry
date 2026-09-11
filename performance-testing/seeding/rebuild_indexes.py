#!/usr/bin/env python3
"""Create model-declared indexes that the 10M seed left missing on live tables.

History btrees were already rebuilt. This restores live UNIQUE/btree/GIN,
intake GIN + uniques, and the AWE lookup index. Safe to re-run (IF NOT EXISTS).
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import psycopg2
from psycopg2 import errors


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [rebuild] {msg}", flush=True)


def dsn() -> str:
    if any(k in os.environ for k in ("PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD")):
        host = os.environ.get("PGHOST", "localhost")
        port = os.environ.get("PGPORT", "5432")
        db = os.environ.get("PGDATABASE", "farmer_registry")
        user = os.environ.get("PGUSER", "postgres")
        password = os.environ.get("PGPASSWORD", "")
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"
    return os.environ.get(
        "SEED_DB_DSN",
        "postgresql://postgres:postgres@localhost:5432/farmer_registry",
    )


def redact(url: str) -> str:
    try:
        p = urlparse(url)
        if p.password:
            return url.replace(p.password, "***")
    except Exception:
        pass
    return url


def idx(name: str, table: str, cols: str, unique: bool = False, using: str | None = None) -> tuple[str, str]:
    kind = "UNIQUE INDEX" if unique else "INDEX"
    using_sql = f" USING {using}" if using else ""
    sql = f"CREATE {kind} IF NOT EXISTS {name} ON {table}{using_sql} ({cols})"
    return (f"{table}.{name}", sql)


def btree_fallback(name: str, table: str, cols: str) -> str:
    return f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"


LIVE_CORE = (
    "functional_record_id",
    "link_internal_record_id",
    "link_foundational_id",
    "last_approved_at",
)
GEO = ("plus_code", "postal_code", "country_code", "geo_lowest_level_value_id")
PERSON = ("foundational_id",)

LIVE_TABLES = [
    ("g2p_register_livestocks", ()),
    ("g2p_register_farm_inputs", ()),
    ("g2p_register_membership_details", ()),
    ("g2p_register_households", GEO),
    ("g2p_register_farmers", PERSON + GEO),
    ("g2p_register_household_members", PERSON + GEO),
    ("g2p_register_lands", GEO),
    ("g2p_register_crops", ()),
]

INTAKE_TABLES = (
    "g2p_intake_form_farmers",
    "g2p_intake_form_households",
    "g2p_intake_form_household_members",
    "g2p_intake_form_lands",
    "g2p_intake_form_crops",
    "g2p_intake_form_livestocks",
    "g2p_intake_form_farm_inputs",
    "g2p_intake_form_membership_details",
)

GIN_LIVE_ORDER = (
    "g2p_register_farmers",
    "g2p_register_households",
    "g2p_register_household_members",
    "g2p_register_lands",
    "g2p_register_livestocks",
    "g2p_register_farm_inputs",
    "g2p_register_membership_details",
    "g2p_register_crops",
)


def fts_gin(name: str, table: str) -> tuple[str, str]:
    sql = (
        f"CREATE INDEX IF NOT EXISTS {name} ON {table} "
        f"USING gin (to_tsvector('simple', coalesce(search_text, '')))"
    )
    return (f"{table}.{name}", sql)


def plan() -> list[tuple[str, str]]:
    steps: list[tuple[str, str]] = []
    steps.append(idx(
        "ix_awe_req_events_artifact_lookup",
        "awe_req_events",
        "artifact_type, artifact_id, applied, occurred_at, received_at",
    ))
    for table in INTAKE_TABLES:
        steps.append(idx(
            f"idx_{table}_search_text_trigram",
            table,
            "search_text gin_trgm_ops",
            using="gin",
        ))
        steps.append(fts_gin(f"idx_{table}_search_text_fts", table))
        steps.append(idx(f"{table}_application_reference_key", table, "application_reference", unique=True))
        steps.append(idx(f"{table}_submission_id_key", table, "submission_id", unique=True))
    for table, extra in LIVE_TABLES:
        steps.append(idx(f"{table}_functional_record_id_key", table, "functional_record_id", unique=True))
        for col in LIVE_CORE[1:]:
            steps.append(idx(f"ix_{table}_{col}", table, col))
        for col in extra:
            steps.append(idx(f"ix_{table}_{col}", table, col))
    for table in GIN_LIVE_ORDER:
        steps.append(idx(
            f"idx_{table}_search_text_trigram",
            table,
            "search_text gin_trgm_ops",
            using="gin",
        ))
        steps.append(fts_gin(f"idx_{table}_search_text_fts", table))
    steps.append(idx(
        "ix_g2p_register_change_request_payloads_search_text_gin",
        "g2p_register_change_request_payloads",
        "search_text gin_trgm_ops",
        using="gin",
    ))
    steps.append(fts_gin(
        "ix_g2p_register_change_request_payloads_search_text_fts",
        "g2p_register_change_request_payloads",
    ))
    return steps


def analyze_tables() -> list[str]:
    return [t for t, _ in LIVE_TABLES] + list(INTAKE_TABLES) + [
        "awe_req_events",
        "g2p_register_change_request_payloads",
    ]


def run_sql(cur, label: str, sql: str, allow_unique_fallback: bool = True) -> str:
    started = time.monotonic()
    log(f"START {label}")
    try:
        cur.execute(sql)
        log(f"OK    {label} in {time.monotonic() - started:.0f}s")
        return "ok"
    except errors.DuplicateTable:
        log(f"SKIP  {label} (already exists) in {time.monotonic() - started:.0f}s")
        return "skip"
    except (errors.UniqueViolation, errors.IntegrityError) as exc:
        if allow_unique_fallback and "UNIQUE INDEX" in sql:
            fallback_name = label.split(".", 1)[-1]
            table = label.split(".", 1)[0]
            cols = sql.rsplit("(", 1)[-1].rstrip(")")
            detail = getattr(exc.diag, "message_primary", None) or str(exc)
            log(f"WARN  {label} unique failed ({detail}); falling back to btree")
            return run_sql(cur, f"{label}#btree", btree_fallback(fallback_name, table, cols), False)
        log(f"FAIL  {label} unique: {exc}")
        return "fail"
    except Exception as exc:
        log(f"FAIL  {label}: {exc}")
        return "fail"


def reset_session(cur) -> None:
    """Undo session-only SETs. Does not touch postgresql.conf / ALTER SYSTEM."""
    for stmt in (
        "RESET maintenance_work_mem",
        "RESET work_mem",
        "RESET synchronous_commit",
    ):
        cur.execute(stmt)
        log(f"session {stmt}")


def main() -> int:
    url = dsn()
    log(f"connecting {redact(url)}")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    counts = {"ok": 0, "skip": 0, "fail": 0}
    failed: list[str] = []
    wall = time.monotonic()
    try:
        for stmt in (
            "SET maintenance_work_mem TO '2GB'",
            "SET work_mem TO '256MB'",
            "SET synchronous_commit TO off",
            "CREATE EXTENSION IF NOT EXISTS pg_trgm",
        ):
            cur.execute(stmt)
            log(f"session {stmt}")

        steps = plan()
        log(f"{len(steps)} index statements")
        for i, (label, sql) in enumerate(steps, start=1):
            log(f"[{i}/{len(steps)}] {label}")
            result = run_sql(cur, label, sql)
            counts[result] += 1
            if result == "fail":
                failed.append(label)

        log("ANALYZE starting")
        for table in analyze_tables():
            started = time.monotonic()
            try:
                cur.execute(f"ANALYZE {table}")
                log(f"ANALYZE {table} in {time.monotonic() - started:.0f}s")
            except Exception as exc:
                log(f"ANALYZE FAIL {table}: {exc}")
                counts["fail"] += 1
                failed.append(f"ANALYZE {table}")
    finally:
        try:
            reset_session(cur)
        except Exception as exc:
            log(f"RESET failed: {exc}")
        cur.close()
        conn.close()

    log(
        f"done wall={time.monotonic() - wall:.0f}s "
        f"ok={counts['ok']} skip={counts['skip']} fail={counts['fail']}"
    )
    if failed:
        log("failed: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
