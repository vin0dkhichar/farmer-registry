import json
import os
import sys

# Target API base URLs. For in-cluster runs use the ClusterIP service DNS, e.g.
#   http://<release>-staff-portal-api  /  http://<release>-partner-api
# For end-to-end runs use the public hostnames behind Istio/RP.
STAFF_API_BASE = os.environ.get("STAFF_API_BASE", "https://staff-farmer-registry.perftest.openg2p.org")
PARTNER_API_BASE = os.environ.get("PARTNER_API_BASE", "https://partner-farmer-registry.perftest.openg2p.org")

# Keycloak / OIDC
KEYCLOAK_BASE = os.environ.get("KEYCLOAK_BASE", "https://keycloak.perftest.openg2p.org")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "staff")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "farmer-registry-staff-portal")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
OIDC_USERNAME = os.environ.get("OIDC_USERNAME", "admin")
OIDC_PASSWORD = os.environ.get("OIDC_PASSWORD", "")

# /documents/upload_documents target bucket (DocumentBucket enum in
# registry-platform: default/templates/documents/data_import_files).
DOCUMENT_UPLOAD_BUCKET = os.environ.get("DOCUMENT_UPLOAD_BUCKET", "documents")

# Default resolves to performance-testing/seeding/seed_manifest.json regardless
# of the cwd Locust is launched from; override via env var if the generator
# wrote it somewhere else (e.g. run directly on the DB host).
_DEFAULT_SEED_MANIFEST = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "seeding", "seed_manifest.json")
)
SEED_MANIFEST = os.environ.get("SEED_MANIFEST", _DEFAULT_SEED_MANIFEST)

REGISTER_FARMER = "a1a4d25a-1cd4-4356-abac-985a0b3c6bcd"
REGISTER_HOUSEHOLD = "9055ab43-c85d-4833-bd00-ca657bb72644"

# farmer_ingestion_intake (g2p_intake_form_definitions.sql / g2p_intake_form_ui_tabs.sql)
FARMER_INTAKE_FORM_ID = "a1a4d25a-1cd4-4356-abac-8782382649"
FARMER_INTAKE_TAB_ID = "a1a4d25a-1cd4-4356-abac-72482721"

# ---------------------------------------------------------------------------
# INTAKE-CREATE (staff-api/intake_create/intake_create_locustfile.py)
# ---------------------------------------------------------------------------
# Loaded once from the bulk seed generator's manifest
# (performance-testing/seeding/); see seed_manifest.json /
# documentation/seeding-design.md.
# Left empty (with a warning) if the manifest isn't there yet, so read-only
# locustfiles that import this module but never touch these still work —
# flows that actually need them fail loudly with an empty-list error only if
# run before seeding has happened.
def _load_seed_manifest() -> dict:
    try:
        with open(SEED_MANIFEST) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[shared.config] could not load seed manifest at {SEED_MANIFEST!r}: {exc}", file=sys.stderr)
        return {}


def _manifest_list(manifest: dict, key: str) -> list[str]:
    values = manifest.get(key) or []
    if not values:
        print(f"[shared.config] seed manifest at {SEED_MANIFEST!r} has no {key}", file=sys.stderr)
    return values


_SEED_MANIFEST_DATA = _load_seed_manifest()

_DEFAULT_PERF_SEED_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "perf-seed")
)
PERF_SEED_DIR = os.environ.get("PERF_SEED_DIR", _DEFAULT_PERF_SEED_DIR)


PERF_SEED_HIT_MAX = int(os.environ.get("PERF_SEED_HIT_MAX", "2000"))


def _load_perf_seed_file(filename: str) -> tuple[list[str], dict[str, int]]:
    path = os.path.join(PERF_SEED_DIR, filename)
    if not os.path.isfile(path):
        return [], {}
    values: list[str] = []
    hits: dict[str, int] = {}
    try:
        with open(path) as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                if line.lstrip().startswith("#"):
                    body = line.lstrip("#").strip()
                    if "\t" in body:
                        term, _, rest = body.partition("\t")
                        if rest.strip().isdigit():
                            hits[term.strip()] = int(rest.strip())
                    continue
                values.append(line)
    except OSError as exc:
        print(f"[shared.config] could not load perf-seed file at {path!r}: {exc}", file=sys.stderr)
        return [], {}
    if not values:
        print(f"[shared.config] perf-seed file at {path!r} is empty", file=sys.stderr)
        return [], hits
    print(f"[shared.config] loaded {len(values)} values from {path}", file=sys.stderr)
    return values, hits


def _load_perf_seed_lines(filename: str) -> list[str]:
    values, _hits = _load_perf_seed_file(filename)
    return values


