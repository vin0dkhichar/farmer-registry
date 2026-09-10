#!/usr/bin/env python3
"""First-stage output (staff-api only): walk locust/api/results/staff-api/ and
emit ../documentation/staff-api/raw-report.md -- one markdown table per
Ingress > Volume-Tier > Pod-Scale > Step > (Scenario, Step 1 only), straight
from Locust's own *_stats.csv (Steps 1-2) / *_stats_history.csv (Step 3) / a
hand-filled CSV (Step 4, db-sweep -- not Locust-fired). No filtering to a
curated endpoint set, no SLO checks, no PASS/FAIL judgement -- every
endpoint Locust actually measured, verbatim. That interpretation step is
synthesize_report.py's job (-> the curated synthesize_templates/ CSVs) and
ultimately documentation/staff-api/final-report.md's.

Which columns appear in each table is driven by the header row of the
matching file under locust/api/templates/staff-api/raw_report_templates/
(isolated.csv / blended.csv / soak.csv / db-sweep.csv) -- edit those to
change what this script renders, no code change needed for that.

Only cells that actually have result files on disk produce a section --
nothing is fabricated for untested cells.

Usage:
    python create_raw_report.py
"""
import csv
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PERF_TESTING_DIR = SCRIPT_DIR.parent
RESULTS_ROOT = PERF_TESTING_DIR / "locust" / "api" / "results" / "staff-api"
RAW_TEMPLATES_DIR = PERF_TESTING_DIR / "locust" / "api" / "templates" / "staff-api" / "raw_report_templates"
OUT_PATH = PERF_TESTING_DIR / "documentation" / "staff-api" / "raw-report.md"

INGRESS_TITLES = {"in-cluster": "In-Cluster", "end-to-end": "End-to-End"}

# raw_report_templates/ column name -> the actual Locust CSV column it reads from.
# Columns with no entry here are read from the Locust row under their own name.
DISPLAY_TO_LOCUST = {
    "Endpoint": "Name",
    "Method": "Type",
    "Median Response Time (ms)": "Median Response Time",
    "Average Response Time (ms)": "Average Response Time",
    "Min Response Time (ms)": "Min Response Time",
    "Max Response Time (ms)": "Max Response Time",
    "p50": "50%", "p66": "66%", "p75": "75%", "p80": "80%",
    "p90": "90%", "p95": "95%", "p98": "98%", "p99": "99%",
    "p99.9": "99.9%", "p99.99": "99.99%", "p100": "100%",
}


def load_columns(template_name: str) -> list[str]:
    with (RAW_TEMPLATES_DIR / template_name).open(newline="") as f:
        return next(csv.reader(f))


def render_table(rows: list[dict], columns: list[str]) -> str:
    header = "| " + " | ".join(columns) + " |"
    sep = "|" + "---|" * len(columns)
    lines = [header, sep]
    for row in rows:
        cells = [row.get(DISPLAY_TO_LOCUST.get(c, c), "") for c in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_verbatim_csv(csv_path: Path) -> str:
    with csv_path.open(newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return ""
    header, *data = rows
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in data:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def find_stats_csv(run_dir: Path) -> Path | None:
    matches = list(run_dir.glob("*_stats.csv"))
    return matches[0] if matches else None


def find_history_csv(run_dir: Path) -> Path | None:
    matches = list(run_dir.glob("*_stats_history.csv"))
    return matches[0] if matches else None


def concurrency_note(run_dir: Path) -> str | None:
    # *_stats.csv (the per-endpoint table) is a single end-of-run aggregate --
    # no time dimension, so no concurrency column ever existed there. Locust's
    # *_stats_history.csv has "User Count" and "Requests/s" per timestamp;
    # pull min/max/final users and peak Aggregated RPS as one-line raw facts,
    # not the full time series.
    history_csv = find_history_csv(run_dir)
    if history_csv is None:
        return None
    with history_csv.open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("Name") == "Aggregated"]
    counts = [int(r["User Count"]) for r in rows if r.get("User Count", "").strip() != ""]
    rps_values = []
    for row in rows:
        raw = (row.get("Requests/s") or "").strip()
        if not raw:
            continue
        try:
            rps_values.append(float(raw))
        except ValueError:
            continue
    if not counts and not rps_values:
        return None
    # Locust keeps writing Aggregated rows after the shape returns None and
    # users are stopped, so the CSV tail is User Count 0. "final" is the last
    # in-run sample (users still > 0), not that shutdown tail.
    last_active = None
    for row in reversed(rows):
        raw_users = (row.get("User Count") or "").strip()
        if not raw_users:
            continue
        try:
            users = int(raw_users)
        except ValueError:
            continue
        if users > 0:
            last_active = row
            break
    final_users = int(last_active["User Count"]) if last_active else (counts[-1] if counts else None)
    final_rps = None
    if last_active and (last_active.get("Requests/s") or "").strip():
        try:
            final_rps = float(last_active["Requests/s"])
        except ValueError:
            pass
    if final_rps is None and rps_values:
        final_rps = rps_values[-1]
    bits = []
    if counts:
        bits.append(
            f"Concurrent users (from `{history_csv.name}`): "
            f"min {min(counts)}, max {max(counts)}, final {final_users}"
        )
    if rps_values:
        bits.append(
            f"Peak RPS (Aggregated): min {min(rps_values):.2f}, "
            f"max {max(rps_values):.2f}, final {final_rps:.2f}"
        )
    return "  \n".join(f"{bit}." for bit in bits)


def render_isolated_step(step_dir: Path) -> str | None:
    columns = load_columns("isolated.csv")
    scenario_dirs = sorted(p for p in step_dir.iterdir() if p.is_dir())
    blocks = []
    for scenario_dir in scenario_dirs:
        stats_csv = find_stats_csv(scenario_dir)
        if stats_csv is None:
            continue
        with stats_csv.open(newline="") as f:
            rows = list(csv.DictReader(f))
        header = f"**Scenario: `{scenario_dir.name}`**"
        note = concurrency_note(scenario_dir)
        if note:
            header += f"  \n{note}"
        blocks.append(header + "\n\n" + render_table(rows, columns))
    return "\n\n".join(blocks) if blocks else None


def render_blended_step(step_dir: Path) -> str | None:
    columns = load_columns("blended.csv")
    stats_csv = find_stats_csv(step_dir)
    if stats_csv is None:
        return None
    with stats_csv.open(newline="") as f:
        rows = list(csv.DictReader(f))
    table = render_table(rows, columns)
    note = concurrency_note(step_dir)
    return f"{note}\n\n{table}" if note else table


def render_soak_step(step_dir: Path) -> str | None:
    columns = load_columns("soak.csv")
    history_csv = find_history_csv(step_dir)
    if history_csv is None:
        return None
    with history_csv.open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("Name") == "Aggregated"]
    if not rows:
        return None
    return render_table(rows, columns)


