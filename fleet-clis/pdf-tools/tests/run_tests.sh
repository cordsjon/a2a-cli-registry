#!/bin/sh
# Dependency-free test runner for pdf-tools (no bats — POSIX sh only).
# Usage: sh tests/run_tests.sh
set -u
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/.." && pwd)
PASS=0; FAIL=0

_ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
_bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }

# assert_eq <name> <expected> <actual>
assert_eq() { [ "$2" = "$3" ] && _ok "$1" || _bad "$1" "expected [$2] got [$3]"; }
# assert_ne_zero <name> <status>
assert_nonzero() { [ "$2" -ne 0 ] && _ok "$1" || _bad "$1" "expected non-zero exit, got 0"; }
assert_zero()    { [ "$2" -eq 0 ] && _ok "$1" || _bad "$1" "expected zero exit, got $2"; }
# assert_contains <name> <haystack> <needle>
assert_contains() { case "$2" in *"$3"*) _ok "$1";; *) _bad "$1" "[$2] does not contain [$3]";; esac; }
assert_file()    { [ -f "$2" ] && _ok "$1" || _bad "$1" "file missing: $2"; }
assert_nofile()  { [ ! -f "$2" ] && _ok "$1" || _bad "$1" "file should not exist: $2"; }

# ---- Task 1: ensure_backend ---------------------------------------------

echo "== backend.sh: ensure_backend =="

# fails fast + non-zero when docker absent (and backend not already healthy).
# Scrubbed PATH: only the unhealthy-curl shim + core bins; docker (in ~/.rd/bin)
# is genuinely off PATH, so `command -v docker` finds nothing.
out=$(PATH="$HERE/mocks/curl-only:/bin:/usr/bin" PDF_BACKEND_URL="http://127.0.0.1:59999" \
      PDF_BACKEND_TIMEOUT=2 sh -c ". '$ROOT/lib/backend.sh'; ensure_backend" 2>&1)
st=$?
assert_nonzero "ensure_backend: non-zero when docker absent" "$st"
assert_contains "ensure_backend: message names Docker" "$out" "Docker"

# returns 0 when the status endpoint is already healthy (curl shim => 200)
out=$(PATH="$HERE/mocks/healthy:$PATH" PDF_BACKEND_URL="http://127.0.0.1:59999" \
      PDF_BACKEND_TIMEOUT=2 sh -c ". '$ROOT/lib/backend.sh'; ensure_backend" 2>&1)
st=$?
assert_zero "ensure_backend: zero when already healthy" "$st"

# ---- Task 2: verb dispatch + atomic output + split ----------------------

echo ""
echo "== pdf-tools: dispatch + split =="

CLI="$ROOT/pdf-tools"
FIX="$HERE/fixtures/sample.pdf"

# split posts to the endpoint and writes output atomically (mock curl => healthy + writes bytes)
rm -f /tmp/pdft_out.pdf /tmp/pdft_out.pdf.tmp
out=$(PATH="$HERE/mocks/split-ok:/bin:/usr/bin" \
      "$CLI" split "$FIX" --pages 1-3 -o /tmp/pdft_out.pdf 2>&1)
st=$?
assert_zero      "split: exit 0 on success" "$st"
assert_file      "split: output written" "/tmp/pdft_out.pdf"
assert_nofile    "split: tmp cleaned up"  "/tmp/pdft_out.pdf.tmp"
assert_contains  "split: prints output path" "$out" "/tmp/pdft_out.pdf"

# no output file remains when curl fails (5xx-equivalent)
rm -f /tmp/pdft_fail.pdf /tmp/pdft_fail.pdf.tmp
out=$(PATH="$HERE/mocks/split-fail:/bin:/usr/bin" \
      "$CLI" split "$FIX" --pages 1-3 -o /tmp/pdft_fail.pdf 2>&1)
st=$?
assert_nonzero   "split: non-zero when backend errors" "$st"
assert_nofile    "split: no partial output on failure" "/tmp/pdft_fail.pdf"
assert_nofile    "split: tmp removed on failure"        "/tmp/pdft_fail.pdf.tmp"

# usage/dispatch: unknown verb => non-zero + usage
out=$("$CLI" bogus 2>&1); st=$?
assert_nonzero   "dispatch: unknown verb non-zero" "$st"
assert_contains  "dispatch: usage names split"     "$out" "split"

# ---- form-fill: mocked (always runs) ------------------------------------

echo ""
echo "== pdf-tools: form-fill (mocked) =="

FORM_FIX="$HERE/fixtures/form_sample.pdf"
printf '{"fullname":"Jonas Cords"}' > /tmp/pdft_ffdata.json

# form-fill requires --data to be an existing JSON file (else usage/exit 2)
out=$("$CLI" form-fill "$FORM_FIX" -o /tmp/pdft_ff.pdf 2>&1); st=$?
assert_nonzero  "form-fill: missing --data => non-zero" "$st"

rm -f /tmp/pdft_ff.pdf /tmp/pdft_ff.pdf.tmp
out=$(PATH="$HERE/mocks/split-ok:/bin:/usr/bin" \
      "$CLI" form-fill "$FORM_FIX" --data /tmp/pdft_ffdata.json -o /tmp/pdft_ff.pdf 2>&1)
st=$?
assert_zero     "form-fill: exit 0 on success" "$st"
assert_file     "form-fill: output written"    "/tmp/pdft_ff.pdf"
assert_nofile   "form-fill: tmp cleaned up"    "/tmp/pdft_ff.pdf.tmp"

# ---- form-fill: LIVE round-trip (auto-skips if backend down) ------------

echo ""
echo "== pdf-tools: form-fill (live round-trip) =="

LIVE_URL="${PDF_BACKEND_URL:-http://localhost:9141}"
if curl -fsS "$LIVE_URL/api/v1/info/status" >/dev/null 2>&1; then
  rm -f /tmp/pdft_fflive.pdf
  "$CLI" form-fill "$FORM_FIX" --data /tmp/pdft_ffdata.json -o /tmp/pdft_fflive.pdf >/dev/null 2>&1
  st=$?
  assert_zero "form-fill live: exit 0" "$st"
  # read the field value back out of the produced PDF via Stirling
  val=$(curl -fsS -X POST "$LIVE_URL/api/v1/form/fields" -F "file=@/tmp/pdft_fflive.pdf" 2>/dev/null \
        | python3 -c "import json,sys; print(json.load(sys.stdin)['fields'][0]['value'])" 2>/dev/null)
  assert_eq "form-fill live: value landed in output" "Jonas Cords" "$val"
else
  echo "  skip live form-fill — backend not reachable at $LIVE_URL"
fi

echo ""
echo "results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
