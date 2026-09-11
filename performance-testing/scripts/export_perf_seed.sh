#!/usr/bin/env bash
# Export DB-backed Locust search terms / household ids into openg2p/perf-seed/.
#
#   cd farmer-registry/performance-testing
#   source seeding/dsn.sh
#   ./scripts/export_perf_seed.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 "$ROOT/scripts/export_perf_seed.py" "$@"
