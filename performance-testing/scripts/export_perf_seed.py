#!/usr/bin/env python3
"""Export Locust search terms and household ids into openg2p/perf-seed/.

Creates the folder if missing and overwrites the txt files on each run.

Terms are taken from tokens that already appear in search_text (one GROUP BY
per source), not by probing guessed 4-char needles. Prefers tokens whose
row count is 1k–2k; if that band is thin, keeps other tokens at or below
the 2k cap, closest to the band.

Usage:
    cd farmer-registry/performance-testing
    source seeding/dsn.sh
    python3 scripts/export_perf_seed.py
    python3 scripts/export_perf_seed.py --source register
    python3 scripts/export_perf_seed.py --source intake cr
    python3 scripts/export_perf_seed.py --source household
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

SCRIPT_DIR = Path(__file__).resolve().parent
PERF_ROOT = SCRIPT_DIR.parent
OPENG2P_ROOT = PERF_ROOT.parent.parent
DEFAULT_OUT_DIR = OPENG2P_ROOT / "perf-seed"

TOKEN_SPLIT = r"[^[:alnum:]]+"


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} [perf-seed] {msg}", flush=True)


def redact(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.password:
            return url.replace(parsed.password, "***")
    except Exception:
        pass
    return url


def connect():
    pghost = os.environ.get("PGHOST")
    if pghost:
        user = os.environ.get("PGUSER", "farmer_registry_user")
        db = os.environ.get("PGDATABASE", "farmer_registry")
        port = os.environ.get("PGPORT", "5432")
        log(f"connecting postgresql://{user}:***@{pghost}:{port}/{db}")
        conn = psycopg2.connect(
            host=pghost,
            port=port,
            dbname=db,
            user=user,
            password=os.environ.get("PGPASSWORD", ""),
        )
    else:
        url = os.environ.get("SEED_DB_DSN")
        if not url:
            raise SystemExit("set PGHOST (source seeding/dsn.sh) or SEED_DB_DSN")
        log(f"connecting {redact(url)}")
        conn = psycopg2.connect(url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '15min'")
        cur.execute("SET work_mem = '256MB'")
    return conn


def write_terms(path: Path, rows: list[tuple[str, int]], header: str, rng: random.Random) -> None:
    shuffled = list(rows)
    rng.shuffle(shuffled)
    lines = [f"# {header}", f"# generated_at={datetime.now(timezone.utc).isoformat()}"]
    lines.extend(f"# {term}\t{hits}" for term, hits in shuffled if hits)
    lines.append("")
    lines.extend(term for term, _ in shuffled)
    path.write_text("\n".join(lines) + "\n")
    log(f"wrote {path} ({len(shuffled)} terms)")


def write_ids(path: Path, ids: list[str], header: str, rng: random.Random) -> None:
    unique = list(dict.fromkeys(ids))
    rng.shuffle(unique)
    lines = [f"# {header}", f"# generated_at={datetime.now(timezone.utc).isoformat()}", ""]
    lines.extend(unique)
    path.write_text("\n".join(lines) + "\n")
    log(f"wrote {path} ({len(unique)} ids)")


def choose_limit(rng: random.Random, available: int, lo: int, hi: int) -> int:
    if available <= 0:
        return 0
    if available <= lo:
        return available
    return min(available, rng.randint(lo, hi))


HOUSEHOLD_SAMPLE_SQL = """
SELECT internal_record_id::text
FROM g2p_register_households TABLESAMPLE SYSTEM (2)
WHERE record_status = 'ACTIVE'
  AND internal_record_id IS NOT NULL
LIMIT %s
"""

REGISTER_TOKENS_SQL = f"""
SELECT term, hits
FROM (
    SELECT lower(token) AS term, count(*)::bigint AS hits
    FROM g2p_register_farmers
    CROSS JOIN LATERAL regexp_split_to_table(search_text, %s) AS token
    WHERE record_status = 'ACTIVE'
      AND search_text IS NOT NULL
      AND length(token) BETWEEN 3 AND 24
      AND token ~ '^[A-Za-z]'
    GROUP BY 1
) counted
WHERE hits <= %(hit_max)s
ORDER BY
    CASE WHEN hits BETWEEN %(hit_min)s AND %(hit_max)s THEN 0 ELSE 1 END,
    abs(hits - %(mid)s),
    hits DESC
LIMIT %(limit)s
"""

INTAKE_PENDING_TOKENS_SQL = f"""
SELECT term, hits
FROM (
    SELECT lower(token) AS term, count(DISTINCT i.submission_id)::bigint AS hits
    FROM g2p_intake_form_farmers i
    JOIN g2p_intake_form_submissions s ON s.submission_id = i.submission_id
    CROSS JOIN LATERAL regexp_split_to_table(i.search_text, %s) AS token
    WHERE i.search_text IS NOT NULL
      AND s.draft_status = 'FINAL'
      AND s.approval_status = 'PENDING'
      AND length(token) BETWEEN 3 AND 24
      AND token ~ '^[A-Za-z]'
    GROUP BY 1
) counted
WHERE hits <= %(hit_max)s
ORDER BY
    CASE WHEN hits BETWEEN %(hit_min)s AND %(hit_max)s THEN 0 ELSE 1 END,
    abs(hits - %(mid)s),
    hits DESC
