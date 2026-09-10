# Ingress -- which network path STAFF_API_BASE below actually reaches:
# in-cluster (Locust hitting the service's ClusterIP -- no RP hop, isolates
# the microservice) or end-to-end (through the public RP hostname, the real
# client path, RP can itself bottleneck). This only *labels* results --
# changing it does NOT change STAFF_API_BASE; you must point STAFF_API_BASE
# at the right host yourself. See documentation/environment-topology.md §5.
# Uncomment exactly one.
# export INGRESS=in-cluster
export INGRESS=end-to-end

export STAFF_API_BASE=https://staff-farmer-registry.perftest.openg2p.org
export KEYCLOAK_BASE=https://keycloak.perftest.openg2p.org
export KEYCLOAK_REALM=staff
export OIDC_CLIENT_ID=farmer-registry-staff-portal
export OIDC_CLIENT_SECRET=12yTrCklvC2obIdAV6DHPkva1P6r1LbP
export OIDC_USERNAME=nina.patel
export OIDC_PASSWORD=password
export SEARCH_PAGE_SIZE=10
export MAX_SEARCH_PAGE=10
export TAB_ITERATION_MIN_WAIT_SECONDS=0.0
export TAB_ITERATION_MAX_WAIT_SECONDS=0.0

# Volume-Tier -- see documentation/staff-api/test-scenarios.md §3. Uncomment exactly one.
# export VOLUME_TIER=smoke
export VOLUME_TIER=primary
# export VOLUME_TIER=stretch
# export VOLUME_TIER=stress

# Pod-Scale -- app replica count under test. Uncomment exactly one.
export POD_SCALE=1
# export POD_SCALE=2
# export POD_SCALE=3

# Step -- see documentation/staff-api/test-scenarios.md §3/§7. Uncomment exactly one.
export STEP=1-isolated
# export STEP=2-blended
# export STEP=3-soak
# export STEP=4-db-sweep

# Only used when STEP=1-isolated (picks which of the 5 scenarios to fire).
# Uncomment exactly one.
# export ISOLATED_SCENARIO=register-read
# export ISOLATED_SCENARIO=cr-create
# export ISOLATED_SCENARIO=cr-read-and-approve
# export ISOLATED_SCENARIO=intake-create
export ISOLATED_SCENARIO=intake-read-and-approve

# =============================================================================
# SLOs -- documentation/staff-api/test-scenarios.md §5. One section per
# endpoint class: the p95/p99 SLO (ms) plus the exact list of endpoint
# `name=` values (comma-separated, matching each locustfile's stats-grouping
# names) that belong to that class. shared/slo_shape.py loads these at
# import time into one endpoint -> SLO map, shared by every scenario's
# LoadTestShape -- edit values/membership here, not in Python.
# =============================================================================

# Freeze the isolated ramp when a farmer staff-portal-api pod reaches this
# many cores (kubectl top). 1.8 leaves headroom under a 2-vCPU limit.
export CPU_BREACH_CORES=1.6
export STAFF_API_KUBE_NAMESPACE=perftest
export STAFF_API_POD_GREP=farmer-registry-staff-portal-api

# --- SLO class: Metadata-Read ------------------------------------------------
export SLO_P95_METADATA_READ_MS=800
export SLO_P99_METADATA_READ_MS=1000
export METADATA_READ_ENDPOINTS="get_all_tabs,get_all_sections,get_tab_sections,get_section_ui_schema,get_attribute_values,render_intake_form"

# --- SLO class: Register-Read ------------------------------------------------
export SLO_P95_REGISTER_READ_MS=800
export SLO_P99_REGISTER_READ_MS=1000
export REGISTER_READ_ENDPOINTS="get_register_summary_data,get_subject_record,get_tab_records,get_number_of_versions,get_version_dates,get_versions_for_a_date,get_deduplication_register_results"
# get_record_history is Register-Read too (same 300/600ms SLO above), but is
# EXCLUDED from REGISTER_READ_ENDPOINTS above -- known upstream bug
# (SYS-ERR-001, see ../seeding-design.md) causes 100% failures, which would
# make SLOStepRampShape stop register_read's ramp on the very first checked
# step. Once product engineering ships the fix, uncomment the line below to
# fold it back in and re-enable its SLO check.
# export REGISTER_READ_ENDPOINTS="${REGISTER_READ_ENDPOINTS},get_record_history"

