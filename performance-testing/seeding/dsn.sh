# Perftest farmer_registry through the local port-forward on 5434
# (same postgres user as the original dsn.sh / staff-api tunnel).
export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5434}"
export PGDATABASE="${PGDATABASE:-farmer_registry}"
export PGUSER="${PGUSER:-postgres}"
export PGPASSWORD="${PGPASSWORD:-FrvXKYSLUclkcgOzp2a18RPf6UFJWXEi}"
export SEED_DB_DSN="postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${PGDATABASE}"

echo "——————————————————————————"
echo "------ SEED_DB_DSN -------"
echo "——————————————————————————"
echo "postgresql://${PGUSER}:***@${PGHOST}:${PGPORT}/${PGDATABASE}"
