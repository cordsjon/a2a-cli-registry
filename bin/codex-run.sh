#!/usr/bin/env bash
# codex-run — run `codex exec` headless and ALWAYS end up with the model's text.
#
# Replaces the hand-assembled scaffold that was rebuilt once per review pass:
#   codex exec --skip-git-repo-check "$(cat prompt.md)" </dev/null > out.txt
#   ... out.txt is empty, exit 0 ...
#   ls -t ~/.codex/sessions/2026/*/*/rollout-*.jsonl | head -1
#   python3 -c 'grep the task_complete payload out of the jsonl'
#
# The failure it works around (codex-cli 0.145.0, verified 2026-07-26): a run
# can complete with exit 0 and emit NOTHING on stdout and nothing into the
# `-o` file, even though the model produced a full answer. The answer is only
# in the session rollout, as `payload.last_agent_message` of the
# `task_complete` event. Never declare a codex run empty without checking there
# (HANDOVER-ard-fleet-discovery-2026-07-26-0930.md, landmine 4).
#
# So this wrapper does three things the raw command does not:
#   * always passes --skip-git-repo-check and `-o <file>`, and tees stdout, so
#     there is a scratch file to read even on the happy path;
#   * on an empty result, recovers last_agent_message from the newest rollout
#     JSONL written after the run started (never an older, unrelated session);
#   * exposes that recovery on its own as `--last-message`, for runs that were
#     started some other way.
#
# Prompts are passed as a FILE, not as an argv string: the failing runs burned
# 53-56K tokens from a 2KB prompt because codex walked the repo tree, and a
# file keeps the prompt out of shell history and off the argv length limit.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

CODEX="${CODEX_BIN:-codex}"
SESSIONS_DIR="${CODEX_SESSIONS_DIR:-$HOME/.codex/sessions}"

PROMPT_FILE=""
OUT=""
WORK_DIR=".codex-runs"
LAST_MESSAGE_ONLY=0
SESSION_FILE=""

usage() {
  cat <<'EOF'
Usage: bin/codex-run.sh --prompt-file PATH [options] [-- extra codex args]
       bin/codex-run.sh --last-message [--session PATH]

  --prompt-file PATH    file holding the prompt (required unless --last-message)
  --out PATH            where the model text lands (default: <workdir>/<stamp>.md)
  --work-dir PATH       scratch dir for output + raw stdout (default: .codex-runs)
  --last-message        do not run codex; print the last agent message of the
                        newest session rollout and exit
  --session PATH        with --last-message, read this rollout JSONL instead of
                        the newest one
  -h, --help            show this help

Anything after `--` is appended to the codex exec command verbatim
(e.g. -- --model gpt-5-codex).

Exit codes: 0 ok, 64 usage, 65 codex ran but produced no recoverable text,
66 missing input file, 69 codex binary not found.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --prompt-file)  PROMPT_FILE="$2"; shift 2 ;;
    --out)          OUT="$2"; shift 2 ;;
    --work-dir)     WORK_DIR="$2"; shift 2 ;;
    --last-message) LAST_MESSAGE_ONLY=1; shift ;;
    --session)      SESSION_FILE="$2"; shift 2 ;;
    -h|--help)      usage; exit 0 ;;
    --)             shift; break ;;
    *) echo "codex-run: unknown argument: $1" >&2; usage >&2; exit 64 ;;
  esac
done
EXTRA_ARGS=("$@")

# Pull payload.last_agent_message out of a rollout JSONL. Stdlib only — this
# has to work with a bare python3, not just the repo venv.
extract_last_message() {
  python3 - "$1" <<'PY'
import json, sys

msg = None
with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line or "last_agent_message" not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = obj.get("payload") or {}
        if payload.get("type") == "task_complete" and payload.get("last_agent_message"):
            msg = payload["last_agent_message"]

if msg is None:
    sys.exit(1)
sys.stdout.write(msg if msg.endswith("\n") else msg + "\n")
PY
}