LIMIT %(limit)s
"""

INTAKE_ALL_TOKENS_SQL = f"""
SELECT term, hits
FROM (
    SELECT lower(token) AS term, count(DISTINCT i.submission_id)::bigint AS hits
    FROM g2p_intake_form_farmers i
    CROSS JOIN LATERAL regexp_split_to_table(i.search_text, %s) AS token
    WHERE i.search_text IS NOT NULL
      AND length(token) BETWEEN 3 AND 24
      AND token ~ '^[A-Za-z]'
    GROUP BY 1
) counted
WHERE hits <= %(hit_max)s
ORDER BY
    CASE WHEN hits BETWEEN %(hit_min)s AND %(hit_max)s THEN 0 ELSE 1 END,
    abs(hits - %(mid)s),
    hits DESC
LIMIT %(limit)s
"""

CR_PENDING_TOKENS_SQL = f"""
SELECT term, hits
FROM (
    SELECT lower(token) AS term, count(*)::bigint AS hits
    FROM g2p_register_change_request_payloads p
    JOIN g2p_register_change_requests cr
      ON cr.change_request_id = p.change_request_id
    CROSS JOIN LATERAL regexp_split_to_table(p.search_text, %s) AS token
    WHERE p.search_text IS NOT NULL
      AND cr.approval_status = 'PENDING'
      AND length(token) BETWEEN 3 AND 24
      AND token ~ '^[A-Za-z]'
    GROUP BY 1
) counted
WHERE hits <= %(hit_max)s
ORDER BY
    CASE WHEN hits BETWEEN %(hit_min)s AND %(hit_max)s THEN 0 ELSE 1 END,
    abs(hits - %(mid)s),
    hits DESC
LIMIT %(limit)s
"""

CR_ALL_TOKENS_SQL = f"""
SELECT term, hits
FROM (
    SELECT lower(token) AS term, count(*)::bigint AS hits
    FROM g2p_register_change_request_payloads p
    CROSS JOIN LATERAL regexp_split_to_table(p.search_text, %s) AS token
    WHERE p.search_text IS NOT NULL
      AND length(token) BETWEEN 3 AND 24
      AND token ~ '^[A-Za-z]'
    GROUP BY 1
) counted
WHERE hits <= %(hit_max)s
ORDER BY
    CASE WHEN hits BETWEEN %(hit_min)s AND %(hit_max)s THEN 0 ELSE 1 END,
    abs(hits - %(mid)s),
    hits DESC
