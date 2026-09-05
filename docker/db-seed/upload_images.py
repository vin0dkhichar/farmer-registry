#!/usr/bin/env python3
"""Upload sample profile images to MinIO and link them via the document catalog.

Flow:
1. Upload each image to the documents bucket (object key = filename).
2. Insert a g2p_registry_documents catalog row (bucket=documents).
3. Set g2p_register_farmers.record_image_document_id = catalog.document_id.

Images live at openg2p-data/demography/images/IND-XXXX.jpg. Farmers reuse the
individual record id (i####), so we match on internal_record_id derived from
the image's numeric suffix.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from minio import Minio

INDIVIDUAL_ID_PREFIX = "i"


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        print(f"[upload-images] Missing required env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def individual_uuid_from_stem(stem: str) -> str | None:
    """IND-0001 -> i0001. Also ETH-IND-0001 -> i0001.

    Last segment, not [1]: a country-prefixed stem would otherwise hit the
    ValueError branch and silently skip every image. Same trap as _fr_id in
    load_sample_data.py, but this one fails quietly rather than loudly.
    """
    try:
        seq = int(stem.rsplit("-", 1)[-1])
    except (IndexError, ValueError):
        return None
    return f"{INDIVIDUAL_ID_PREFIX}{seq:04d}"


def main() -> None:
    images_dir = Path(os.environ.get("IMAGES_DIR", "/openg2p-data/demography/images"))
    # Physical bucket must match DocumentBucket.DOCUMENTS ("documents")
    bucket_name = env("IMAGE_BUCKET_NAME", "documents")
    endpoint = env("MINIO_ENDPOINT")
    access_key = env("MINIO_ACCESS_KEY")
    secret_key = env("MINIO_SECRET_KEY")
    secure = os.environ.get("MINIO_SECURE", "false").lower() in ("1", "true", "yes")

    if not images_dir.is_dir():
        print(f"[upload-images] Images directory not found: {images_dir}", file=sys.stderr)
        sys.exit(1)

    image_files = sorted(images_dir.glob("*.jpg"))
    if not image_files:
        print(f"[upload-images] No .jpg files found in {images_dir}", file=sys.stderr)
        sys.exit(1)

    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
    if not client.bucket_exists(bucket_name):
        client.make_bucket(bucket_name)
        print(f"[upload-images] Created MinIO bucket: {bucket_name}")

    print(f"[upload-images] Uploading {len(image_files)} image(s) to s3://{bucket_name}/ …")
    uploaded: list[tuple[str, str]] = []
    for path in image_files:
        internal_record_id = individual_uuid_from_stem(path.stem)
        if internal_record_id is None:
            print(f"[upload-images] Skipping unrecognised filename: {path.name}")
            continue
        client.fput_object(bucket_name, path.name, str(path), content_type="image/jpeg")
        uploaded.append((internal_record_id, path.name))
    print(f"[upload-images] Uploaded {len(uploaded)} images.")

    conn = psycopg2.connect(
        host=env("REGISTRY_PGHOST") or env("PGHOST"),
        port=os.environ.get("REGISTRY_PGPORT") or os.environ.get("PGPORT", "5432"),
        dbname=env("REGISTRY_PGDATABASE") or env("PGDATABASE"),
        user=env("REGISTRY_PGUSER") or env("PGUSER"),
        password=env("REGISTRY_PGPASSWORD") or env("PGPASSWORD"),
    )
    conn.autocommit = False
    cur = conn.cursor()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        updated = 0
        for internal_record_id, object_key in uploaded:
            document_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO "public"."g2p_registry_documents"
                    (document_id, document_store_id, bucket, source_filename, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_store_id) DO UPDATE
                    SET source_filename = EXCLUDED.source_filename
                RETURNING document_id
                """,
                (document_id, object_key, "documents", object_key, "seeder", now),
            )
            row = cur.fetchone()
            catalog_document_id = row[0] if row else document_id

            cur.execute(
                """
                UPDATE "public"."g2p_register_farmers"
                SET record_image_document_id = %s
                WHERE internal_record_id = %s
                """,
                (catalog_document_id, internal_record_id),
            )
            updated += cur.rowcount

        conn.commit()
        print(
            f"[upload-images] Catalogued {len(uploaded)} images; "
            f"updated {updated} rows in g2p_register_farmers."
        )
    except Exception as exc:
        conn.rollback()
        print(f"[upload-images] DB update FAILED: {exc}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
