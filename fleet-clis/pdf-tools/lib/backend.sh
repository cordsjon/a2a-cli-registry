# backend.sh — self-managed Stirling PDF backend for pdf-tools (POSIX sh).
# Sourced by the pdf-tools CLI. Never `exit`s on the happy path; callers
# rely on ensure_backend's return code.
#
# Port 9141 is portmgr-allocated (service stirling-pdf). Override via
# PDF_BACKEND_URL for tests. See docs/plans/2026-07-13-pdf-tools-cli.md.

: "${PDF_BACKEND_URL:=http://localhost:9141}"
: "${PDF_BACKEND_TIMEOUT:=60}"
: "${PDF_IMAGE:=stirlingtools/stirling-pdf:latest}"
: "${PDF_CONTAINER:=stirling-pdf}"
: "${PDF_BACKEND_PORT:=9141}"

_die() { echo "pdf-tools: $1" >&2; exit "${2:-1}"; }

_backend_healthy() {
  curl -fsS "$PDF_BACKEND_URL/api/v1/info/status" >/dev/null 2>&1
}

# ensure_backend: guarantee Stirling is reachable, starting it on demand.
# Returns 0 when healthy; _die (non-zero) on any unrecoverable condition.
# Bounded wait — never hangs (codex-stdin-hang lesson).
ensure_backend() {
  _backend_healthy && return 0

  command -v docker >/dev/null 2>&1 \
    || _die "Docker not found on PATH. Install Docker (or Rancher Desktop), then retry." 3

  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$PDF_CONTAINER"; then
    # Reuse a stopped container of the same name if present; else create.
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$PDF_CONTAINER"; then
      docker start "$PDF_CONTAINER" >/dev/null 2>&1 \
        || _die "failed to start existing container '$PDF_CONTAINER'" 4
    else
      docker run -d --name "$PDF_CONTAINER" --restart unless-stopped \
        -p "$PDF_BACKEND_PORT:$PDF_BACKEND_PORT" -e "SERVER_PORT=$PDF_BACKEND_PORT" \
        "$PDF_IMAGE" >/dev/null 2>&1 \
        || _die "failed to launch Stirling container ($PDF_IMAGE)" 4
    fi
  fi

  waited=0
  while [ "$waited" -lt "$PDF_BACKEND_TIMEOUT" ]; do
    _backend_healthy && return 0
    sleep 2
    waited=$((waited + 2))
  done

  _die "Stirling not healthy after ${PDF_BACKEND_TIMEOUT}s. Last logs:
$(docker logs --tail 20 "$PDF_CONTAINER" 2>&1)" 5
}
