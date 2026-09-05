#!/usr/bin/env python3
"""Seed Farmer Registry sample records through the intake-form API.

Households are submitted and approved first. Farmers are then submitted with
the live household id, land is saved before crop / livestock / farm-inputs
(those rows parent to land), then each intake is finalized and approved by
alex.carter (stage 1) and nina.patel (stage 2). Celery ingest writes the
register rows — this script never INSERTs into g2p_register_*.
"""

from __future__ import annotations

import csv
import json
import os
import ssl
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

import psycopg2
import psycopg2.extras

# ── Register / form / section ids (farmer-extension meta_data) ───────────────
HOUSEHOLD_REGISTER_ID = "9055ab43-c85d-4833-bd00-ca657bb72644"
HOUSEHOLD_FORM_ID = "9055ab43-c85d-4833-bd00-ca657bb72650"
FARMER_REGISTER_ID = "a1a4d25a-1cd4-4356-abac-985a0b3c6bcd"
FARMER_FORM_ID = "a1a4d25a-1cd4-4356-abac-8782382649"
LAND_REGISTER_ID = "493153d5-07ef-4743-8efd-07f4099772b9"
CROP_REGISTER_ID = "5fa096f8-ffdc-4b0a-ab16-9ca386c23310"
LIVESTOCK_REGISTER_ID = "4bcb88a3-fc5e-44d2-abc6-e2c68670c5bb"
FARM_INPUTS_REGISTER_ID = "18df8370-3e9a-493f-aa27-fc1b9e05629c"
MEMBERSHIP_REGISTER_ID = "495f251c-83a5-4025-a307-1925712c9d0b"
HH_MEMBER_REGISTER_ID = "52979fdd-220c-48dd-8de0-0a434e786427"

HH_INFO_SECTION = "household_household_household_information_section_01"
HH_LOCATION_SECTION = "household_household_location_section_03"
HH_MEMBER_SECTION = "household_household_household_member_section_02"

FARMER_LOOKUP_SECTION = "farmer_household_lookup_section_01"
FARMER_PERSONAL_SECTION = "farmer_farmer_personal_identification_section_01"
FARMER_SOCIO_SECTION = "farmer_farmer_socio_economic_and_health_section_04"
FARMER_LOCATION_SECTION = "farmer_farmer_location_section_03"
FARMER_LAND_SECTION = "farmer_farm_farm_details_section_01"
FARMER_CROP_SECTION = "a7d69d0c-ed5b-4d78-b2b5-90dfe40c8aa2"
FARMER_INPUT_SECTION = "43c0b48b-3af1-41a4-8399-48e7ab718e80"
FARMER_LIVESTOCK_SECTION = "2b73b4c3-b3f0-48cc-bba7-2b522b62e785"
FARMER_MEMBERSHIP_SECTION = "farmer_membership_membership_details_01"

ARTIFACT_INTAKE = "registry.intake_form"

EDU_MAP = {
    "NONE": "ILLITERATE",
    "VOCATIONAL": "CAN_READ_AND_WRITE",
    "ILLITERATE": "ILLITERATE",
    "CAN_READ_AND_WRITE": "CAN_READ_AND_WRITE",
    "NON_FORMAL": "NON_FORMAL",
    "NEVER_ATTEND": "NEVER_ATTEND",
    "BASIC": "BASIC",
    "PRIMARY": "PRIMARY",
    "INTERMEDIARY": "INTERMEDIARY",
    "SECONDARY": "SECONDARY",
    "TERTIARY": "TERTIARY",
    "HIGHER_EDUCATION": "HIGHER_EDUCATION",
}
INCOME_MAP = {
    "CROP_PRODUCTION": "SOI_CROP_PRODUCTION",
    "SOI_CROP_PRODUCTION": "SOI_CROP_PRODUCTION",
    "LIVESTOCK_PRODUCTION": "SOI_LIVESTOCK_PRODUCTION",
    "SOI_LIVESTOCK_PRODUCTION": "SOI_LIVESTOCK_PRODUCTION",
    "LIVESTOCK": "SOI_LIVESTOCK_PRODUCTION",
    "GOVERNMENT_NGO_SUPPORT": "SOI_GOVERNMENT_NGO_SUPPORT",
    "SOI_GOVERNMENT_NGO_SUPPORT": "SOI_GOVERNMENT_NGO_SUPPORT",
    "OTHERS": "SOI_OTHERS",
    "SOI_OTHERS": "SOI_OTHERS",
    "REMITTANCES": "SOI_OTHERS",
    "WAGE_LABOR": "SOI_OTHERS",
    "BUSINESS_TRADE": "SOI_OTHERS",
}
LANG_MAP = {
    "ENGLISH": "ENGLISH",
    "HINDI": "HINDI",
    "SPANISH": "SPANISH",
    "FRENCH": "FRENCH",
    "LOCAL": "ENGLISH",
}

OPENG2P_DATA_DIR = Path(os.environ.get("OPENG2P_DATA_DIR", "/openg2p-data"))
DEMO_DIR = OPENG2P_DATA_DIR / "demography"
JSON_COLUMNS_INDIVIDUAL = {"phone_numbers"}


def log(msg: str) -> None:
    print(f"[load-sample-data] {msg}", flush=True)