# Newest rollout JSONL, optionally restricted to files modified at or after a
# reference file. Without the reference we would happily return yesterday's run.
#
# Sorted lexically, not by mtime: rollout paths are ISO-timestamped
# (<year>/<month>/<day>/rollout-2026-07-28T20-33-10-<uuid>.jsonl), so
# `sort -r | head -1` is newest-first and avoids `xargs ls -t`, which
# mis-sorts as soon as xargs splits the list across several `ls` calls.
#
# The `head -1` needs pipefail off: head exits after one line, upstream find
# takes SIGPIPE, and under `set -euo pipefail` that aborts the script with no
# message at all.
newest_rollout() {
  local newer_than="${1:-}"
  local -a find_args=("$SESSIONS_DIR" -name 'rollout-*.jsonl' -type f)
  [ -n "$newer_than" ] && find_args+=(-newer "$newer_than")
  ( set +o pipefail; find "${find_args[@]}" -print 2>/dev/null | sort -r | head -1 ) || true
}

if [ "$LAST_MESSAGE_ONLY" -eq 1 ]; then
  [ -n "$SESSION_FILE" ] || SESSION_FILE="$(newest_rollout)"
  if [ -z "$SESSION_FILE" ] || [ ! -f "$SESSION_FILE" ]; then
    echo "codex-run: no session rollout found under $SESSIONS_DIR" >&2
    exit 66
  fi
  echo "codex-run: session $SESSION_FILE" >&2
  if ! extract_last_message "$SESSION_FILE"; then
    echo "codex-run: no task_complete/last_agent_message in $SESSION_FILE" >&2
    exit 65
  fi
  exit 0
fi

if [ -z "$PROMPT_FILE" ]; then
  echo "codex-run: --prompt-file is required (or use --last-message)" >&2
  usage >&2
  exit 64
fi
if [ ! -f "$PROMPT_FILE" ]; then
  echo "codex-run: no such prompt file: $PROMPT_FILE" >&2
  exit 66
fi
if ! command -v "$CODEX" >/dev/null 2>&1; then
  echo "codex-run: codex binary not found: $CODEX (set \$CODEX_BIN)" >&2
  exit 69
fi

cd "$REPO_ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$WORK_DIR"
[ -n "$OUT" ] || OUT="$WORK_DIR/$STAMP.md"
STDOUT_LOG="$WORK_DIR/$STAMP.stdout"

# Marker file: anything codex writes lands strictly after this mtime, so the
# rollout search below can never pick up an unrelated earlier session.
MARKER="$WORK_DIR/.$STAMP.marker"
: > "$MARKER"

echo "codex-run: $CODEX exec --skip-git-repo-check -o $OUT (prompt: $PROMPT_FILE)" >&2
set +e
# ${ARR[@]+"${ARR[@]}"}, not "${ARR[@]}": macOS ships bash 3.2, where expanding
# an EMPTY array under `set -u` is an unbound-variable error. Since no extra
# codex args is the default invocation, the plain form aborted the run here and
# then reported the resulting empty -o file as codex's silent-empty bug — i.e.
# codex was never actually called.
"$CODEX" exec --skip-git-repo-check -o "$OUT" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} \
  "$(cat "$PROMPT_FILE")" </dev/null 2>&1 | tee "$STDOUT_LOG"
CODEX_RC="${PIPESTATUS[0]}"
set -e

if [ -s "$OUT" ]; then
  echo "codex-run: output in $OUT (rc=$CODEX_RC)" >&2
  rm -f "$MARKER"
  exit "$CODEX_RC"
fi

# Silent-empty case. Recover from the rollout instead of reporting a false empty.
echo "codex-run: -o file empty (rc=$CODEX_RC) — recovering from session rollout" >&2
ROLLOUT="$(newest_rollout "$MARKER")"
rm -f "$MARKER"

if [ -z "$ROLLOUT" ]; then
  echo "codex-run: no rollout written since the run started; raw stdout: $STDOUT_LOG" >&2
  exit 65
fi

if extract_last_message "$ROLLOUT" > "$OUT"; then
  echo "codex-run: recovered from $ROLLOUT -> $OUT" >&2
  cat "$OUT"
  exit "$CODEX_RC"
fi

echo "codex-run: $ROLLOUT has no last_agent_message; raw stdout: $STDOUT_LOG" >&2
exit 65
