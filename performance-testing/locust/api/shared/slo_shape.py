import html
import json
import os
import subprocess
from collections import Counter

from locust import LoadTestShape, events
from locust.stats import calculate_response_time_percentile

# Endpoint classes -- must match the *_ENDPOINTS / SLO_P95_*_MS section names
# in env.sh exactly (documentation/staff-api/test-scenarios.md §5).
SLO_CLASSES = [
    "METADATA_READ",
    "REGISTER_READ",
    "CHANGE_REQUEST_READ",
    "INTAKE_SUBMISSION_READ",
    "REGISTER_SEARCH",
    "CHANGE_REQUEST_WRITE",
    "INTAKE_SUBMISSION_WRITE",
    "WORKFLOW_READ",
    "WORKFLOW_WRITE",
    "DOCUMENT_FETCH",
    "DOCUMENT_UPLOAD",
]


def _load_endpoint_slo_ms() -> tuple[dict[str, int], dict[str, int]]:
    """Two endpoint -> SLO-ms maps (p95, p99), built from env.sh's per-class
    sections. A single shared pair of maps works for every scenario: each
    scenario's Locust run only ever produces stats.entries for the endpoints
    it actually fires, so SLOStepRampShape naturally only checks the subset
    relevant to whichever scenario is running -- no per-scenario map needed.
    """
    p95_mapping: dict[str, int] = {}
    p99_mapping: dict[str, int] = {}
    for cls in SLO_CLASSES:
        p95_env = os.environ.get(f"SLO_P95_{cls}_MS")
        p99_env = os.environ.get(f"SLO_P99_{cls}_MS")
        endpoints_env = os.environ.get(f"{cls}_ENDPOINTS", "")
        if not p95_env or not endpoints_env:
            continue
        p95 = int(p95_env)
        p99 = int(p99_env) if p99_env else None
        for name in endpoints_env.split(","):
            name = name.strip()
            if not name:
                continue
            p95_mapping[name] = p95
            if p99 is not None:
                p99_mapping[name] = p99
    return p95_mapping, p99_mapping


ENDPOINT_SLO_P95_MS, ENDPOINT_SLO_P99_MS = _load_endpoint_slo_ms()

# Farmer staff-api CPU snapshot for the separate /farmer-cpu page (not mixed
# into Locust Statistics). Freeze logic still uses CPU_BREACH_CORES in tick().
STAFF_API_CPU: dict = {
    "hottest_cores": None,
    "total_cores": None,
    "limit_cores": float(os.environ.get("CPU_BREACH_CORES", "1.8")),
    "polls": 0,
    "error": None,
    "pods": [],
}

_POD_CPU_EXTREMA: dict[str, tuple[float, float]] = {}


def _short_pod_name(name: str) -> str:
    suffix = name.rsplit("-", 1)[-1]
    return suffix if suffix else name