def env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.environ.get(name, default if default is not None else "")
    if required and not value:
        print(f"[load-sample-data] Missing env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def registry_env(name: str, required: bool = True) -> str:
    """Registry Postgres setting. REGISTRY_PG* wins so AWE seed cannot hijack PG*."""
    value = os.environ.get(f"REGISTRY_{name}") or os.environ.get(name) or ""
    awe_db = os.environ.get("AWE_PGDATABASE") or ""
    if name == "PGDATABASE" and awe_db and value == awe_db:
        print(
            "[load-sample-data] PGDATABASE is the AWE database "
            f"({awe_db}). Set REGISTRY_PGDATABASE to the farmer registry DB.",
            file=sys.stderr,
        )
        sys.exit(1)
    if required and not value:
        print(
            f"[load-sample-data] Missing env var: REGISTRY_{name} or {name}",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


# ── Geo (master-data) ────────────────────────────────────────────────────────

_GEO_INDEX: dict = {}
_GEO_BY_ID: dict = {}
_GEO_LEAF: dict | None = None


def _md_connect():
    host = os.environ.get("MD_PGHOST")
    dbname = os.environ.get("MD_PGDATABASE")
    if not host or not dbname:
        return None
    return psycopg2.connect(
        host=host,
        port=os.environ.get("MD_PGPORT", "5432"),
        dbname=dbname,
        user=os.environ.get("MD_PGUSER", ""),
        password=os.environ.get("MD_PGPASSWORD", ""),
    )


def load_geo_indexes() -> None:
    global _GEO_INDEX, _GEO_BY_ID, _GEO_LEAF
    conn = _md_connect()
    if conn is None:
        log("MD_PG* not set — geo ids will be empty.")
        return
    try:
        with conn.cursor() as cur:
            cur.execute("select level_id, level_mnemonic from g2p_geo_levels")
            mnemonic = dict(cur.fetchall())
            cur.execute(
                "select level_value_id, level_id, level_value_mnemonic, "
                "parent_level_value_id from g2p_geo_level_values"
            )
            rows = cur.fetchall()
            _GEO_BY_ID = {
                vid: (mnemonic.get(lid, lid), name, parent)
                for vid, lid, name, parent in rows
            }
            _GEO_INDEX = {
                (parent or "", (name or "").strip().lower()): vid
                for vid, _lid, name, parent in rows
            }
            children = {parent for _vid, _lid, _name, parent in rows if parent}
            leaves = [
                vid for vid, _lid, _name, parent in rows if vid not in children
            ]
            _GEO_LEAF = _GEO_BY_ID.get(leaves[0]) and {
                "id": leaves[0],
                "hierarchy": hierarchy_from_id(leaves[0]),
            }
            if leaves:
                _GEO_LEAF = {
                    "id": leaves[0],
                    "hierarchy": hierarchy_from_id(leaves[0]),
                }
        log(f"master-data geo: {len(_GEO_BY_ID)} units.")
    finally:
        conn.close()


def hierarchy_from_id(pcode: str) -> dict:
    chain = []
    seen, cur = set(), pcode
    while cur and cur in _GEO_BY_ID and cur not in seen:
        seen.add(cur)
        level, name, parent = _GEO_BY_ID[cur]
        chain.append(
            {
                "level_mnemonic": level,
                "level_value_mnemonic": name,
                "level_value_id": cur,
            }
        )
        cur = parent
    chain.reverse()
    return {"hierarchy": chain}


def geo_for_record(rec: dict) -> tuple[str | None, dict | None]:
    if rec.get("geo_pcode") and rec["geo_pcode"] in _GEO_BY_ID:
        return rec["geo_pcode"], hierarchy_from_id(rec["geo_pcode"])
    if _GEO_LEAF:
        return _GEO_LEAF["id"], _GEO_LEAF["hierarchy"]
    return None, None


def _address_line(parts) -> str:
    if not parts:
        return ""
    if isinstance(parts, str):
        return parts
    return ", ".join(str(v) for v in parts.values() if v)


def _age_from_birth(birth: str | None, fallback: int | None) -> int | None:
    if not birth:
        return fallback
    try:
        y, m, d = [int(x) for x in str(birth)[:10].split("-")]
        born = date(y, m, d)
    except (TypeError, ValueError):
        return fallback
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _map_edu(value: str | None) -> str:
    key = (value or "BASIC").upper()
    return EDU_MAP.get(key, "BASIC")


def _map_income(value: str | None) -> str:
    key = (value or "SOI_CROP_PRODUCTION").upper()
    return INCOME_MAP.get(key, "SOI_CROP_PRODUCTION")


def _map_lang(value: str | None) -> str:
    key = (value or "ENGLISH").upper()
    return LANG_MAP.get(key, "ENGLISH")


def _read_csv_rows(path: Path, json_columns: set) -> list:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        out = []
        for row in csv.DictReader(f):
            parsed = {}
            for k, v in row.items():
                if v == "":
                    parsed[k] = None
                elif k in json_columns:
                    parsed[k] = json.loads(v)
                else:
                    parsed[k] = v
            out.append(parsed)
        return out


def load_people_from_csv() -> tuple[list, list]:
    inds_raw = _read_csv_rows(DEMO_DIR / "individuals.csv", JSON_COLUMNS_INDIVIDUAL)
    hhs_raw = _read_csv_rows(DEMO_DIR / "households.csv", set())
    if not inds_raw:
        return [], []
    individuals = []
    for i in inds_raw:
        phones = i.get("phone_numbers")
        phone = None
        if isinstance(phones, list) and phones:
            phone = phones[0].get("number") if isinstance(phones[0], dict) else str(phones[0])
        birth = i.get("birth_date") or "1985-01-01"
        individuals.append(
            {
                "internal_record_id": i.get("internal_record_id"),
                "household_id": i.get("household_id"),
                "full_name": i.get("full_name") or f"{i.get('first_name') or ''} {i.get('last_name') or ''}".strip(),
                "first_name": i.get("first_name") or "Farmer",
                "middle_name": i.get("middle_name"),
                "last_name": i.get("last_name") or "Seed",
                "given_name": i.get("given_name") or i.get("first_name") or "Farmer",
                "gender": (i.get("gender") or "MALE").upper(),
                "birth_date": str(birth)[:10],
                "estimated_age": _as_int(i.get("estimated_age")) or _age_from_birth(str(birth)[:10], 40),
                "marital_status": (i.get("marital_status") or "MARRIED").upper(),
                "education_level": _map_edu(i.get("education_level")),
                "foundational_id": i.get("foundational_id") or f"NID-{str(i.get('internal_record_id'))[-6:]}",
                "phone": phone,
                "latitude": i.get("latitude"),
                "longitude": i.get("longitude"),
                "address_line_1": i.get("address_line_1") or "",
                "country_code": i.get("country_code"),
                "geo_pcode": i.get("geo_pcode"),
            }
        )
    by_hh: dict[str, list] = {}
    for i in individuals:
        by_hh.setdefault(i.get("household_id"), []).append(i)
    households = []
    for h in hhs_raw:
        hid = h.get("internal_record_id") or h.get("household_id")
        members = by_hh.get(hid, [])
        if not members:
            continue
        head_name = h.get("head_name") or ""
        head = next((m for m in members if m["full_name"] == head_name), members[0])
        households.append(
            {
                "household_id": hid,
                "head": head,
                "members": members,
                "latitude": h.get("latitude") or head.get("latitude"),
                "longitude": h.get("longitude") or head.get("longitude"),
                "address_line_1": h.get("address_line_1") or head.get("address_line_1"),
                "country_code": h.get("country_code") or head.get("country_code"),
                "geo_pcode": h.get("geo_pcode") or head.get("geo_pcode"),
            }
        )
    log(f"CSV samples: {len(individuals)} individuals, {len(households)} households.")
    return individuals, households


def synthetic_households(count: int) -> list:
    geo_id, geo_h = geo_for_record({})
    out = []
    for n in range(count):
        members = []
        for mi, (first, last, gender, age) in enumerate(
            (
                ("Amina", f"Seed{n+1}", "FEMALE", 42),
                ("Omar", f"Seed{n+1}", "MALE", 45),
                ("Lila", f"Seed{n+1}", "FEMALE", 12),
            )
        ):
            birth = date.today().replace(year=date.today().year - age)
            members.append(
                {
                    "internal_record_id": f"syn-{n}-{mi}",
                    "household_id": f"syn-hh-{n}",
                    "full_name": f"{first} {last}",
                    "first_name": first,
                    "middle_name": None,
                    "last_name": last,
                    "given_name": first,
                    "gender": gender,
                    "birth_date": birth.isoformat(),
                    "estimated_age": age,
                    "marital_status": "MARRIED" if age >= 18 else "SINGLE",
                    "education_level": "BASIC",
                    "foundational_id": f"NID-SYN{n}{mi}",
                    "phone": f"+25470000{n:02d}{mi}",
                    "latitude": 1.29,
                    "longitude": 36.82,
                    "address_line_1": f"{n+1} Seed Lane",
                    "country_code": "KE",
                    "geo_pcode": geo_id,
                }
            )
        head = members[0]
        out.append(
            {
                "household_id": f"syn-hh-{n}",
                "head": head,
                "members": members,
                "latitude": 1.29,
                "longitude": 36.82,
                "address_line_1": head["address_line_1"],
                "country_code": "KE",
                "geo_pcode": geo_id,
            }
        )
        _ = geo_h
    log(f"synthetic samples: {len(out)} household(s).")
    return out


def _as_int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _as_float(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def person_phones(person: dict) -> list | None:
    if not person.get("phone"):
        return None
    return [{"type": "personal", "number": str(person["phone"]), "is_primary": True}]


def person_emails(person: dict) -> list:
    slug = "".join(ch for ch in (person.get("first_name") or "farmer").lower() if ch.isalnum())
    return [{"type": "personal", "address": f"{slug}.seed@example.org", "is_primary": True}]


def geo_fields(rec: dict) -> dict:
    lowest, hierarchy = geo_for_record(rec)
    return {
        "latitude": _as_float(rec.get("latitude")),
        "longitude": _as_float(rec.get("longitude")),
        "altitude": 1200.0,
        "plus_code": "SEED+00",
        "address_line_1": rec.get("address_line_1") or "1 Seed Road",
        "address_line_2": "Plot 1",
        "postal_code": "00100",
        "country_code": rec.get("country_code") or "KE",
        "geo_lowest_level_value_id": lowest,
        "geo_code_hierarchy_json": hierarchy,
    }


def person_fields(person: dict, *, extra: dict | None = None) -> dict:
    gender = (person.get("gender") or "MALE").upper()
    if gender == "OTHERS":
        gender = "OTHER"
    if gender not in ("MALE", "FEMALE", "OTHER", "UNKNOWN"):
        gender = "MALE"
    marital = (person.get("marital_status") or "MARRIED").upper()
    if marital not in ("SINGLE", "MARRIED", "DIVORCED", "WIDOWED", "SEPARATED", "UNKNOWN"):
        marital = "MARRIED"
    birth = str(person.get("birth_date") or "1985-01-01")[:10]
    age = person.get("estimated_age") or _age_from_birth(birth, 40)
    # Domain rule: estimated_age must match birth_date within one year.
    computed = _age_from_birth(birth, age)
    if computed is not None:
        age = computed
    nid = person.get("foundational_id") or "NID-000000"
    payload = {
        "first_name": person.get("first_name") or "Farmer",
        "middle_name": person.get("middle_name") or "K",
        "last_name": person.get("last_name") or "Seed",
        "given_name": person.get("given_name") or person.get("first_name") or "Farmer",
        "prefix": "Ms" if gender == "FEMALE" else "Mr",
        "suffix": None,
        "gender": gender,
        "birth_date": birth,
        "foundational_id": nid,
        "phone_numbers": person_phones(person) or [
            {"type": "personal", "number": "+254700000001", "is_primary": True}
        ],
        "emails": person_emails(person),
        "marital_status": marital,
        "occupation": "FARMER",
        "income_level": "LOW",
        "language_code": "en",
        "education_level": _map_edu(person.get("education_level")),
        "registration_date": date.today().isoformat(),
        **geo_fields(person),
    }
    if extra:
        payload.update(extra)
    return payload


# ── HTTP / Keycloak / Staff API ──────────────────────────────────────────────

def _ssl_ctx():
    if env_bool("INTAKE_SEED_VERIFY_TLS", True):
        return ssl.create_default_context()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http_json(
    method: str,
    url: str,
    *,
    data: dict | None = None,
    headers: dict | None = None,
    form: dict | None = None,
    timeout: int = 60,
) -> tuple[int, Any]:
    body = None
    hdrs = dict(headers or {})
    if form is not None:
        body = urllib_parse.urlencode(form).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif data is not None:
        body = json.dumps(data).encode()
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib_request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib_request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
            raw = resp.read()
            parsed = json.loads(raw.decode()) if raw else {}
            return resp.status, parsed
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(raw) if raw else {"text": raw}
        except json.JSONDecodeError:
            parsed = {"text": raw[:800]}
        return exc.code, parsed


class StaffClient:
    def __init__(self, base_url: str, token: str, username: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        csrf = uuid.uuid4().hex
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
            "Cookie": f"X-CSRF-Token={csrf}",
        }

    def post(self, path: str, payload: dict) -> dict:
        envelope = {
            "request_header": {
                "sender_app_mnemonic": "farmer-db-seed",
                "sender_app_url": "http://db-seed",
                "request_id": uuid.uuid4().hex,
                "request_timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "request_body": {"request_payload": payload},
        }
        url = f"{self.base_url}{path}"
        last_err = None
        for attempt in range(8):
            status, body = http_json("POST", url, data=envelope, headers=self.headers)
            header = (body or {}).get("response_header") or {}
            if status == 403 or (
                isinstance(header, dict) and str(header.get("response_error_code", "")).endswith("403")
            ):
                last_err = f"{path} as {self.username} -> 403 (auth warming up)"
                time.sleep(5)
                continue
            if status != 200:
                raise RuntimeError(f"{path} as {self.username} -> {status}: {body}")
            if header.get("response_status") == "ERROR":
                raise RuntimeError(
                    f"{path} as {self.username} ERROR "
                    f"{header.get('response_error_code')}: {header.get('response_error_message')}"
                )
            return ((body or {}).get("response_body") or {}).get("response_payload") or body
        raise RuntimeError(last_err or f"{path} failed")


def fetch_token(token_url: str, client_id: str, username: str, password: str, client_secret: str) -> str:
    form = {
        "grant_type": "password",
        "client_id": client_id,
        "username": username,
        "password": password,
        "scope": "openid",
    }
    if client_secret:
        form["client_secret"] = client_secret
    status, body = http_json("POST", token_url, form=form, timeout=20)
    if status != 200:
        raise RuntimeError(f"password grant failed for '{username}' ({status}): {body}")
    return body["access_token"]


def keycloak_prepare_users(
    base_url: str,
    realm: str,
    admin_user: str,
    admin_password: str,
    client_id: str,
    usernames: list[str],
    password: str,
) -> None:
    """Make alex.carter / nina.patel usable for the password grant."""
    token_url = f"{base_url.rstrip('/')}/realms/master/protocol/openid-connect/token"
    status, body = http_json(
        "POST",
        token_url,
        form={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": admin_user,
            "password": admin_password,
        },
        timeout=20,
    )
    if status != 200:
        log(f"keycloak admin login skipped ({status}): {body}")
        return
    admin_token = body["access_token"]
    hdrs = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    realm_url = f"{base_url.rstrip('/')}/admin/realms/{realm}"

    status, clients = http_json(
        "GET", f"{realm_url}/clients?clientId={urllib_parse.quote(client_id)}", headers=hdrs
    )
    if status == 200 and clients:
        client = clients[0]
        if not client.get("directAccessGrantsEnabled"):
            client["directAccessGrantsEnabled"] = True
            http_json("PUT", f"{realm_url}/clients/{client['id']}", data=client, headers=hdrs)
            log(f"enabled direct access grants on {client_id}")

    for username in usernames:
        status, users = http_json(
            "GET",
            f"{realm_url}/users?username={urllib_parse.quote(username)}&exact=true",
            headers=hdrs,
        )
        if status != 200 or not users:
            log(f"keycloak user '{username}' not found — login may fail")
            continue
        user_id = users[0]["id"]
        http_json(
            "PUT",
            f"{realm_url}/users/{user_id}/reset-password",
            data={"type": "password", "value": password, "temporary": False},
            headers=hdrs,
        )
        http_json(
            "PUT",
            f"{realm_url}/users/{user_id}",
            data={"requiredActions": [], "enabled": True},
            headers=hdrs,
        )
        log(f"keycloak user '{username}': password set non-temporary")


# ── Intake helpers ───────────────────────────────────────────────────────────

def section_record_id(save_result: dict, section_register_id: str) -> str:
    for payload in save_result.get("section_payloads") or []:
        if payload.get("section_register_id") != section_register_id:
            continue
        records = payload.get("records") or []
        if records:
            rid = records[0].get("internal_record_id")
            if rid:
                return rid
    raise RuntimeError(f"no internal_record_id returned for {section_register_id}")


def section_record_ids(save_result: dict, section_register_id: str) -> list[str]:
    for payload in save_result.get("section_payloads") or []:
        if payload.get("section_register_id") != section_register_id:
            continue
        return [
            r["internal_record_id"]
            for r in (payload.get("records") or [])
            if r.get("internal_record_id")
        ]
    return []


def save_section(
    client: StaffClient,
    *,
    submission_id: str | None,
    section_id: str,
    section_register_id: str,
    form_id: str,
    register_id: str,
    records: list[dict],
) -> dict:
    payload = {
        "submission_id": submission_id,
        "section_id": section_id,
        "section_payload": records,
        "section_register_id": section_register_id,
        "form_id": form_id,
        "register_id": register_id,
        "created_by": client.username,
        "documents": [],
    }
    result = client.post("/intake-form-data/save_intake_form_submission", payload)
    if not result or not result.get("submission_id"):
        raise RuntimeError(f"save {section_id} returned no submission_id: {result}")
    return result


def finalize(client: StaffClient, submission_id: str, register_id: str, form_id: str) -> dict:
    return client.post(
        "/intake-form-data/finalize_intake_form_submission",
        {"submission_id": submission_id, "register_id": register_id, "form_id": form_id},
    )


def open_awe_tasks(awe_conn, artifact_id: str) -> list[dict]:
    with awe_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT t.id AS task_id, t.stage_order, t.assignee
              FROM approval_task t
              JOIN approval_request r ON r.id = t.request_id
             WHERE r.artifact_id = %s
               AND t.status IN ('open', 'claimed')
             ORDER BY t.stage_order
            """,
            (str(artifact_id),),
        )
        return [dict(r) for r in cur.fetchall()]


def approve_intake(
    clients: dict[str, StaffClient],
    awe_conn,
    submission_id: str,
    timeout: int,
) -> None:
    """Walk AWE stages: alex.carter then nina.patel."""
    deadline = time.time() + timeout
    approved_any = False
    while time.time() < deadline:
        registry_conn = registry_connect()
        try:
            status = submission_approval_status(registry_conn, submission_id)
        finally:
            registry_conn.close()
        if status == "APPROVED":
            log(f"  submission {submission_id} approved")
            return
        tasks = open_awe_tasks(awe_conn, submission_id)
        if not tasks:
            if approved_any:
                time.sleep(2)
                continue
            time.sleep(2)
            continue
        for task in tasks:
            assignee = (task.get("assignee") or "").strip()
            client = clients.get(assignee) or clients.get(assignee.split("@")[0])
            if client is None:
                # Fall back to the named stage users if AWE stores a UUID.
                stage = int(task.get("stage_order") or 1)
                client = clients["alex.carter"] if stage == 1 else clients["nina.patel"]
            client.post(
                "/awe/submit_task_decision",
                {
                    "task_id": str(task["task_id"]),
                    "action": "approve",
                    "comment": f"db-seed intake approve ({client.username})",
                    "artifact_id": str(submission_id),
                    "artifact_type": ARTIFACT_INTAKE,
                    "current_stage": int(task.get("stage_order") or 1),
                },
            )
            log(
                f"  approved AWE task {task['task_id']} "
                f"stage={task.get('stage_order')} as {client.username}"
            )
            approved_any = True
        time.sleep(2)
    raise RuntimeError(
        f"submission {submission_id} was not approved within {timeout}s "
        "(check AWE, alex.carter / nina.patel, and celery ingest)"
    )


def registry_connect():
    return psycopg2.connect(
        host=registry_env("PGHOST"),
        port=os.environ.get("REGISTRY_PGPORT") or os.environ.get("PGPORT", "5432"),
        dbname=registry_env("PGDATABASE"),
        user=registry_env("PGUSER"),
        password=registry_env("PGPASSWORD"),
    )


def submission_approval_status(conn, submission_id: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "select approval_status from g2p_intake_form_submissions where submission_id = %s",
            (submission_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def wait_register_row(table: str, internal_id: str, timeout: int) -> None:
    deadline = time.time() + timeout
    sql = f'select 1 from "public"."{table}" where internal_record_id = %s'
    while time.time() < deadline:
        conn = registry_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (internal_id,))
                if cur.fetchone():
                    return
        finally:
            conn.close()
        time.sleep(2)
    raise RuntimeError(
        f"{table} row {internal_id} not ingested within {timeout}s — "
        "is celery worker + beat + beat-worker running on registry_worker_queue?"
    )


def wait_linked_rows(
    table: str,
    link_id: str | None,
    minimum: int,
    timeout: int,
    via_land_of: str | None = None,
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        conn = registry_connect()
        try:
            with conn.cursor() as cur:
                if via_land_of:
                    cur.execute(
                        f"""
                        select count(*) from "public"."{table}" c
                         join "public"."g2p_register_lands" l
                           on l.internal_record_id = c.link_internal_record_id
                        where l.link_internal_record_id = %s
                        """,
                        (via_land_of,),
                    )
                else:
                    cur.execute(
                        f'select count(*) from "public"."{table}" where link_internal_record_id = %s',
                        (link_id,),
                    )
                if cur.fetchone()[0] >= minimum:
                    return
        finally:
            conn.close()
        time.sleep(2)
    raise RuntimeError(
        f"{table} did not reach {minimum} ingested row(s) within {timeout}s"
    )


def already_seeded() -> bool:
    conn = registry_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("select count(*) from g2p_register_households")
            hh = cur.fetchone()[0]
            cur.execute("select count(*) from g2p_register_farmers")
            fr = cur.fetchone()[0]
            return hh > 0 and fr > 0
    except Exception:  # noqa: BLE001
        return False
    finally:
        conn.close()


def household_payload(hh: dict) -> dict:
    members = hh["members"]
    males = sum(1 for m in members if (m.get("gender") or "").upper() == "MALE")
    females = sum(1 for m in members if (m.get("gender") or "").upper() == "FEMALE")
    children = sum(1 for m in members if (m.get("estimated_age") or 0) < 18)
    elderly = sum(1 for m in members if (m.get("estimated_age") or 0) >= 60)
    size = males + females
    if size == 0:
        size = len(members) or 1
        males = size
        females = 0
    return {
        "household_head": hh["head"]["full_name"],
        "size_of_group": size,
        "number_of_children": children,
        "number_of_elderly_members": elderly,
        "number_of_male_members": males,
        "number_of_female_members": females,
        "other_land_owner": False,
        **geo_fields(hh),
    }


def member_payload(member: dict, household_intake_id: str, *, is_head: bool = False) -> dict:
    age = member.get("estimated_age") or 0
    if is_head:
        relationship = None
    elif age < 18:
        relationship = "CHILD"
    elif (member.get("marital_status") or "").upper() == "MARRIED":
        relationship = "SPOUSE"
    else:
        relationship = "OTHER"
    return {
        **person_fields(member),
        "is_disabled": False,
        "is_head": is_head,
        "relationship_to_the_head": relationship,
        "link_internal_record_id": household_intake_id,
    }


def farmer_extra(index: int) -> dict:
    disabled = index % 4 == 0
    income = (
        "SOI_CROP_PRODUCTION",
        "SOI_LIVESTOCK_PRODUCTION",
        "SOI_GOVERNMENT_NGO_SUPPORT",
        "SOI_OTHERS",
    )[index % 4]
    return {
        "estimated_age": None,  # filled from birth
        "has_personal_phone": True,
        "disabled": disabled,
        "disability_type": "MOBILITY" if disabled else None,
        "disability_severity": "SOME_DIFFICULTY" if disabled else None,
        "source_of_income": income,
        "source_of_income_other": "Seasonal work" if income == "SOI_OTHERS" else None,
        "language_spoken": ("ENGLISH", "HINDI", "FRENCH", "SPANISH")[index % 4],
        "national_id_masked": "XXXXXX1234",
    }


def land_payload(hh: dict, farmer_id: str, index: int) -> dict:
    geo = geo_fields(hh)
    lat = _as_float(hh.get("latitude")) or 1.29
    lon = _as_float(hh.get("longitude")) or 36.82
    return {
        "link_internal_record_id": farmer_id,
        "land_ownership_type": ("OWNER", "TENANT", "CROP_SHARE")[index % 3],
        "certificate_storage_id": None,
        "land_size": 2.5 + index,
        "unit": "HECTARE",
        "soil_fertility": ("SF_HIGH", "SF_MEDIUM", "SF_LOW")[index % 3],
        "current_land_use": "AGRICULTURAL",
        "farming_type": "MIXED",
        "year_of_acquisition": 2018,
        "means_of_acquisition": "MOA_INHERITANCE",
        **geo,
        "shape_type": "POINT",
        "shape_coordinates_json": {"type": "Point", "coordinates": [lon, lat]},
    }


def crop_payload(land_id: str, index: int) -> dict:
    commodity = ("CROP_MAIZE", "CROP_WHEAT", "CROP_TEFF")[index % 3]
    planted = (date.today() - timedelta(days=40)).isoformat()
    return {
        "link_internal_record_id": land_id,
        "commodity": commodity,
        "planted_date": planted,
        "season": "SEASON_SUMMER",
        "end_use": "FOOD_HUMAN_CONSUMPTION",
    }


def livestock_payload(land_id: str, index: int) -> dict:
    kind = ("LSTK_GOAT", "LSTK_CATTLE", "LSTK_SHEEP")[index % 3]
    return {
        "link_internal_record_id": land_id,
        "livestock_type": kind,
        "breed": "BREED_LOCAL",
        "head_count": 6 + index,
        "livestock_system": "MIXED",
    }


def farm_inputs_payload(land_id: str) -> dict:
    return {
        "link_internal_record_id": land_id,
        "fertilizer_use": True,
        "pesticide_use": False,
        "insecticide_use": False,
        "improved_seed_use": True,
        "water_source": "WS_WELL_GROUND",
        "access_to_machinery": True,
        "access_to_finance": False,
    }


def membership_payload(farmer_id: str, name: str) -> dict:
    return {
        "link_internal_record_id": farmer_id,
        "is_primary_cooperative_member": True,
        "primary_cooperative_name": f"{name} Cooperative",
        "is_cooperative_union_member": True,
        "cooperative_union_name": "District Farmers Union",
        "is_farmer_cluster_member": True,
        "farmer_cluster_role": "MEMBER",
    }


def submit_household(client: StaffClient, hh: dict) -> tuple[str, str]:
    info = household_payload(hh)
    saved = save_section(
        client,
        submission_id=None,
        section_id=HH_INFO_SECTION,
        section_register_id=HOUSEHOLD_REGISTER_ID,
        form_id=HOUSEHOLD_FORM_ID,
        register_id=HOUSEHOLD_REGISTER_ID,
        records=[info],
    )
    submission_id = saved["submission_id"]
    hh_id = section_record_id(saved, HOUSEHOLD_REGISTER_ID)
    loc = {**info, "internal_record_id": hh_id}
    save_section(
        client,
        submission_id=submission_id,
        section_id=HH_LOCATION_SECTION,
        section_register_id=HOUSEHOLD_REGISTER_ID,
        form_id=HOUSEHOLD_FORM_ID,
        register_id=HOUSEHOLD_REGISTER_ID,
        records=[loc],
    )
    head_id = hh["head"].get("internal_record_id")
    members = [
        member_payload(
            m,
            hh_id,
            is_head=m.get("internal_record_id") == head_id,
        )
        for m in hh["members"]
    ]
    save_section(
        client,
        submission_id=submission_id,
        section_id=HH_MEMBER_SECTION,
        section_register_id=HH_MEMBER_REGISTER_ID,
        form_id=HOUSEHOLD_FORM_ID,
        register_id=HOUSEHOLD_REGISTER_ID,
        records=members,
    )
    finalize(client, submission_id, HOUSEHOLD_REGISTER_ID, HOUSEHOLD_FORM_ID)
    return submission_id, hh_id


def submit_farmer(
    client: StaffClient, hh: dict, household_id: str, index: int
) -> tuple[str, str]:
    farmer = hh["head"]
    extra = farmer_extra(index)
    extra["estimated_age"] = _age_from_birth(farmer.get("birth_date"), farmer.get("estimated_age") or 40)
    extra["national_id_masked"] = f"XXXX{(farmer.get('foundational_id') or '0000')[-4:]}"
    personal = {
        **person_fields(farmer, extra=extra),
        "link_internal_record_id": household_id,
    }
    saved = save_section(
        client,
        submission_id=None,
        section_id=FARMER_PERSONAL_SECTION,
        section_register_id=FARMER_REGISTER_ID,
        form_id=FARMER_FORM_ID,
        register_id=FARMER_REGISTER_ID,
        records=[personal],
    )
    submission_id = saved["submission_id"]
    farmer_id = section_record_id(saved, FARMER_REGISTER_ID)
    linked = {**personal, "internal_record_id": farmer_id, "link_internal_record_id": household_id}
    save_section(
        client,
        submission_id=submission_id,
        section_id=FARMER_LOOKUP_SECTION,
        section_register_id=FARMER_REGISTER_ID,
        form_id=FARMER_FORM_ID,
        register_id=FARMER_REGISTER_ID,
        records=[linked],
    )
    save_section(
        client,
        submission_id=submission_id,
        section_id=FARMER_SOCIO_SECTION,
        section_register_id=FARMER_REGISTER_ID,
        form_id=FARMER_FORM_ID,
        register_id=FARMER_REGISTER_ID,
        records=[linked],
    )
    save_section(
        client,
        submission_id=submission_id,
        section_id=FARMER_LOCATION_SECTION,
        section_register_id=FARMER_REGISTER_ID,
        form_id=FARMER_FORM_ID,
        register_id=FARMER_REGISTER_ID,
        records=[linked],
    )

    land_rows = [land_payload(hh, farmer_id, 0), land_payload(hh, farmer_id, 1)]
    land_saved = save_section(
        client,
        submission_id=submission_id,
        section_id=FARMER_LAND_SECTION,
        section_register_id=LAND_REGISTER_ID,
        form_id=FARMER_FORM_ID,
        register_id=FARMER_REGISTER_ID,
        records=land_rows,
    )
    land_ids = section_record_ids(land_saved, LAND_REGISTER_ID)
    if len(land_ids) < 2:
        raise RuntimeError(f"expected 2 land ids, got {land_ids}")
    land_a, land_b = land_ids[0], land_ids[1]

    save_section(
        client,
        submission_id=submission_id,
        section_id=FARMER_CROP_SECTION,
        section_register_id=CROP_REGISTER_ID,
        form_id=FARMER_FORM_ID,
        register_id=FARMER_REGISTER_ID,
        records=[crop_payload(land_a, 0), crop_payload(land_b, 1)],
    )
    save_section(
        client,
        submission_id=submission_id,
        section_id=FARMER_LIVESTOCK_SECTION,
        section_register_id=LIVESTOCK_REGISTER_ID,
        form_id=FARMER_FORM_ID,
        register_id=FARMER_REGISTER_ID,
        records=[livestock_payload(land_a, 0), livestock_payload(land_a, 1)],
    )
    save_section(
        client,
        submission_id=submission_id,
        section_id=FARMER_INPUT_SECTION,
        section_register_id=FARM_INPUTS_REGISTER_ID,
        form_id=FARMER_FORM_ID,
        register_id=FARMER_REGISTER_ID,
        records=[farm_inputs_payload(land_a), farm_inputs_payload(land_b)],
    )
    save_section(
        client,
        submission_id=submission_id,
        section_id=FARMER_MEMBERSHIP_SECTION,
        section_register_id=MEMBERSHIP_REGISTER_ID,
        form_id=FARMER_FORM_ID,
        register_id=FARMER_REGISTER_ID,
        records=[membership_payload(farmer_id, farmer["full_name"])],
    )
    finalize(client, submission_id, FARMER_REGISTER_ID, FARMER_FORM_ID)
    return submission_id, farmer_id


def main() -> None:
    log("Starting intake-form sample seed…")
    staff_api = env("STAFF_API_URL", "http://127.0.0.1:8001")
    token_url = env(
        "STAFF_TOKEN_URL",
        env("KEYCLOAK_ISSUER_URL", "") + "/protocol/openid-connect/token"
        if env("KEYCLOAK_ISSUER_URL")
        else "",
    )
    if not token_url:
        print(
            "[load-sample-data] Set STAFF_TOKEN_URL or KEYCLOAK_ISSUER_URL "
            "(Keycloak password-grant token endpoint).",
            file=sys.stderr,
        )
        sys.exit(1)
    client_id = env("STAFF_CLIENT_ID", required=True)
    client_secret = env("STAFF_CLIENT_SECRET")
    password = env("INTAKE_SEED_PASSWORD", env("KEYCLOAK_AWE_APPROVER_PASSWORD", "pass"))
    submit_user = env("INTAKE_SEED_SUBMIT_USER", "alex.carter")
    approver1 = env("INTAKE_SEED_APPROVER_1", "alex.carter")
    approver2 = env("INTAKE_SEED_APPROVER_2", "nina.patel")
    ingest_timeout = env_int("INTAKE_SEED_INGEST_TIMEOUT", 180)
    approve_timeout = env_int("INTAKE_SEED_APPROVE_TIMEOUT", 180)
    max_hh = env_int("INTAKE_SEED_MAX_HOUSEHOLDS", 25)

    if already_seeded() and not env_bool("INTAKE_SEED_FORCE"):
        log("register already has household + farmer rows — skip (INTAKE_SEED_FORCE=true to redo).")
        return

    load_geo_indexes()
    _, households = load_people_from_csv()
    if not households:
        households = synthetic_households(max_hh)
    households = households[:max_hh]
    if not households:
        print("[load-sample-data] no people to seed", file=sys.stderr)
        sys.exit(1)

    kc_base = env("KEYCLOAK_BASE_URL")
    kc_admin = env("KEYCLOAK_ADMIN_USER")
    kc_admin_pw = env("KEYCLOAK_ADMIN_PASSWORD")
    kc_realm = env("KEYCLOAK_REALM", "staff")
    users = list(dict.fromkeys([submit_user, approver1, approver2]))
    if kc_base and kc_admin and kc_admin_pw:
        try:
            keycloak_prepare_users(
                kc_base, kc_realm, kc_admin, kc_admin_pw, client_id, users, password
            )
        except Exception as exc:  # noqa: BLE001
            log(f"keycloak prepare warning: {exc}")

    clients: dict[str, StaffClient] = {}
    for username in users:
        token = fetch_token(token_url, client_id, username, password, client_secret)
        clients[username] = StaffClient(staff_api, token, username)
        log(f"logged in as {username}")
    submitter = clients[submit_user]

    awe_conn = psycopg2.connect(
        host=env("AWE_PGHOST", env("PGHOST", required=True)),
        port=os.environ.get("AWE_PGPORT", os.environ.get("PGPORT", "5432")),
        dbname=env("AWE_PGDATABASE", "awe"),
        user=env("AWE_PGUSER", env("PGUSER", "")),
        password=env("AWE_PGPASSWORD", env("PGPASSWORD", "")),
    )

    try:
        for index, hh in enumerate(households):
            log(f"household {index + 1}/{len(households)}: {hh['head']['full_name']}")
            hh_sub, hh_id = submit_household(submitter, hh)
            approve_intake(clients, awe_conn, hh_sub, approve_timeout)
            wait_register_row("g2p_register_households", hh_id, ingest_timeout)
            wait_linked_rows("g2p_register_household_members", hh_id, 1, ingest_timeout)
            log(f"  household ingested id={hh_id}")

            log(f"farmer {index + 1}/{len(households)}: {hh['head']['full_name']} -> household {hh_id}")
            fr_sub, fr_id = submit_farmer(submitter, hh, hh_id, index)
            approve_intake(clients, awe_conn, fr_sub, approve_timeout)
            wait_register_row("g2p_register_farmers", fr_id, ingest_timeout)
            wait_linked_rows("g2p_register_lands", fr_id, 2, ingest_timeout)
            wait_linked_rows("g2p_register_crops", None, 2, ingest_timeout, via_land_of=fr_id)
            wait_linked_rows("g2p_register_livestocks", None, 2, ingest_timeout, via_land_of=fr_id)
            wait_linked_rows("g2p_register_farm_inputs", None, 2, ingest_timeout, via_land_of=fr_id)
            wait_linked_rows("g2p_register_membership_details", fr_id, 1, ingest_timeout)
            log(f"  farmer ingested id={fr_id}")
    finally:
        awe_conn.close()
    log("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[load-sample-data] FAILED: {exc}", file=sys.stderr)
        raise