# --- SLO class: Change-Request-Read ------------------------------------------
export SLO_P95_CHANGE_REQUEST_READ_MS=800
export SLO_P99_CHANGE_REQUEST_READ_MS=1000
export CHANGE_REQUEST_READ_ENDPOINTS="get_change_request,check_change_request_sequence,get_deduplication_change_request_results,get_number_of_pending_change_requests,get_change_requests,get_register_change_request_summary_data"

# --- SLO class: Intake-Submission-Read ---------------------------------------
export SLO_P95_INTAKE_SUBMISSION_READ_MS=800
export SLO_P99_INTAKE_SUBMISSION_READ_MS=1000
export INTAKE_SUBMISSION_READ_ENDPOINTS="get_intake_form_submission,get_intake_form_submissions_summary,get_deduplication_intake_form_register_results,get_deduplication_intake_form_intake_form_results"

# --- SLO class: Register-Search ----------------------------------------------
export SLO_P95_REGISTER_SEARCH_MS=800
export SLO_P99_REGISTER_SEARCH_MS=1000
export REGISTER_SEARCH_ENDPOINTS="search_in_a_register,search_in_change_request,search_in_intake_form_submissions"

# --- SLO class: Change-Request-Write -----------------------------------------
export SLO_P95_CHANGE_REQUEST_WRITE_MS=800
export SLO_P99_CHANGE_REQUEST_WRITE_MS=1000
export CHANGE_REQUEST_WRITE_ENDPOINTS="create_change_request,create_change_request_for_core_data"

# --- SLO class: Intake-Submission-Write --------------------------------------
export SLO_P95_INTAKE_SUBMISSION_WRITE_MS=800
export SLO_P99_INTAKE_SUBMISSION_WRITE_MS=1000
export INTAKE_SUBMISSION_WRITE_ENDPOINTS="save_intake_form_submission,finalize_intake_form_submission"

# --- SLO class: Workflow-Read -------------------------------------------------
export SLO_P95_WORKFLOW_READ_MS=1200
export SLO_P99_WORKFLOW_READ_MS=1300
export WORKFLOW_READ_ENDPOINTS="list_tasks_for_request"

# --- SLO class: Workflow-Write ------------------------------------------------
export SLO_P95_WORKFLOW_WRITE_MS=1200
export SLO_P99_WORKFLOW_WRITE_MS=1300
export WORKFLOW_WRITE_ENDPOINTS="submit_task_decision"

# --- SLO class: Document-Fetch ------------------------------------------------
export SLO_P95_DOCUMENT_FETCH_MS=800
export SLO_P99_DOCUMENT_FETCH_MS=1000
export DOCUMENT_FETCH_ENDPOINTS="get_file_url,get_change_request_documents,get_intake_form_documents"

# --- SLO class: Document-Upload ----------------------------------------------
# No p99 -- size-dependent, see test-scenarios.md §5.
export SLO_P95_DOCUMENT_UPLOAD_MS=800
export DOCUMENT_UPLOAD_ENDPOINTS="upload_documents"

echo "------------------"
echo "------ ENV -------"
echo "------------------"

echo "$INGRESS"
echo "$STAFF_API_BASE"
echo "$KEYCLOAK_BASE"
echo "$KEYCLOAK_REALM"
echo "$OIDC_CLIENT_ID"
echo "$OIDC_CLIENT_SECRET"
echo "$OIDC_USERNAME"
echo "$OIDC_PASSWORD"
echo "$SEED_MANIFEST"
echo "$SEARCH_PAGE_SIZE"
echo "$MAX_SEARCH_PAGE"
echo "$TAB_ITERATION_MIN_WAIT_SECONDS"
echo "$TAB_ITERATION_MAX_WAIT_SECONDS"
echo "$VOLUME_TIER"
echo "$POD_SCALE"
echo "$STEP"
echo "$ISOLATED_SCENARIO"
echo "$CPU_BREACH_CORES"
echo "$STAFF_API_KUBE_NAMESPACE"
echo "$STAFF_API_POD_GREP"
