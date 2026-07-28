#!/usr/bin/env bash
# remediate-run — thin wrapper around `a2a-cli-registry remediate`.
#
# Replaces the hand-run form
#   python3 -c 'from core.cli.main import main; main(["remediate", ...])'
# which was repeated once per mode (dry-run copy / live / triage copy /
# triage live) only because the console-script entrypoint needs PATH setup.
#
# What it adds over the raw command:
#   * runs the CLI as `python3 -m core.cli.main` from the repo root, so no
#     installed console script and no PATH setup is required;
#   * copies the DB to a timestamped working copy by default, so a live or
#     --apply-safe run can never mutate the canonical registry.db;
#   * with --in-place, backs the DB up first and then mutates it.
#
# It deliberately does NOT reimplement locking: core/cli/main.py already holds
# the sidecar file lock for every mutating remediate path.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# The repo venv holds the runtime deps (portalocker, sqlmodel, ...). Prefer it
# over a bare python3, which is what forced the PATH fiddling in the first
# place. $A2A_PYTHON overrides for a venv kept outside the repo.
if [ -n "${A2A_PYTHON:-}" ]; then
  PYTHON="$A2A_PYTHON"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  PYTHON="python3"
fi

DB="registry.db"
OUT=""
WORK_DIR=".remediate-runs"
LIVE=0
IN_PLACE=0
APPLY_SAFE=0
MAX_LLM_CALLS=0

usage() {
  cat <<'EOF'
Usage: bin/remediate-run.sh [options]

  --db PATH             source registry DB (default: registry.db)
  --out PATH            proposals output path (default: <workdir>/<stamp>-proposals.json)
  --work-dir PATH       where copies/backups land (default: .remediate-runs)
  --live                actually file Paperclip issues (default: dry-run)
  --triage N            Hermes diagnosis batch cap (--max-llm-calls N; default 0 = skip)
  --apply-safe          arm SafeFixer (wheel-only install + isolated re-probe)
  --in-place            run against --db itself; a backup is taken first
  -h, --help            show this help

By default the run happens against a timestamped COPY of --db, so the
canonical registry.db is never mutated.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --db)        DB="$2"; shift 2 ;;
    --out)       OUT="$2"; shift 2 ;;
    --work-dir)  WORK_DIR="$2"; shift 2 ;;
    --live)      LIVE=1; shift ;;
    --triage)    MAX_LLM_CALLS="$2"; shift 2 ;;
    --apply-safe) APPLY_SAFE=1; shift ;;
    --in-place)  IN_PLACE=1; shift ;;
    -h|--help)   usage; exit 0 ;;
    *) echo "remediate-run: unknown argument: $1" >&2; usage >&2; exit 64 ;;
  esac
done

cd "$REPO_ROOT"

if [ ! -f "$DB" ]; then
  echo "remediate-run: no such DB: $DB" >&2
  exit 66
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$WORK_DIR"

if [ "$IN_PLACE" -eq 1 ]; then
  BACKUP="$WORK_DIR/$STAMP-registry.db.bak"
  cp "$DB" "$BACKUP"
  TARGET_DB="$DB"
  echo "remediate-run: in-place on $DB (backup: $BACKUP)" >&2
else
  TARGET_DB="$WORK_DIR/$STAMP-registry.db"
  cp "$DB" "$TARGET_DB"
  echo "remediate-run: working copy: $TARGET_DB" >&2
fi

[ -n "$OUT" ] || OUT="$WORK_DIR/$STAMP-proposals.json"

ARGS=(remediate --db "$TARGET_DB" --out "$OUT" --max-llm-calls "$MAX_LLM_CALLS")
[ "$LIVE" -eq 1 ] && ARGS+=(--file)
[ "$APPLY_SAFE" -eq 1 ] && ARGS+=(--apply-safe)

echo "remediate-run: $PYTHON -m core.cli.main ${ARGS[*]}" >&2
exec "$PYTHON" -m core.cli.main "${ARGS[@]}"
