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

echo ""
echo "results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