# internal_record_ids of seeded Household register records — the
# farmer_household_lookup_section_01 section links a farmer intake submission
# to one of these. Prefer openg2p/perf-seed/household_ids.txt when present.
HOUSEHOLD_IDS = _load_perf_seed_lines("household_ids.txt") or _manifest_list(
    _SEED_MANIFEST_DATA, "household_ids"
)

# Exported from perftest via scripts/export_perf_seed.py. Create flows skip
# terms whose comment hit-count is already at PERF_SEED_HIT_MAX (2000).
SEARCH_TERMS, SEARCH_TERM_HITS = _load_perf_seed_file("register_search_terms.txt")
if not SEARCH_TERMS:
    SEARCH_TERMS = _manifest_list(_SEED_MANIFEST_DATA, "search_terms")
    SEARCH_TERM_HITS = {}
INTAKE_SEARCH_TERMS, INTAKE_SEARCH_TERM_HITS = _load_perf_seed_file("intake_search_terms.txt")
if not INTAKE_SEARCH_TERMS:
    INTAKE_SEARCH_TERMS = list(SEARCH_TERMS)
    INTAKE_SEARCH_TERM_HITS = dict(SEARCH_TERM_HITS)
CR_SEARCH_TERMS, CR_SEARCH_TERM_HITS = _load_perf_seed_file("cr_search_terms.txt")
if not CR_SEARCH_TERMS:
    CR_SEARCH_TERMS = list(SEARCH_TERMS)
    CR_SEARCH_TERM_HITS = dict(SEARCH_TERM_HITS)

# Register browsing flow (staff-api/register_read/register_read_locustfile.py)
SEARCH_PAGE_SIZE = int(os.environ.get("SEARCH_PAGE_SIZE", "10"))
MAX_SEARCH_PAGE = int(os.environ.get("MAX_SEARCH_PAGE", "20"))
TAB_ITERATION_MIN_WAIT_SECONDS = float(os.environ.get("TAB_ITERATION_MIN_WAIT_SECONDS", "0.0"))
TAB_ITERATION_MAX_WAIT_SECONDS = float(os.environ.get("TAB_ITERATION_MAX_WAIT_SECONDS", "0.0"))

# Intake read-and-approve flow (staff-api/intake_read_and_approve/intake_read_and_approve_locustfile.py)
INTAKE_SEARCH_PAGE_SIZE = int(os.environ.get("INTAKE_SEARCH_PAGE_SIZE", "20"))
# Fraction of intake_create submissions that embed a pool search_term (findable
# by approve searches), and fraction of intake_read_and_approve tasks that
# intentionally search for a hit. The remaining ~20% create with a unique
# miss-token / search with a miss-token so empty-result path is exercised.
INTAKE_SEARCH_HIT_RATE = float(os.environ.get("INTAKE_SEARCH_HIT_RATE", "0.8"))

# CR read-and-approve flow (staff-api/cr_read_and_approve/cr_read_and_approve_locustfile.py)
CR_SEARCH_PAGE_SIZE = int(os.environ.get("CR_SEARCH_PAGE_SIZE", "20"))

# ---------------------------------------------------------------------------
# CR-CREATE (staff-api/cr_create/cr_create_locustfile.py)
# ---------------------------------------------------------------------------
# One known-editable field per Farmer-register section (from
# g2p_register_sections.sql's section_ui_schema / the domain models in
# farmer-extension/register_domain/models), chosen ahead of time rather than
# parsed live, so the CR always targets a field guaranteed to exist and
# accept a plain value. section_id -> field_name.
#
# The three sections whose section_register_id belongs to a *different*
# register's own domain (household_information, household cross-linked
# location, household_member) are intentionally left unmapped — their
# fields live on the Household/HouseholdMember models, not verified here.
# Tabs that only offer unmapped sections are skipped.
CR_FIELD_BY_SECTION = {
    "01425f4e-720e-4a4e-a0db-73f371ae2a07": "functional_record_id",  # fr_farmer_header (CORE section)
    "farmer_farmer_personal_identification_section_01": "middle_name",
    "farmer_farmer_socio_economic_and_health_section_04": "source_of_income_other",
    "farmer_farmer_location_section_03": "address_line_1",
    "farmer_farm_farm_details_section_01": "address_line_1",
    "farmer_crop_crop_details_section_01": "season",
    "farmer_farm_input_farm_input_details_section_01": "access_to_finance",
    "farmer_membership_membership_details_01": "primary_cooperative_name",
    "farmer_livestock_livestock_details_section_01": "breed",  # API-sourced enum (LIVESTOCK_BREED)
    "farmer_household_lookup_section_01": "link_internal_record_id",
}
