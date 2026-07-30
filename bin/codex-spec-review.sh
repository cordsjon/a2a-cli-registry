#!/usr/bin/env bash
# codex-spec-review — ground a spec with codex in ONE invocation.
#
# Replaces the 4 hand-assembled steps that were rebuilt per review pass:
#   1. hand-write a review prompt naming the spec and the prior findings
#   2. codex exec ... </dev/null with the sentinel/background scaffold
#   3. dig the model text out of the session rollout when stdout came back empty
#   4. eyeball the answer for a plan-ready decision and re-type the findings
#
# Steps 2+3 already live in bin/codex-run.sh; this wrapper adds 1 and 4 and
# delegates the rest, so there is exactly one copy of the silent-empty recovery.
#
# The spec text is INLINED into the prompt, not referenced by path, and the
# prompt forbids repo exploration. That is the whole point: the runs that burned
# 53-56K tokens from a 2KB prompt did so because codex walked the repo tree
# looking for context it was never given (codex-cli 0.145.0, verified
# 2026-07-26). Handing it the path instead of the text reproduces that burn.
#
# Output contract asked of the model, and parsed back here:
#   FINDING: <one line per blocking gap>
#   VERDICT: PLAN-READY | NOT-PLAN-READY
#
# Exit codes: 0 PLAN-READY, 1 NOT-PLAN-READY, 64 usage, 65 codex produced no
# recoverable verdict, 66 missing input file.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_RUN="$REPO_ROOT/bin/codex-run.sh"

SPEC=""
FINDINGS=""
OUT=""
WORK_DIR=".codex-runs"
PARSE_FILE=""

usage() {
  cat <<'EOF'
Usage: bin/codex-spec-review.sh --spec PATH [options] [-- extra codex args]
       bin/codex-spec-review.sh --parse PATH

  --spec PATH        the spec to ground (required unless --parse)
  --findings PATH    prior findings the model must re-check, one per line
  --out PATH         where the raw model text lands (default: <workdir>/<stamp>-review.md)
  --work-dir PATH    scratch dir for prompt + raw output (default: .codex-runs)
  --parse PATH       do not run codex; parse an existing review file and exit
                     with the verdict's exit code
  -h, --help         show this help

Anything after `--` is forwarded to codex-run.sh verbatim
(e.g. -- -- --model gpt-5-codex).
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --spec)      SPEC="$2"; shift 2 ;;
    --findings)  FINDINGS="$2"; shift 2 ;;
    --out)       OUT="$2"; shift 2 ;;
    --work-dir)  WORK_DIR="$2"; shift 2 ;;
    --parse)     PARSE_FILE="$2"; shift 2 ;;
    -h|--help)   usage; exit 0 ;;
    --)          shift; break ;;
    *) echo "codex-spec-review: unknown argument: $1" >&2; usage >&2; exit 64 ;;
  esac
done
EXTRA_ARGS=("$@")

# The verdict token. NOT-PLAN-READY is tested FIRST because PLAN-READY is a
# substring of it — matching the positive first would report every rejected spec
# as approved, which is worse than having no gate at all.
parse_verdict() {
  local line
  line="$( (set +o pipefail
            grep -o -E 'VERDICT:[[:space:]]*[*_ ]*(NOT-)?PLAN-READY' "$1" \
              2>/dev/null | tail -1) || true )"
  case "$line" in
    *NOT-PLAN-READY) printf 'NOT-PLAN-READY\n' ;;
    *PLAN-READY)     printf 'PLAN-READY\n' ;;
    *) return 1 ;;
  esac
}

# FINDING: lines, tolerating the markdown the model wraps them in
# ("- **FINDING:** ..." / "* FINDING: ...").
parse_findings() {
  sed -n -E 's/^[[:space:]]*[-*#>]*[[:space:]]*[*_]*FINDING:[*_]*[[:space:]]*//p' "$1"
}

# Print findings + verdict and return the verdict's exit code. Shared by the
# --parse path and the post-run path so both report identically.
report() {
  local file="$1" verdict
  if ! verdict="$(parse_verdict "$file")"; then
    echo "codex-spec-review: no VERDICT line in $file" >&2
    return 65
  fi
  local n=0
  while IFS= read -r finding; do
    [ -n "$finding" ] || continue
    n=$((n + 1))
    printf 'FINDING %d: %s\n' "$n" "$finding"
  done < <(parse_findings "$file")
  printf 'VERDICT: %s (findings=%d)\n' "$verdict" "$n"
  [ "$verdict" = "PLAN-READY" ] && return 0
  return 1
}

if [ -n "$PARSE_FILE" ]; then
  if [ ! -f "$PARSE_FILE" ]; then
    echo "codex-spec-review: no such review file: $PARSE_FILE" >&2
    exit 66
  fi
  # `report` returns 1 for NOT-PLAN-READY, which is a verdict and not an error,
  # so it must not trip `set -e`.
  rc=0; report "$PARSE_FILE" || rc=$?
  exit "$rc"
fi

if [ -z "$SPEC" ]; then
  echo "codex-spec-review: --spec is required (or use --parse)" >&2
  usage >&2
  exit 64
fi
if [ ! -f "$SPEC" ]; then
  echo "codex-spec-review: no such spec: $SPEC" >&2
  exit 66
fi
if [ -n "$FINDINGS" ] && [ ! -f "$FINDINGS" ]; then
  echo "codex-spec-review: no such findings file: $FINDINGS" >&2
  exit 66
fi

cd "$REPO_ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$WORK_DIR"
[ -n "$OUT" ] || OUT="$WORK_DIR/$STAMP-review.md"
PROMPT="$WORK_DIR/$STAMP-review.prompt"

{
  cat <<'EOF'
You are reviewing a specification for PLAN-READINESS. Decide whether an
engineer could implement it without further clarification.

Work ONLY from the spec text below and, if present, the prior findings. Do NOT
read, list, search or explore any files in this repository — everything you need
is inline. Exploring the tree wastes the entire budget and is not permitted.

Judge the spec on: unambiguous acceptance criteria; named interfaces and data
shapes; stated error/edge behaviour; testability; and any internal
contradiction.

Answer in this exact shape, and nothing else:
  one FINDING: line per blocking gap (omit entirely if there are none)
  a final line reading exactly `VERDICT: PLAN-READY` or `VERDICT: NOT-PLAN-READY`
`PLAN-READY` means zero blocking gaps.
EOF
  if [ -n "$FINDINGS" ]; then
    printf '\n--- PRIOR FINDINGS (state for each whether it is now resolved) ---\n'
    cat "$FINDINGS"
  fi
  printf '\n--- SPEC: %s ---\n' "$SPEC"
  cat "$SPEC"
} > "$PROMPT"

echo "codex-spec-review: prompt $PROMPT ($(wc -c < "$PROMPT" | tr -d ' ') bytes)" >&2

# codex-run.sh owns </dev/null, -o, the tee and the rollout recovery. A codex
# failure there is fatal here: an empty review must never parse as a verdict.
# ${ARR[@]+...}: bash 3.2 (macOS default) errors on expanding an empty array
# under `set -u`, and no extra args is the default invocation.
"$CODEX_RUN" --prompt-file "$PROMPT" --out "$OUT" --work-dir "$WORK_DIR" \
  ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} >/dev/null

echo "codex-spec-review: raw review $OUT" >&2
rc=0; report "$OUT" || rc=$?
exit "$rc"
