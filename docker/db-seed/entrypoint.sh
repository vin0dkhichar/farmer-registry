#!/bin/sh
set -e

# Farmer db-seed entrypoint.
# Same as the registry-platform hook, except AWE policies are applied BEFORE
# sample data: farmer sample records are created through the intake-form API
# and approved by alex.carter / nina.patel, which needs AWE policies in place.

PGPORT="${PGPORT:-5432}"
# Snapshot registry DSN before any AWE/master-data helper can overwrite PG*.
REGISTRY_PGHOST="${REGISTRY_PGHOST:-$PGHOST}"
REGISTRY_PGPORT="${REGISTRY_PGPORT:-$PGPORT}"
REGISTRY_PGDATABASE="${REGISTRY_PGDATABASE:-$PGDATABASE}"
REGISTRY_PGUSER="${REGISTRY_PGUSER:-$PGUSER}"
REGISTRY_PGPASSWORD="${REGISTRY_PGPASSWORD:-$PGPASSWORD}"
export REGISTRY_PGHOST REGISTRY_PGPORT REGISTRY_PGDATABASE REGISTRY_PGUSER REGISTRY_PGPASSWORD

restore_registry_pg() {
  PGHOST="$REGISTRY_PGHOST"
  PGPORT="$REGISTRY_PGPORT"
  PGDATABASE="$REGISTRY_PGDATABASE"
  PGUSER="$REGISTRY_PGUSER"
  PGPASSWORD="$REGISTRY_PGPASSWORD"
  export PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD
}

LOAD_GEO_DATA="${LOAD_GEO_DATA:-false}"
SYNC_GEO_WIDGETS="${SYNC_GEO_WIDGETS:-false}"
LOAD_SAMPLE_DATA="${LOAD_SAMPLE_DATA:-false}"
LOAD_IMAGES="${LOAD_IMAGES:-false}"
LOAD_TEMPLATES="${LOAD_TEMPLATES:-false}"
AWE_DB_SEED_ENABLED="${AWE_DB_SEED_ENABLED:-false}"

SEED_DIR="/seed"
META_DATA_DIR="${SEED_DIR}/meta_data"
AWE_META_DATA_DIR="${SEED_DIR}/awe_meta_data"

run_sql_files() {
  dir="$1"
  label="$2"
  db_host="${3:-$PGHOST}"
  db_port="${4:-$PGPORT}"
  db_name="${5:-$PGDATABASE}"
  db_user="${6:-$PGUSER}"
  db_password="${7:-$PGPASSWORD}"
  # Do not export PG* — seed_awe would otherwise leak AWE connection into
  # load_sample_data.py (which reads PGDATABASE for the registry).

  if [ ! -d "$dir" ]; then
    echo "[db-seed] No ${label} directory found at ${dir}, skipping."
    return
  fi

  sql_files=$(find "$dir" -name '*.sql' -type f | sort)
  if [ -z "$sql_files" ]; then
    echo "[db-seed] No SQL files found in ${dir}, skipping."
    return
  fi

  echo "[db-seed] Running ${label} on ${db_name}@${db_host}:${db_port} ..."
  for f in $sql_files; do
    echo "[db-seed]   -> $(basename "$f")"
    PGHOST="$db_host" PGPORT="$db_port" PGDATABASE="$db_name" PGUSER="$db_user" PGPASSWORD="$db_password" \
      psql -v ON_ERROR_STOP=0 -f "$f"
  done
  echo "[db-seed] ${label} completed."
}

run_callback_secret() {
  tpl="${AWE_META_DATA_DIR}/40_callback_secret.sql.tpl"
  if [ ! -f "$tpl" ]; then
    return
  fi
  if [ -z "$AWE_CALLBACK_HMAC_SECRET" ]; then
    echo "[db-seed] AWE_CALLBACK_HMAC_SECRET unset — skipping callback_secret."
    return
  fi
  if [ -z "$AWE_CALLBACK_CALLER_SERVICE" ]; then
    echo "[db-seed] AWE_CALLBACK_CALLER_SERVICE unset — skipping callback_secret."
    return
  fi
  AWE_CALLBACK_SECRET_ID="${AWE_CALLBACK_SECRET_ID:-registry}"
  echo "[db-seed]   -> callback_secret (AWE DB, from template) id=${AWE_CALLBACK_SECRET_ID} caller_service=${AWE_CALLBACK_CALLER_SERVICE}"
  export AWE_CALLBACK_HMAC_SECRET AWE_CALLBACK_SECRET_ID AWE_CALLBACK_CALLER_SERVICE
  PGHOST="${AWE_PGHOST}" PGPORT="${AWE_PGPORT:-5432}" PGDATABASE="${AWE_PGDATABASE}" \
    PGUSER="${AWE_PGUSER}" PGPASSWORD="${AWE_PGPASSWORD}" \
    envsubst '${AWE_CALLBACK_HMAC_SECRET} ${AWE_CALLBACK_SECRET_ID} ${AWE_CALLBACK_CALLER_SERVICE}' < "$tpl" | psql -v ON_ERROR_STOP=0 -f -
}

