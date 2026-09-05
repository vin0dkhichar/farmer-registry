#!/usr/bin/env python3
"""Generate a large, realistic Farmer Registry sample and bulk-load it.

Why this lives in farmer-registry
---------------------------------
It writes farmer's own extension tables and draws every enum-backed value from
farmer's LandOwnershipTypeEnum, CurrentLandUseEnum, FarmingTypeEnum,
LandSizeUnitEnum, CropEndUseEnum, LivestockSystemEnum, SourceOfIncomeEnum and
FarmerClusterRoleEnum. It cannot seed any other registry, and it has to move in
lockstep with those enums. NSR's equivalent is a different script for the same
reason.

Why this exists alongside the inherited load_sample_data.py
-----------------------------------------------------------
The registry-platform db-seed image ships a farmer-shaped `load_sample_data.py`
that ingests the hand-enumerated ~500-row demo set from `seed-data/*.json` — every
row, including its ids, written out by hand. That is the right shape for a
smoke-test fixture but cannot scale, and the dashboards need volume before any
distribution is legible. This generates at arbitrary scale and loads with COPY.

Two things it deliberately does NOT do
--------------------------------------
1. It does not invent a geography. Places are read from the deployment's own
   Master Data hierarchy, at whatever depth that holds — 4 levels here, 5
   elsewhere — so the generated records join to the same geo ids every other
   service uses. A deployment with no country pack gets no sample rather than a
   fabricated country.
2. It does not re-seed. A fixed --seed regenerates the SAME record ids, and COPY
   has no ON CONFLICT to absorb them, so a second run on a seeded database would
   die on row one. Seeded means done; --purge is the deliberate way to redo it.

Shape it generates
------------------
    farmer ──< land ──< crop / livestock / farm_inputs
           └──< membership_details, score

which is the farmer schema: crops, livestock and inputs belong to the PARCEL,
not to the farmer.
"""

import argparse
import json
import os
import random
import sys
import uuid
from datetime import date, datetime, timedelta
from io import StringIO

import psycopg2

# created_by stamped on every generated farmer. It is what tells this
# generator's rows apart from the demo fixture's in the same tables — the
# seeded-means-done guard and --purge both key off it.
SEEDER = "bulk-sample"

# Rows per COPY chunk. Large enough to amortise round-trips, small enough that a
# failure does not roll back an hour of work.
CHUNK = 50_000

# --- farmer's enums, mirrored ------------------------------------------------
# Weighted so a chart has a shape rather than a flat bar. Values MUST match
# register_domain/models/enums.py; test drift shows up as blank chart slices.
TENURE = [("OWNER", 0.62), ("TENANT", 0.26), ("CROP_SHARE", 0.12)]
LAND_USE = [("AGRICULTURAL", 0.78), ("GRAZING", 0.14), ("FOREST", 0.05), ("RESIDENTIAL", 0.03)]
FARMING_TYPE = [("CROP", 0.48), ("MIXED", 0.32), ("LIVESTOCK", 0.14), ("AGROFORESTRY", 0.04), ("AQUACULTURE", 0.02)]
SIZE_UNIT = [("HECTARE", 0.55), ("ACRE", 0.35), ("SQUARE_METER", 0.10)]
CROP_END_USE = [("FOOD_HUMAN_CONSUMPTION", 0.72), ("FEED_ANIMALS", 0.18),
                ("BIOFUELS_NONFOOD", 0.05), ("OTHER", 0.05)]
LIVESTOCK_SYSTEM = [("SEDENTARY_PASTORAL", 0.44), ("MIXED", 0.28), ("SEMI_NOMADIC", 0.14),
                    ("NOMADIC_PASTORAL", 0.10), ("INDUSTRIAL", 0.04)]
INCOME = [("SOI_CROP_PRODUCTION", 0.55), ("SOI_LIVESTOCK_PRODUCTION", 0.27),
          ("SOI_GOVERNMENT_NGO_SUPPORT", 0.10), ("SOI_OTHERS", 0.08)]
CLUSTER_ROLE = [("MEMBER", 0.80), ("LEAD", 0.07), ("DEPUTY", 0.06),
                ("SECRETARY", 0.04), ("ACCOUNTANT", 0.03)]
EDUCATION = [("NONE", 0.28), ("PRIMARY", 0.36), ("SECONDARY", 0.24),
             ("TERTIARY", 0.09), ("VOCATIONAL", 0.03)]