def _farmer_cpu_live_html() -> str:
    snapshot = json.dumps(STAFF_API_CPU, indent=2)
    snapshot_safe = html.escape(snapshot)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Farmer staff-api CPU</title>
  <style>
    body {{ font-family: sans-serif; margin: 16px; }}
    table {{ border-collapse: collapse; }}
    td, th {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
    pre {{ background: #111; color: #eee; padding: 12px; overflow: auto; }}
  </style>
</head>
<body>
  <h1>Farmer staff-portal-api CPU</h1>
  <p>Live (polls every 2s). Locust Statistics is unchanged. Raw JSON:
     <a href="/staff-api-cpu.json">/staff-api-cpu.json</a></p>
  <p id="summary"></p>
  <table>
    <thead><tr><th>pod</th><th>cpu cores</th><th>min</th><th>max</th></tr></thead>
    <tbody id="pods"></tbody>
  </table>
  <pre id="json">{snapshot_safe}</pre>
  <script>
    async function refresh() {{
      const res = await fetch("/staff-api-cpu.json", {{ cache: "no-store" }});
      const data = await res.json();
      document.getElementById("json").textContent = JSON.stringify(data, null, 2);
      const pods = data.pods || [];
      document.getElementById("summary").textContent =
        "pods=" + pods.length +
        " total=" + data.total_cores +
        " hottest=" + data.hottest_cores +
        " limit=" + data.limit_cores +
        " polls=" + data.polls +
        (data.error ? " error=" + data.error : "");
      const tbody = document.getElementById("pods");
      tbody.innerHTML = "";
      if (!pods.length) {{
        tbody.innerHTML = "<tr><td colspan='4'>no farmer staff-api pods yet</td></tr>";
        return;
      }}
      for (const pod of pods) {{
        const tr = document.createElement("tr");
        tr.innerHTML =
          "<td>" + pod.name + "</td>" +
          "<td>" + Number(pod.cores).toFixed(3) + "</td>" +
          "<td>" + Number(pod.min_cores).toFixed(3) + "</td>" +
          "<td>" + Number(pod.max_cores).toFixed(3) + "</td>";
        tbody.appendChild(tr);
      }}
    }}
    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>
"""


@events.init.add_listener
def _attach_farmer_cpu_page(environment, **kwargs):
    if not environment.web_ui:
        return
    try:
        from flask import jsonify, make_response
    except ImportError:
        return

    @environment.web_ui.app.route("/staff-api-cpu.json")
    def staff_api_cpu_json():
        response = jsonify(STAFF_API_CPU)
        response.headers["Cache-Control"] = "no-store"
        return response

    @environment.web_ui.app.route("/staff-api-cpu")
    def staff_api_cpu():
        response = make_response(_farmer_cpu_live_html())
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return response

    @environment.web_ui.app.route("/farmer-cpu")
    def farmer_cpu_page():
        response = make_response(_farmer_cpu_live_html())
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return response


def _parse_kubectl_cpu(token: str) -> float:
    """Convert `kubectl top` CPU tokens (e.g. 1999m, 1.80, 2) to cores."""
    token = token.strip()
    if token.endswith("m"):
        return float(token[:-1]) / 1000.0
    return float(token)


class SLOStepRampShape(LoadTestShape):
    """
    Step-1 (isolated) ramp-to-breach-then-soak shape, driven by
    ENDPOINT_SLO_P95_MS / ENDPOINT_SLO_P99_MS (loaded from env.sh, not
    hardcoded -- see documentation/staff-api/test-scenarios.md §4/§5). A
    scenario fires endpoints from several different SLO classes in one run
    (e.g. register_read touches Metadata-Read and Register-Search), so this
    checks each endpoint against its own class's SLOs, not the whole run
    against one number.

    Starts with warmup_seconds at warmup_users with NO SLO checks (cold
    cache / first-connection noise is discarded). Then ramps +step_users
    every step_seconds. Once any tracked endpoint (with enough *successful*
    samples this step) breaches its own p95 OR p99 SLO, the ramp freezes at
    the last good user count and holds for sustain_seconds, printing p95/p99
    during that soak, then stops. If a farmer staff-api replica reaches
    CPU_BREACH_CORES, the ramp also freezes at the current user count.
    Per-pod CPU is shown on /farmer-cpu, not in Locust Statistics.

    If max_users is reached with no breach, it stops immediately without a
    soak.

    503s/other failures are logged but do NOT stop or freeze the ramp, and
    do NOT feed the p95/p99 calculation used to decide a breach either --
    only successful requests' response times count toward SLO checks (a
    failed request's "response time" -- e.g. a near-instant connection
    reset -- isn't a real latency sample, and Locust's own
    get_current_response_time_percentile() would otherwise silently mix
    failed and successful requests together). This shape tracks its own
    per-step, success-only response-time samples via a `request` event
    listener rather than relying on that built-in.

    NOTE: -u/-r/-t are ignored by Locust once a custom shape is active (see
    COMMON_OPTIONS in locust/main.py) -- this class owns its entire stop
    condition, including the max_users safety net.

    NOTE: register_read's get_record_history has a known upstream bug
    (SYS-ERR-001 -- see documentation/seeding-design.md) causing 100%
    failures. It's deliberately excluded from REGISTER_READ_ENDPOINTS in
    env.sh (commented-out toggle to re-add it once fixed) -- since failures
    no longer freeze/stop the ramp on their own, this is now a labeling
    concern rather than a ramp-killer, but it's still excluded to keep
    register_read's failure log free of a known, unrelated noise source.
    """

    # Base class, not meant to be run directly -- must NOT be auto-detected
    # by Locust as a runnable shape (only its per-scenario subclasses, e.g.
    # RegisterReadRampShape, should be). Locust's load_locustfile treats any
    # LoadTestShape subclass as runnable unless abstract=True is set
    # explicitly in that class's own body (see
    # locust/util/load_locustfile.py's is_shape_class) -- without this, a
    # locustfile that merely imports SLOStepRampShape (to subclass it) would
    # have Locust pick up two candidate shapes: this base class AND the
    # subclass, arbitrarily choosing one.
    abstract = True

    endpoint_slo_p95_ms: dict[str, int] = ENDPOINT_SLO_P95_MS
    endpoint_slo_p99_ms: dict[str, int] = ENDPOINT_SLO_P99_MS
    step_seconds = 30
    step_users = 4
    max_users = 100
    # Docs §7: warm 1–5 min and discard. Hold at warmup_users with no SLO
    # checks so cold-start latency cannot freeze the ramp.
    warmup_seconds = 1 * 60
    warmup_users = 2
    # Need enough success samples for a meaningful percentile; 5 made p95
    # ≈ max-of-5 and let a single outlier freeze the ramp.
    min_requests_for_check = 100
    sustain_seconds = 10 * 60
    cpu_breach_cores = float(os.environ.get("CPU_BREACH_CORES", "1.8"))
    kube_namespace = os.environ.get("STAFF_API_KUBE_NAMESPACE", "perftest")
    pod_grep = os.environ.get("STAFF_API_POD_GREP", "farmer-registry-staff-portal-api")
    cpu_poll_seconds = 10

    def __init__(self):
        super().__init__()
        self._step = -1
        self._step_start: dict[tuple[str, str], tuple[int, int]] = {}
        self._step_success_times: dict[tuple[str, str], list[int]] = {}
        self._breach_user_count: int | None = None
        self._breach_run_time: float | None = None
        self._breach_reason: str | None = None
        self._soak_started = False
        self._soak_last_report_at: float | None = None
        self._soak_slo_failed = False
        self._listener_registered = False
        self._warmup_done_logged = False
        self._cpu_skip_logged = False
        self._last_cpu_poll_at = 0.0
        self._last_cpu_cores: float | None = None
        self._last_hot_cores: float | None = None
        self._tracked_names = set(self.endpoint_slo_p95_ms) | set(self.endpoint_slo_p99_ms)

    def _on_request(self, request_type, name, response_time, response_length, exception=None, **_kwargs):
        # Only successful requests' latencies feed the SLO percentile check
        # -- a failed request's response_time isn't a real latency sample
        # (e.g. a connection reset returns almost instantly), and mixing it
        # in would let failures indirectly trigger/avoid a breach.
        if exception is not None:
            return
        if name not in self._tracked_names:
            return
        # Warmup traffic is discarded — do not accumulate samples that
        # would leak into the first ramp step's percentile check.
        if self.get_run_time() < self.warmup_seconds:
            return
        self._step_success_times.setdefault((name, request_type), []).append(response_time)

    def _percentile(self, name: str, method: str, percent: float) -> int | None:
        times = self._step_success_times.get((name, method))
        if not times:
            return None
        histogram = Counter(times)
        return calculate_response_time_percentile(histogram, len(times), percent)

    def _staff_api_cpu_cores(self, run_time: float) -> float | None:
        if not self.kube_namespace:
            return None
        if run_time - self._last_cpu_poll_at < self.cpu_poll_seconds and self._last_cpu_poll_at > 0:
            return self._last_hot_cores
        self._last_cpu_poll_at = run_time
        try:
            result = subprocess.run(
                ["kubectl", "top", "pod", "-n", self.kube_namespace, "--no-headers"],
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            if not self._cpu_skip_logged:
                print(f"[shape] CPU check skipped (kubectl top failed: {exc})")
                self._cpu_skip_logged = True
            STAFF_API_CPU["error"] = str(exc)
            self._last_cpu_cores = None
            self._last_hot_cores = None
            return None
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "non-zero exit").strip()
            STAFF_API_CPU["error"] = err
            if not self._cpu_skip_logged:
                print(f"[shape] CPU check skipped (kubectl top: {err})")
                self._cpu_skip_logged = True
            self._last_cpu_cores = None
            self._last_hot_cores = None
            return None
        pods: list[dict] = []
        needle = self.pod_grep
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            name, cpu_token = parts[0], parts[1]
            if needle not in name:
                continue
            if "locust" in name:
                continue
            try:
                cores = _parse_kubectl_cpu(cpu_token)
            except ValueError:
                continue
            prev = _POD_CPU_EXTREMA.get(name)
            min_c = cores if prev is None else min(prev[0], cores)
            max_c = cores if prev is None else max(prev[1], cores)
            _POD_CPU_EXTREMA[name] = (min_c, max_c)
            pods.append(
                {
                    "name": name,
                    "short_name": _short_pod_name(name),
                    "cores": cores,
                    "min_cores": min_c,
                    "max_cores": max_c,
                }
            )
        if not pods:
            STAFF_API_CPU["error"] = f"no pods matching {needle!r} in {self.kube_namespace}"
            if not self._cpu_skip_logged:
                print(
                    f"[shape] CPU check skipped (no pods matching "
                    f"{needle!r} in namespace {self.kube_namespace})"
                )
                self._cpu_skip_logged = True
            self._last_cpu_cores = None
            self._last_hot_cores = None
            return None
        pods.sort(key=lambda pod: pod["name"])
        total = sum(float(pod["cores"]) for pod in pods)
        hottest = max(float(pod["cores"]) for pod in pods)
        self._last_cpu_cores = total
        self._last_hot_cores = hottest
        self._publish_cpu(pods, total, hottest)
        return hottest

    def _publish_cpu(self, pods: list[dict], total: float, hottest: float) -> None:
        STAFF_API_CPU["pods"] = pods
        STAFF_API_CPU["hottest_cores"] = hottest
        STAFF_API_CPU["total_cores"] = total
        STAFF_API_CPU["limit_cores"] = self.cpu_breach_cores
        STAFF_API_CPU["error"] = None
        STAFF_API_CPU["polls"] = int(STAFF_API_CPU.get("polls") or 0) + 1
        per_pod = " ".join(
            f"{pod['short_name']}={pod['cores']:.2f}c" for pod in pods
        )
        print(
            f"[shape] farmer staff-api cpu pods={len(pods)} total={total:.2f}c | {per_pod}"
        )

    def _cpu_log_bit(self, hottest: float | None) -> str:
        if hottest is None:
            return ""
        pods = STAFF_API_CPU.get("pods") or []
        if not pods:
            return f" hottest={hottest:.2f}c"
        per_pod = " ".join(f"{pod['short_name']}={pod['cores']:.2f}c" for pod in pods)
        total = STAFF_API_CPU.get("total_cores")
        total_bit = f" total={total:.2f}c" if total is not None else ""
        return f" hottest={hottest:.2f}c{total_bit} | {per_pod}"

    def _print_latency_snapshot(self, label: str) -> bool:
        """Print p95/p99 vs SLO for every tracked endpoint with enough samples.

        Returns True if any endpoint with enough samples is over SLO.
        """
        breached = False
        printed = False
        for (name, method), times in sorted(self._step_success_times.items()):
            if name not in self._tracked_names:
                continue
            if len(times) < self.min_requests_for_check:
                continue
            printed = True
            p95 = self._percentile(name, method, 0.95)
            p99 = self._percentile(name, method, 0.99)
            slo95 = self.endpoint_slo_p95_ms.get(name)
            slo99 = self.endpoint_slo_p99_ms.get(name)
            bits = [f"{name} n={len(times)}"]
            if p95 is not None and slo95 is not None:
                bits.append(f"p95={p95}ms/{slo95}ms")
                if p95 > slo95:
                    breached = True
            if p99 is not None and slo99 is not None:
                bits.append(f"p99={p99}ms/{slo99}ms")
                if p99 > slo99:
                    breached = True
            print(f"[shape] {label}: {' '.join(bits)}")
        if not printed:
            print(
                f"[shape] {label}: not enough successes yet "
                f"(need ≥{self.min_requests_for_check}/endpoint)"
            )
        return breached

    def _slo_breached_this_window(self, user_count: int, entries) -> bool:
        for (name, method), entry in entries.items():
            if name not in self._tracked_names:
                continue
            start_requests, start_failures = self._step_start.get((name, method), (0, 0))
            requests_this_step = entry.num_requests - start_requests
            failures_this_step = entry.num_failures - start_failures
            success_times = self._step_success_times.get((name, method), [])
            if failures_this_step > 0 and requests_this_step >= self.min_requests_for_check:
                print(
                    f"[shape] {name} had {failures_this_step} failure(s) "
                    f"at {user_count} users (logged, not stopping)"
                )
            if len(success_times) < self.min_requests_for_check:
                continue

            slo95 = self.endpoint_slo_p95_ms.get(name)
            if slo95 is not None:
                p95 = self._percentile(name, method, 0.95)
                if p95 is not None and p95 > slo95:
                    print(
                        f"[shape] SLO breach: {name} p95={p95}ms > SLO-95={slo95}ms "
                        f"at {user_count} users (n={len(success_times)})"
                    )
                    return True
            slo99 = self.endpoint_slo_p99_ms.get(name)
            if slo99 is not None:
                p99 = self._percentile(name, method, 0.99)
                if p99 is not None and p99 > slo99:
                    print(
                        f"[shape] SLO breach: {name} p99={p99}ms > SLO-99={slo99}ms "
                        f"at {user_count} users (n={len(success_times)})"
                    )
                    return True
        return False

    def _begin_soak(self, user_count: int, run_time: float, reason: str):
        self._breach_user_count = user_count
        self._breach_run_time = run_time
        self._breach_reason = reason
        self._soak_started = False
        self._soak_last_report_at = None
        self._soak_slo_failed = False
        print(
            f"[shape] freezing ramp at {user_count} users ({reason}), "
            f"soaking {self.sustain_seconds}s and checking p95/p99"
        )

    def tick(self):
        if not self._listener_registered:
            # self.runner is only attached after __init__ (see
            # Environment._create_runner), so the listener is registered
            # lazily on first tick instead.
            self.runner.environment.events.request.add_listener(self._on_request)
            self._listener_registered = True

        run_time = self.get_run_time()
        entries = self.runner.stats.entries

        if self._breach_user_count is not None:
            self._staff_api_cpu_cores(run_time)
            if not self._soak_started:
                # Soak window is independent of the breaching step's samples.
                self._soak_started = True
                self._step_success_times = {}
                self._step_start = {key: (e.num_requests, e.num_failures) for key, e in entries.items()}
                self._soak_last_report_at = run_time
            soak_elapsed = run_time - self._breach_run_time
            if (
                self._soak_last_report_at is not None
                and run_time - self._soak_last_report_at >= self.step_seconds
            ):
                cpu = self._staff_api_cpu_cores(run_time)
                cpu_bit = self._cpu_log_bit(cpu)
                label = (
                    f"soak {int(soak_elapsed)}s/{self.sustain_seconds}s "
                    f"@ {self._breach_user_count} users{cpu_bit}"
                )
                if self._print_latency_snapshot(label):
                    self._soak_slo_failed = True
                    print("[shape] soak window is above SLO (continuing until 2min ends)")
                self._soak_last_report_at = run_time
            if soak_elapsed >= self.sustain_seconds:
                cpu = self._staff_api_cpu_cores(run_time)
                cpu_bit = self._cpu_log_bit(cpu)
                verdict = "FAIL" if self._soak_slo_failed else "PASS"
                print(
                    f"[shape] soak complete: {verdict} {self.sustain_seconds}s at "
                    f"{self._breach_user_count} users ({self._breach_reason}){cpu_bit}"
                )
                self._print_latency_snapshot("soak final")
                return None
            return (self._breach_user_count, self.step_users)

        # Warmup: fixed low concurrency, no SLO checks, samples discarded
        # (see _on_request). Matches documentation/staff-api/test-scenarios.md
        # §7 prep ("warm up 3–5 min … discard this window").
        if run_time < self.warmup_seconds:
            self._staff_api_cpu_cores(run_time)
            return (self.warmup_users, self.step_users)

        if not self._warmup_done_logged:
            self._warmup_done_logged = True
            # Reset step bookkeeping so the first ramp step starts clean.
            self._step = -1
            self._step_start = {}
            self._step_success_times = {}
            print(
                f"[shape] warmup complete ({self.warmup_seconds}s at "
                f"{self.warmup_users} users); starting ramp "
                f"(SLO check needs ≥{self.min_requests_for_check} successes/endpoint/step; "
                f"CPU freeze at {self.cpu_breach_cores} cores)"
            )

        # Ramp clock starts after warmup so step 0 is not mixed with cold traffic.
        ramp_time = run_time - self.warmup_seconds
        step = int(ramp_time // self.step_seconds)
        user_count = self.step_users * (step + 1)

        cpu = self._staff_api_cpu_cores(run_time)
        if cpu is not None and self.cpu_breach_cores > 0 and cpu >= self.cpu_breach_cores:
            hold = max(self.warmup_users, min(user_count, self.max_users))
            print(
                f"[shape] CPU breach: farmer staff-api hottest={cpu:.2f}c >= "
                f"{self.cpu_breach_cores}c at {user_count} users"
                f"{self._cpu_log_bit(cpu)}"
            )
            self._begin_soak(hold, run_time, f"CPU {cpu:.2f}c")
            return (hold, self.step_users)

        if step != self._step:
            # New step: snapshot every endpoint's cumulative failure counter
            # (for logging only) and clear the success-only response-time
            # samples so the SLO check below is scoped to this step's
            # traffic only.
            self._step = step
            self._step_start = {key: (e.num_requests, e.num_failures) for key, e in entries.items()}
            self._step_success_times = {}
        elif self._slo_breached_this_window(user_count, entries):
            last_good = max(self.warmup_users, user_count - self.step_users)
            self._begin_soak(last_good, run_time, f"SLO at {user_count} users; holding last-good")
            return (last_good, self.step_users)

        if user_count > self.max_users:
            print(f"[shape] stop: reached max_users={self.max_users} without breaching any SLO")
            return None

        return (user_count, self.step_users)