def render_db_sweep_step(step_dir: Path) -> str | None:
    # Not Locust-fired -- pick up whatever hand-filled readings CSV(s) a human
    # dropped here (see raw_report_templates/db-sweep.csv for the schema),
    # and dump verbatim, one table per file.
    csv_files = sorted(step_dir.glob("*.csv"))
    blocks = []
    for csv_path in csv_files:
        table = render_verbatim_csv(csv_path)
        if table:
            blocks.append(f"**Source: `{csv_path.name}`**\n\n" + table)
    return "\n\n".join(blocks) if blocks else None


STEP_RENDERERS = {
    "isolated": render_isolated_step,
    "blended": render_blended_step,
    "soak": render_soak_step,
    "db-sweep": render_db_sweep_step,
}


def render_step(step_dir: Path) -> str | None:
    step_name = step_dir.name.split("-", 1)[-1]  # "1-isolated" -> "isolated"
    renderer = STEP_RENDERERS.get(step_name)
    if renderer is None:
        return None
    return renderer(step_dir)


def main():
    if not RESULTS_ROOT.is_dir():
        raise SystemExit(f"No results directory at {RESULTS_ROOT}")

    ingress_sections = []
    for ingress_dir in sorted(p for p in RESULTS_ROOT.iterdir() if p.is_dir()):
        tier_sections = []
        for tier_dir in sorted(p for p in ingress_dir.iterdir() if p.is_dir()):
            pod_sections = []
            for pod_dir in sorted(p for p in tier_dir.iterdir() if p.is_dir() and p.name.startswith("pod-")):
                step_sections = []
                for step_dir in sorted(p for p in pod_dir.iterdir() if p.is_dir()):
                    body = render_step(step_dir)
                    if body:
                        step_sections.append(f"##### Step: `{step_dir.name}`\n\n{body}")
                if step_sections:
                    pod_sections.append(f"#### Pod-Scale: `{pod_dir.name}`\n\n" + "\n\n".join(step_sections))
            if pod_sections:
                tier_sections.append(f"### Volume-Tier: `{tier_dir.name}`\n\n" + "\n\n".join(pod_sections))
        if tier_sections:
            title = INGRESS_TITLES.get(ingress_dir.name, ingress_dir.name)
            ingress_sections.append(f"## {title}\n\n" + "\n\n".join(tier_sections))

    if not ingress_sections:
        raise SystemExit(f"No result files found anywhere under {RESULTS_ROOT}")

    doc = [
        "# Raw Report",
        "",
        "Every measurement Locust actually recorded, verbatim -- no curation to a "
        "headline endpoint set, no SLO comparison, no PASS/FAIL. That interpretation "
        "lives in [`final-report.md`](final-report.md), built from this document.",
        "",
        "Auto-generated by `scripts/create_raw_report.py` from "
        "`locust/api/results/staff-api/` -- re-run it after any new run rather than "
        "editing this file by hand; it will be overwritten.",
        "",
        *ingress_sections,
    ]

    OUT_PATH.write_text("\n".join(doc) + "\n")
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