MARITAL = [("MARRIED", 0.63), ("SINGLE", 0.18), ("WIDOWED", 0.12), ("DIVORCED", 0.07)]
GENDER = [("MALE", 0.53), ("FEMALE", 0.47)]
DISABILITY_TYPE = [("PHYSICAL", 0.42), ("VISUAL", 0.22), ("HEARING", 0.18),
                   ("INTELLECTUAL", 0.10), ("OTHER", 0.08)]
DISABILITY_SEV = [("MILD", 0.55), ("MODERATE", 0.31), ("SEVERE", 0.14)]

COMMODITIES = [("Maize", 0.22), ("Teff", 0.16), ("Wheat", 0.13), ("Sorghum", 0.10),
               ("Barley", 0.08), ("Coffee", 0.08), ("Haricot Bean", 0.07),
               ("Sesame", 0.05), ("Chickpea", 0.05), ("Millet", 0.03),
               ("Vegetables", 0.03)]
LIVESTOCK_TYPE = [("Cattle", 0.34), ("Goat", 0.24), ("Sheep", 0.20),
                  ("Poultry", 0.14), ("Donkey", 0.05), ("Camel", 0.03)]
WATER_SOURCE = [("Rainfed", 0.66), ("River", 0.14), ("Borehole", 0.10),
                ("Irrigation Canal", 0.07), ("Pond", 0.03)]
SEASON = [("Meher", 0.62), ("Belg", 0.30), ("Irrigated", 0.08)]
SOIL = [("high", 0.24), ("medium", 0.51), ("low", 0.25)]

FIRST_M = ["Abebe", "Bekele", "Chala", "Dawit", "Eyob", "Fikru", "Getachew", "Hailu",
           "Kebede", "Lemma", "Mulugeta", "Negash", "Tadesse", "Worku", "Yohannes"]
FIRST_F = ["Almaz", "Birtukan", "Chaltu", "Desta", "Eleni", "Frehiwot", "Genet",
           "Hirut", "Kidist", "Lensa", "Meseret", "Rahel", "Selam", "Tigist", "Zewditu"]
LAST = ["Abera", "Bekele", "Desalegn", "Fikadu", "Girma", "Haile", "Kassa", "Mekonnen",
        "Negussie", "Regassa", "Shiferaw", "Tesfaye", "Wolde", "Yimer", "Zeleke"]


def weighted(rng, table):
    """Pick from [(value, weight), ...]. Kept explicit rather than random.choices
    so a single rng drives every draw and --seed is genuinely reproducible."""
    r = rng.random()
    acc = 0.0
    for value, w in table:
        acc += w
        if r <= acc:
            return value
    return table[-1][0]


def log(msg):
    print(f"[bulk-sample] {msg}", flush=True)