LIMIT %(limit)s
"""


def fetch_tokens(cur, sql: str, *, hit_min: int, hit_max: int, limit: int) -> list[tuple[str, int]]:
    """Bind split pattern plus hit-band params. hit_max appears twice in SQL."""
    mid = (hit_min + hit_max) // 2
    numbered = (
        sql.replace("%(hit_max)s", "%s")
        .replace("%(hit_min)s", "%s")
        .replace("%(mid)s", "%s")
        .replace("%(limit)s", "%s")
    )
    cur.execute(numbered, (TOKEN_SPLIT, hit_max, hit_min, hit_max, mid, limit))
    return [(str(term), int(hits)) for term, hits in cur.fetchall() if term]


SOURCES = ("register", "household", "intake", "cr")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        nargs="+",
        choices=SOURCES,
        default=list(SOURCES),
        help="Only export these (default: all). Examples: --source register | --source intake cr",
    )
    parser.add_argument(
        "--out-dir",
        default=os.environ.get("PERF_SEED_DIR", str(DEFAULT_OUT_DIR)),
        help="Destination folder (created if missing, files overwritten)",
    )
    parser.add_argument("--hit-min", type=int, default=int(os.environ.get("PERF_SEED_HIT_MIN", "1000")))
    parser.add_argument("--hit-max", type=int, default=int(os.environ.get("PERF_SEED_HIT_MAX", "2000")))
    parser.add_argument("--register-min-terms", type=int, default=int(os.environ.get("PERF_SEED_REGISTER_MIN", "7000")))
    parser.add_argument("--register-max-terms", type=int, default=int(os.environ.get("PERF_SEED_REGISTER_MAX", "8000")))
    parser.add_argument("--other-min-terms", type=int, default=int(os.environ.get("PERF_SEED_OTHER_MIN", "5000")))
    parser.add_argument("--other-max-terms", type=int, default=int(os.environ.get("PERF_SEED_OTHER_MAX", "6000")))
    parser.add_argument(
        "--household-min-ids",
        type=int,
        default=int(os.environ.get("PERF_SEED_HOUSEHOLD_MIN", "5000")),
    )
    parser.add_argument(
        "--household-max-ids",
        type=int,
        default=int(os.environ.get("PERF_SEED_HOUSEHOLD_MAX", "6000")),
    )
    parser.add_argument("--seed", type=int, default=int(os.environ.get("PERF_SEED_RNG", "571")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.hit_min > args.hit_max:
        raise SystemExit("--hit-min must be <= --hit-max")
    if args.register_min_terms > args.register_max_terms:
        raise SystemExit("--register-min-terms must be <= --register-max-terms")
    if args.other_min_terms > args.other_max_terms:
        raise SystemExit("--other-min-terms must be <= --other-max-terms")
    if args.household_min_ids > args.household_max_ids:
        raise SystemExit("--household-min-ids must be <= --household-max-ids")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    register_limit = rng.randint(args.register_min_terms, args.register_max_terms)
    other_limit = rng.randint(args.other_min_terms, args.other_max_terms)

    sources = set(args.source)
    log(f"out={out_dir} sources={sorted(sources)} register_limit={register_limit} other_limit={other_limit}")

    conn = connect()
    register_rows: list[tuple[str, int]] = []
    intake_rows: list[tuple[str, int]] = []
    cr_rows: list[tuple[str, int]] = []
    try:
        with conn.cursor() as cur:
            if "register" in sources:
                log("aggregating register search_text tokens (one query)")
                register_rows = fetch_tokens(
                    cur,
                    REGISTER_TOKENS_SQL,
                    hit_min=args.hit_min,
                    hit_max=args.hit_max,
                    limit=register_limit,
                )
                in_band = sum(1 for _term, hits in register_rows if args.hit_min <= hits <= args.hit_max)
                log(f"register tokens={len(register_rows)} in_band={in_band}")
                write_terms(
                    out_dir / "register_search_terms.txt",
                    register_rows,
                    f"g2p_register_farmers search_text tokens hit_max={args.hit_max}",
                    rng,
                )

            if "household" in sources:
                household_target = rng.randint(args.household_min_ids, args.household_max_ids)
                household_ids: list[str] = []
                remaining = household_target
                attempts = 0
                while len(household_ids) < household_target and attempts < 8:
                    attempts += 1
                    cur.execute(HOUSEHOLD_SAMPLE_SQL, (remaining,))
                    household_ids.extend(row[0] for row in cur.fetchall() if row and row[0])
                    household_ids = list(dict.fromkeys(household_ids))
                    remaining = household_target - len(household_ids)
                household_ids = household_ids[:household_target]
                log(f"household ids={len(household_ids)}")
                write_ids(
                    out_dir / "household_ids.txt",
                    household_ids,
                    "ACTIVE g2p_register_households.internal_record_id sample",
                    rng,
                )

            if "intake" in sources:
                log("aggregating intake PENDING search_text tokens (one query)")
                intake_rows = fetch_tokens(
                    cur,
                    INTAKE_PENDING_TOKENS_SQL,
                    hit_min=args.hit_min,
                    hit_max=args.hit_max,
                    limit=other_limit,
                )
                if len(intake_rows) < min(20, other_limit):
                    log("intake PENDING tokens thin; aggregating all intake search_text")
                    intake_rows = fetch_tokens(
                        cur,
                        INTAKE_ALL_TOKENS_SQL,
                        hit_min=args.hit_min,
                        hit_max=args.hit_max,
                        limit=other_limit,
                    )
                in_band = sum(1 for _term, hits in intake_rows if args.hit_min <= hits <= args.hit_max)
                log(f"intake tokens={len(intake_rows)} in_band={in_band}")
                write_terms(
                    out_dir / "intake_search_terms.txt",
                    intake_rows,
                    f"intake search_text tokens hit_max={args.hit_max}",
                    rng,
                )

            if "cr" in sources:
                log("aggregating CR PENDING search_text tokens (one query)")
                cr_rows = fetch_tokens(
                    cur,
                    CR_PENDING_TOKENS_SQL,
                    hit_min=args.hit_min,
                    hit_max=args.hit_max,
                    limit=other_limit,
                )
                if len(cr_rows) < min(20, other_limit):
                    log("CR PENDING tokens thin; aggregating all CR payload search_text")
                    cr_rows = fetch_tokens(
                        cur,
                        CR_ALL_TOKENS_SQL,
                        hit_min=args.hit_min,
                        hit_max=args.hit_max,
                        limit=other_limit,
                    )
                in_band = sum(1 for _term, hits in cr_rows if args.hit_min <= hits <= args.hit_max)
                log(f"cr tokens={len(cr_rows)} in_band={in_band}")
                write_terms(
                    out_dir / "cr_search_terms.txt",
                    cr_rows,
                    f"change-request search_text tokens hit_max={args.hit_max}",
                    rng,
                )
    finally:
        conn.close()

    checked = []
    if "register" in sources:
        checked.append(("register_search_terms.txt", register_rows))
    if "intake" in sources:
        checked.append(("intake_search_terms.txt", intake_rows))
    if "cr" in sources:
        checked.append(("cr_search_terms.txt", cr_rows))
    missing = [name for name, rows in checked if not rows]
    if missing:
        log(f"WARNING empty files: {', '.join(missing)}")
        return 1
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
