#!/bin/sh
# Reproduce the pdf-tools registry state on this machine — idempotent.
# Reconstructs what git does NOT carry: the two feed entries (demo/ is
# gitignored) and the registry.db not_standalone column (registry.db is
# gitignored). Safe to re-run; each step is a no-op if already applied.
#
#   sh fleet-clis/pdf-tools/seed/apply.sh [--config demo/config.toml]
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(CDPATH= cd -- "$HERE/../../.." && pwd)          # fleet-clis/pdf-tools/seed -> repo root
BIN="$HERE/../pdf-tools"                                # the CLI binary the entries point at
BIN=$(CDPATH= cd -- "$(dirname -- "$BIN")" && pwd)/pdf-tools
SEED="$HERE/feed-entries.json"
CONFIG="${2:-demo/config.toml}"

cd "$REPO"

# 0. locate the live feed the config consumes (cli_audit_path in the TOML)
FEED=$(grep -E '^cli_audit_path' "$CONFIG" 2>/dev/null | sed 's/.*=[[:space:]]*"\(.*\)".*/\1/')
[ -n "$FEED" ] || { echo "apply: cannot read cli_audit_path from $CONFIG" >&2; exit 1; }
echo "apply: feed=$FEED  binary=$BIN"

# 1. migration — ensure registry.db has the not_standalone column (models expect it)
DB=registry.db
if [ -f "$DB" ]; then
  if ! sqlite3 "$DB" "PRAGMA table_info(cli);" | grep -q '|not_standalone|'; then
    cp "$DB" "$DB.bak-$(date +%Y%m%d%H%M%S 2>/dev/null || echo pretools)"
    sqlite3 "$DB" "ALTER TABLE cli ADD COLUMN not_standalone BOOLEAN NOT NULL DEFAULT 0;"
    echo "apply: added not_standalone column to $DB (backed up)"
  else
    echo "apply: not_standalone column already present"
  fi
fi

# 1b. portmgr allocation — ensure the stirling-pdf service has a registered
#     port (idempotent: /allocate returns the existing port if already assigned).
if curl -fsS http://localhost:9000/allocations >/dev/null 2>&1; then
  PORT=$(curl -fsS -X POST http://localhost:9000/allocate \
    -H 'Content-Type: application/json' \
    -d '{"id":"stirling-pdf","title":"Stirling PDF","type":"service","health_endpoint":"/api/v1/info/status","subtitle":"Local PDF manipulation backend (pdf-tools CLI)"}' \
    2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('port',''))" 2>/dev/null)
  [ -n "$PORT" ] && echo "apply: portmgr port for stirling-pdf = $PORT"
  # keep backend.sh in sync if portmgr issued a different port than the default
  if [ -n "$PORT" ] && [ "$PORT" != "9141" ]; then
    echo "apply: NOTE portmgr issued $PORT (not the default 9141) — set PDF_BACKEND_PORT=$PORT / PDF_BACKEND_URL=http://localhost:$PORT" >&2
  fi
else
  echo "apply: portmgr not reachable on :9000 — skipping port registration (backend.sh defaults to 9141)" >&2
fi

# 2. upsert the entries into the live feed — replace-by-slug, not skip-if-
#    present, so edits to an existing slug's fields (e.g. new intent_tags)
#    actually land on re-apply instead of being silently ignored (KP:
#    "idempotent" only meant safe-to-rerun here, not sync-on-change).
python3 - "$SEED" "$FEED" "$BIN" <<'PY'
import json, sys, os, tempfile
seed_path, feed_path, binpath = sys.argv[1], sys.argv[2], sys.argv[3]
seed = json.load(open(seed_path))
feed = json.load(open(feed_path)) if os.path.exists(feed_path) else {"schema_version":1,"run_id":"seeded","clis":[]}
clis = feed.setdefault("clis", [])
by_slug = {c.get("slug"): i for i, c in enumerate(clis)}
added = 0
updated = 0
for e in seed["entries"]:
    e = dict(e); e["path"] = binpath           # resolve the placeholder path
    if e["slug"] in by_slug:
        if clis[by_slug[e["slug"]]] != e:
            clis[by_slug[e["slug"]]] = e
            updated += 1
    else:
        clis.append(e)
        by_slug[e["slug"]] = len(clis) - 1
        added += 1
# atomic write
d = os.path.dirname(feed_path) or "."
fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
with os.fdopen(fd, "w") as fh:
    json.dump(feed, fh, indent=2)
os.replace(tmp, feed_path)
unchanged = len(seed["entries"]) - added - updated
print(f"apply: feed upsert — {added} added, {updated} updated, {unchanged} unchanged")
PY

# 3. populate + probe (use the repo venv — needs portalocker etc.)
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
echo "apply: populating registry..."
"$PY" -m core.cli.main populate --config "$CONFIG" 2>&1 | tail -3

echo "apply: done. Verify with: $PY -c \"from core.store.db import init_db,get_session; from core.catalog.queries import search_clis; e=init_db('registry.db'); s=get_session(e).__enter__(); print([h['slug'] for h in search_clis(s,'pdf') if 'pdf-tools' in h['slug']])\""