def die(msg):
    print(f"[bulk-sample] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


# ---------------------------------------------------------------- geo from MDS
def load_geo(mds_conn, expect_country):
    """Return (levels, leaves).

    levels  — [(level_id, mnemonic), ...] root-first, at this deployment's depth.
    leaves  — [[(mnemonic, value_mnemonic, value_id), ...], ...] one full chain
              per deepest-level place.

    Read, never invented: the chain is exactly what Master Data holds, so the
    generated geo_code_hierarchy_json joins to the same ids the rest of the
    platform uses.
    """
    with mds_conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.g2p_geo_levels')")
        if cur.fetchone()[0] is None:
            return [], []
        cur.execute("SELECT level_id, level_mnemonic, parent_level_id FROM g2p_geo_levels")
        rows = cur.fetchall()
        if not rows:
            return [], []

        by_parent = {}
        for lid, mnem, parent in rows:
            by_parent.setdefault(parent, []).append((lid, mnem))
        chain, cursor_parent = [], None
        while by_parent.get(cursor_parent):
            lid, mnem = sorted(by_parent[cursor_parent])[0]
            chain.append((lid, mnem))
            cursor_parent = lid
        if not chain:
            return [], []

        cur.execute(
            "SELECT level_value_id, level_id, level_value_mnemonic, parent_level_value_id "
            "FROM g2p_geo_level_values"
        )
        vals = cur.fetchall()

    if expect_country:
        roots = [v for v in vals if v[1] == chain[0][0]]
        got = {(v[2] or "").upper() for v in roots} | {(v[0] or "").upper() for v in roots}
        if expect_country.upper() not in got:
            die(f"Master Data holds {sorted(got) or '(nothing)'} at the root level, "
                f"not the expected {expect_country!r}. This is a guard, not a "
                f"selector — fix the country pack or drop --expect-country.")

    node = {v[0]: v for v in vals}
    level_mnem = dict(chain)
    deepest = chain[-1][0]
    leaves = []
    for v in vals:
        if v[1] != deepest:
            continue
        path, cur_node = [], v
        while cur_node is not None:
            path.append((level_mnem.get(cur_node[1], cur_node[1]), cur_node[2], cur_node[0]))
            cur_node = node.get(cur_node[3])
        leaves.append(list(reversed(path)))
    return chain, leaves


# ------------------------------------------------------------------ COPY loader
class Copier:
    """Buffered COPY writer. One per table; flush() streams a chunk."""

    def __init__(self, conn, table, cols):
        self.conn, self.table, self.cols = conn, table, cols
        self.buf, self.n = StringIO(), 0
        self.total = 0

    def add(self, row):
        out = []
        for v in row:
            if v is None:
                out.append("\\N")
            elif isinstance(v, bool):
                out.append("t" if v else "f")
            else:
                s = str(v)
                out.append(s.replace("\\", "\\\\").replace("\t", "\\t")
                            .replace("\n", "\\n").replace("\r", "\\r"))
        self.buf.write("\t".join(out) + "\n")
        self.n += 1
        if self.n >= CHUNK:
            self.flush()

    def flush(self):
        if not self.n:
            return
        self.buf.seek(0)
        cols = ", ".join(f'"{c}"' for c in self.cols)
        with self.conn.cursor() as cur:
            cur.copy_expert(f'COPY "public"."{self.table}" ({cols}) FROM STDIN', self.buf)
        self.total += self.n
        self.buf, self.n = StringIO(), 0


def rid(rng):
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def main():
    p = argparse.ArgumentParser(description="Generate and load a bulk Farmer Registry sample.")
    p.add_argument("--db", default=os.environ.get("FR_DB", "farmer_registry"),
                   help="registry database (default: $FR_DB)")
    p.add_argument("--geo-db", default=os.environ.get("MDS_DB", "master_data"),
                   help="Master Data database to read geography from (default: $MDS_DB)")
    p.add_argument("--farmers", type=int, default=100_000)
    p.add_argument("--seed", type=int, default=20260401,
                   help="fixed so a rerun reproduces the same ids — see --purge")
    p.add_argument("--score-type", default="VULNERABILITY")
    p.add_argument("--register-id", default=None)
    p.add_argument("--expect-country", default=None,
                   help="guard: abort if MDS holds a different country")
    p.add_argument("--purge", action="store_true",
                   help="delete previously generated rows first, then regenerate")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    dsn = dict(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", ""),
    )
    conn = psycopg2.connect(dbname=args.db, **dsn)
    conn.autocommit = False
    mds = psycopg2.connect(
        dbname=args.geo_db,
        host=os.environ.get("MDS_PGHOST") or dsn["host"],
        port=os.environ.get("MDS_PGPORT") or dsn["port"],
        user=os.environ.get("MDS_PGUSER") or dsn["user"],
        password=os.environ.get("MDS_PGPASSWORD") or dsn["password"],
    )

    # --- guards ---------------------------------------------------------------
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.g2p_register_farmers')")
        if cur.fetchone()[0] is None:
            # On a fresh install this hook can run before the registry has created
            # its schema. An absent table means "not seeded", not a failure.
            log("g2p_register_farmers does not exist yet — nothing to seed.")
            return
        # Count only what THIS generator wrote. The demo fixture
        # (dbSeed.loadSampleData) writes the same tables under its own created_by,
        # and both are normally on — counting every farmer would let those ~21
        # fixture rows block the bulk load forever.
        cur.execute('SELECT count(*) FROM g2p_register_farmers WHERE created_by = %s',
                    (SEEDER,))
        existing = cur.fetchone()[0]

    if existing and args.purge and not args.dry_run:
        log(f"--purge: removing {existing} bulk-generated farmers and their children")
        with conn.cursor() as cur:
            # Scoped to this generator's rows, by walking down from its farmers —
            # a blanket DELETE would take the demo fixture with it. Children first.
            bulk_farmers = ('SELECT internal_record_id FROM g2p_register_farmers '
                            'WHERE created_by = %s')
            bulk_lands = (f'SELECT internal_record_id FROM g2p_register_lands '
                          f'WHERE link_internal_record_id IN ({bulk_farmers})')
            for live, hist in (
                ("g2p_register_crops", "g2p_register_history_crops"),
                ("g2p_register_livestocks", "g2p_register_history_livestocks"),
                ("g2p_register_farm_inputs", "g2p_register_history_farm_inputs"),
            ):
                cur.execute(
                    f'DELETE FROM {hist} WHERE internal_record_id IN '
                    f'(SELECT internal_record_id FROM {live} '
                    f'WHERE link_internal_record_id IN ({bulk_lands}))',
                    (SEEDER,),
                )
            for t in ("g2p_register_crops", "g2p_register_livestocks",
                      "g2p_register_farm_inputs"):
                cur.execute(f'DELETE FROM {t} WHERE link_internal_record_id IN ({bulk_lands})',
                            (SEEDER,))
            for live, hist in (
                ("g2p_register_lands", "g2p_register_history_lands"),
                ("g2p_register_membership_details", "g2p_register_history_membership_details"),
            ):
                cur.execute(
                    f'DELETE FROM {hist} WHERE internal_record_id IN '
                    f'(SELECT internal_record_id FROM {live} '
                    f'WHERE link_internal_record_id IN ({bulk_farmers}))',
                    (SEEDER,),
                )
            for t in ("g2p_register_lands", "g2p_register_membership_details",
                      "g2p_register_scores"):
                cur.execute(f'DELETE FROM {t} WHERE link_internal_record_id IN ({bulk_farmers})',
                            (SEEDER,))
            cur.execute(
                'DELETE FROM g2p_register_history_farmers WHERE internal_record_id IN '
                f'({bulk_farmers})',
                (SEEDER,),
            )
            cur.execute('DELETE FROM g2p_register_farmers WHERE created_by = %s', (SEEDER,))
        conn.commit()
        existing = 0
    elif existing:
        # Seeded means done. A rerun would regenerate identical ids and COPY has no
        # ON CONFLICT, so it would die on row one and fail the whole upgrade.
        log(f"already seeded ({existing:,} bulk farmers) — nothing to do. "
            "Use --purge to regenerate.")
        return

    # g2p_register_scores.register_id is NOT NULL. Look the Farmer register up by
    # mnemonic rather than hardcoding a uuid — the ids are per-deployment (seeded
    # by g2p_register_definitions.sql) and a wrong one would attach every score to
    # a register that does not exist.
    register_id = args.register_id
    if not register_id:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.g2p_register_definitions')")
            if cur.fetchone()[0] is not None:
                cur.execute("SELECT register_id FROM g2p_register_definitions "
                            "WHERE register_mnemonic = %s", ("Farmer",))
                row = cur.fetchone()
                register_id = row[0] if row else None
    if not register_id:
        log("no Farmer register in g2p_register_definitions — scores will be skipped. "
            "Pass --register-id to force one.")

    # One score definition for the whole run: a definition is a shared entity, so
    # a fresh uuid per row would imply thousands of distinct scoring models.
    levels, leaves = load_geo(mds, args.expect_country)
    if not leaves:
        log("Master Data holds no geography — skipping. Load a country pack "
            "(geoSeed.countryPack) and rerun; a sample with an invented country "
            "would join to nothing.")
        return
    log(f"geo: {len(levels)} levels ({', '.join(m for _, m in levels)}), {len(leaves)} places")

    if args.dry_run:
        log(f"dry run: would generate {args.farmers} farmers into {args.db}")
        return

    rng = random.Random(args.seed)
    today = date.today()
    score_def_id = rid(rng)

    farmers = Copier(conn, "g2p_register_farmers", [
        "internal_record_id", "functional_record_id", "record_name", "record_status",
        "created_at", "created_by", "last_approved_at", "last_approved_by",
        "registration_date", "search_text",
        "first_name", "last_name", "gender", "birth_date", "marital_status",
        "occupation", "education_level", "estimated_age", "has_personal_phone",
        "disabled", "disability_type", "disability_severity", "source_of_income",
        "language_spoken", "latitude", "longitude", "country_code",
        "geo_lowest_level_value_id", "geo_code_hierarchy_json"])
    lands = Copier(conn, "g2p_register_lands", [
        "internal_record_id", "link_internal_record_id", "functional_record_id",
        "record_status", "created_at", "created_by", "last_approved_at",
        "last_approved_by", "land_ownership_type", "land_size", "unit",
        "soil_fertility", "current_land_use", "farming_type", "year_of_acquisition",
        "means_of_acquisition", "certificate_storage_id",
        "geo_lowest_level_value_id", "geo_code_hierarchy_json"])
    crops = Copier(conn, "g2p_register_crops", [
        "internal_record_id", "link_internal_record_id", "functional_record_id",
        "record_status", "created_at", "created_by", "last_approved_at",
        "last_approved_by", "commodity", "planted_date", "season", "end_use"])
    stock = Copier(conn, "g2p_register_livestocks", [
        "internal_record_id", "link_internal_record_id", "functional_record_id",
        "record_status", "created_at", "created_by", "last_approved_at",
        "last_approved_by", "livestock_type", "breed", "head_count",
        "livestock_system"])
    inputs = Copier(conn, "g2p_register_farm_inputs", [
        "internal_record_id", "link_internal_record_id", "functional_record_id",
        "record_status", "created_at", "created_by", "last_approved_at",
        "last_approved_by", "fertilizer_use", "pesticide_use",
        "insecticide_use", "improved_seed_use", "water_source",
        "access_to_machinery", "access_to_finance"])
    member = Copier(conn, "g2p_register_membership_details", [
        "internal_record_id", "link_internal_record_id", "functional_record_id",
        "record_status", "created_at", "created_by", "last_approved_at",
        "last_approved_by", "is_primary_cooperative_member",
        "primary_cooperative_name", "is_cooperative_union_member",
        "cooperative_union_name", "is_farmer_cluster_member", "farmer_cluster_role"])
    scores = Copier(conn, "g2p_register_scores", [
        "internal_record_id", "link_internal_record_id", "register_id",
        "score_definition_id", "triggered_by_cr_id",
        "score_type", "computed_score", "computed_at"])

    log(f"generating {args.farmers} farmers…")
    _seq = {'LD': 0, 'CR': 0, 'LS': 0, 'FI': 0, 'MB': 0}
    def _fid(pfx):
        _seq[pfx] += 1
        return f"{pfx}-{_seq[pfx]:09d}"
    for i in range(args.farmers):
        fid = rid(rng)
        chain = leaves[rng.randrange(len(leaves))]
        hierarchy = json.dumps({"hierarchy": [
            {"level_mnemonic": m, "level_value_mnemonic": vm, "level_value_id": vid}
            for m, vm, vid in chain]})
        leaf_id = chain[-1][2]
        sex = weighted(rng, GENDER)
        first = rng.choice(FIRST_F if sex == "FEMALE" else FIRST_M)
        last = rng.choice(LAST)
        age = rng.randint(19, 82)
        born = today - timedelta(days=age * 365 + rng.randrange(365))
        disabled = rng.random() < 0.07
        created = datetime(today.year - 1, 1, 1) + timedelta(minutes=rng.randrange(500_000))
        # ~4% of farmers have no recorded birth date; the age band then falls
        # back to estimated_age.
        has_dob = rng.random() > 0.04

        farmers.add([
            fid, f"FR-{i + 1:08d}", f"{first} {last}", "ACTIVE",
            created.isoformat(sep=" "), SEEDER,
            created.isoformat(sep=" "), SEEDER,
            (created.date()).isoformat(),
            f"{first} {last}".lower(),
            first, last, sex, born.isoformat() if has_dob else None,
            weighted(rng, MARITAL), "Farmer", weighted(rng, EDUCATION),
            None if has_dob else age,
            rng.random() < 0.58, disabled,
            weighted(rng, DISABILITY_TYPE) if disabled else None,
            weighted(rng, DISABILITY_SEV) if disabled else None,
            weighted(rng, INCOME), rng.choice(["am", "om", "ti", "so"]),
            f"{8.0 + rng.random() * 6:.5f}", f"{35.0 + rng.random() * 8:.5f}",
            "ET", leaf_id, hierarchy,
        ])

        # Sub-table functional ids are SEQUENTIAL, not a truncated uuid.
        # The old `f"CR-{cid[:8]}"` kept only 8 hex chars: ~4.3e9 values, so by the
        # birthday bound a run of this size collides long before it finishes —
        # 100k farmers died at ~39k crop rows on
        # ix_g2p_register_crops_functional_record_id. A counter cannot collide.
        # A farmer with no land at all is real (pastoralists, landless labour) and
        # the coverage panel is supposed to show it.
        for _ in range(weighted(rng, [(1, 0.55), (2, 0.28), (3, 0.11), (0, 0.06)])):
            lid = rid(rng)
            unit = weighted(rng, SIZE_UNIT)
            size = {"HECTARE": lambda: round(rng.uniform(0.15, 9.0), 2),
                    "ACRE": lambda: round(rng.uniform(0.4, 22.0), 2),
                    "SQUARE_METER": lambda: rng.randrange(500, 40_000)}[unit]()
            ftype = weighted(rng, FARMING_TYPE)
            lands.add([
                lid, fid, _fid("LD"), "ACTIVE", created.isoformat(sep=" "), SEEDER, created.isoformat(sep=" "), SEEDER,
                weighted(rng, TENURE), size, unit, weighted(rng, SOIL),
                weighted(rng, TENURE), str(size), unit, weighted(rng, SOIL),
                weighted(rng, LAND_USE), ftype, rng.randrange(1985, today.year),
                rng.choice(["inherited", "purchased", "allocated", "rented"]),
                f"CERT-{_seq['LD']:09d}" if rng.random() < 0.41 else None,
                leaf_id, hierarchy,
            ])

            if ftype in ("CROP", "MIXED", "AGROFORESTRY"):
                for _ in range(rng.randint(1, 3)):
                    cid = rid(rng)
                    planted = today - timedelta(days=rng.randrange(400))
                    crops.add([cid, lid, _fid("CR"), "ACTIVE",
                               created.isoformat(sep=" "), SEEDER, created.isoformat(sep=" "), SEEDER, weighted(rng, COMMODITIES),
                               planted.isoformat(), weighted(rng, SEASON),
                               weighted(rng, CROP_END_USE)])
            if ftype in ("LIVESTOCK", "MIXED"):
                for _ in range(rng.randint(1, 3)):
                    sid = rid(rng)
                    stock.add([sid, lid, _fid("LS"), "ACTIVE",
                               created.isoformat(sep=" "), SEEDER, created.isoformat(sep=" "), SEEDER, weighted(rng, LIVESTOCK_TYPE),
                               rng.choice(["Local", "Crossbreed", "Improved"]),
                               rng.randint(1, 60), weighted(rng, LIVESTOCK_SYSTEM)])
            if rng.random() < 0.72:
                iid = rid(rng)
                inputs.add([iid, lid, _fid("FI"), "ACTIVE",
                            created.isoformat(sep=" "), SEEDER, created.isoformat(sep=" "), SEEDER,
                            rng.random() < 0.46, rng.random() < 0.31,
                            rng.random() < 0.22, rng.random() < 0.38,
                            weighted(rng, WATER_SOURCE),
                            rng.random() < 0.17, rng.random() < 0.24])

        if rng.random() < 0.34:
            mid = rid(rng)
            in_cluster = rng.random() < 0.55
            member.add([mid, fid, _fid("MB"), "ACTIVE", created.isoformat(sep=" "), SEEDER, created.isoformat(sep=" "), SEEDER,
                        rng.random() < 0.62, "Woreda Farmers Cooperative",
                        rng.random() < 0.21, "Regional Cooperative Union",
                        in_cluster, weighted(rng, CLUSTER_ROLE) if in_cluster else None])
        if register_id and rng.random() < 0.28:
            sid = rid(rng)
            scores.add([sid, fid, register_id, score_def_id, rid(rng), args.score_type,
                        round(rng.uniform(0, 100), 2), created.isoformat(sep=" ")])

        if (i + 1) % 25_000 == 0:
            log(f"  {i + 1:,}/{args.farmers:,} farmers")

    for c in (farmers, lands, crops, stock, inputs, member, scores):
        c.flush()
    conn.commit()

    log(f"loaded: {farmers.total:,} farmers, {lands.total:,} parcels, "
        f"{crops.total:,} crops, {stock.total:,} livestock, {inputs.total:,} input "
        f"records, {member.total:,} memberships, {scores.total:,} scores")
    log("done.")


if __name__ == "__main__":
    main()