seed_awe() {
  if [ "$AWE_DB_SEED_ENABLED" != "true" ]; then
    echo "[db-seed] Skipping AWE seed (AWE_DB_SEED_ENABLED=${AWE_DB_SEED_ENABLED})."
    return
  fi
  if [ -z "$AWE_PGDATABASE" ] || [ -z "$AWE_PGHOST" ]; then
    echo "[db-seed] AWE_DB_SEED_ENABLED but AWE DB env incomplete — skipping AWE seed."
    return
  fi
  echo "---------------------------------------------"
  echo " AWE DB : ${AWE_PGDATABASE}@${AWE_PGHOST}:${AWE_PGPORT:-5432}"
  echo "---------------------------------------------"
  run_sql_files "$AWE_META_DATA_DIR" "AWE meta_data" \
    "$AWE_PGHOST" "${AWE_PGPORT:-5432}" "$AWE_PGDATABASE" "$AWE_PGUSER" "$AWE_PGPASSWORD"
  run_callback_secret
}

echo "============================================="
echo " OpenG2P Farmer Registry DB Seed"
echo " Registry DB : ${PGDATABASE}@${PGHOST}:${PGPORT}"
echo " Master DB   : ${MD_PGDATABASE:-unset}@${MD_PGHOST:-unset}:${MD_PGPORT:-5432}"
echo " AWE DB seed : ${AWE_DB_SEED_ENABLED}"
echo " Geo data    : ${LOAD_GEO_DATA}"
echo " Sample data : ${LOAD_SAMPLE_DATA} (intake-form API)"
echo " Images      : ${LOAD_IMAGES}"
echo " Templates   : ${LOAD_TEMPLATES}"
echo "============================================="

run_sql_files "$META_DATA_DIR" "meta-data"

if [ "$LOAD_GEO_DATA" = "true" ]; then
  echo "[db-seed] Loading geo data into master_data ..."
  python3 /seed/load_geo_data.py
else
  echo "[db-seed] Skipping geo data (LOAD_GEO_DATA=${LOAD_GEO_DATA})."
fi

if [ "$SYNC_GEO_WIDGETS" = "true" ]; then
  echo "[db-seed] Syncing geo widgets to the loaded country hierarchy ..."
  python3 /seed/sync_geo_widgets.py
else
  echo "[db-seed] Skipping geo-widget sync (SYNC_GEO_WIDGETS=${SYNC_GEO_WIDGETS})."
fi

# AWE policies must exist before intake finalize/approve.
seed_awe
restore_registry_pg

if [ "$LOAD_SAMPLE_DATA" = "true" ]; then
  if [ -f /seed/load_sample_data.py ]; then
    echo "[db-seed] Loading sample data via intake-form API ..."
    python3 /seed/load_sample_data.py
  else
    echo "[db-seed] ERROR: LOAD_SAMPLE_DATA=true but /seed/load_sample_data.py is missing." >&2
    exit 1
  fi
else
  echo "[db-seed] Skipping sample data (LOAD_SAMPLE_DATA=${LOAD_SAMPLE_DATA})."
fi

if [ "$LOAD_IMAGES" = "true" ]; then
  if [ -f /seed/upload_images.py ]; then
    echo "[db-seed] Uploading profile images to MinIO ..."
    python3 /seed/upload_images.py
  else
    echo "[db-seed] ERROR: LOAD_IMAGES=true but /seed/upload_images.py is missing." >&2
    exit 1
  fi
else
  echo "[db-seed] Skipping image upload (LOAD_IMAGES=${LOAD_IMAGES})."
fi

if [ "$LOAD_TEMPLATES" = "true" ]; then
  echo "[db-seed] Uploading templates to MinIO ..."
  python3 /seed/upload_templates.py
else
  echo "[db-seed] Skipping template upload (LOAD_TEMPLATES=${LOAD_TEMPLATES})."
fi

echo "[db-seed] Done."
