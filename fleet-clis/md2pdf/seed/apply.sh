#!/bin/sh
# Reproduce the md2pdf registry state on this machine — idempotent.
# Reconstructs what git does NOT carry: the feed entry (demo/ is gitignored)
# and the live registry DB row + its capability row. Safe to re-run.
#
#   sh fleet-clis/md2pdf/seed/apply.sh [--db ~/.hermes/cli-registry.db] [--config demo/config.toml]
#
# WHY NOT `populate` (the step pdf-tools/ and funroadtrip/ apply.sh end with):
# populate() deletes every DB row whose slug is absent from the feed
# (core/populate.py, `to_remove = existing - incoming`). Measured 2026-10-30
# on the live DB: 641 rows, feed demo/cli-audit/latest.json (2026-08-03) has
# 479; 165 rows (134 manual-register such as bf-batch, 24 external:nosignups,
# 6 cli_audit, 1 manual_spec3) would be deleted, and 165/641 = 25.7 % is
# under the 30 % mass-removal breaker. So this script takes the route
# bf-batch took (source_class manual-register): register_cli.py upserts the
# cli row (lang=python -> launch_spec kind python_module + script_path, the
# only kind hermes-adapter dispatches), and the capability row is upserted
# with provenance='manual', which populate() preserves (PRESERVED_PROVENANCE).
# The feed entry is still written so a future populate from a refreshed feed
# re-creates the same row instead of removing it.
#
# Prerequisites: pandoc + weasyprint on PATH (brew install pandoc weasyprint);
# ~/projects/00_Governance/scripts/register_cli.py; sqlite3.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(CDPATH= cd -- "$HERE/../../.." && pwd)          # fleet-clis/md2pdf/seed -> registry repo root
SEED="$HERE/feed-entries.json"
BIN=$(CDPATH= cd -- "$HERE/.." && pwd)/md2pdf.py
[ -f "$BIN" ] || { echo "apply: no wrapper at $BIN" >&2; exit 1; }

DB="${REGISTRY_DB:-$HOME/.hermes/cli-registry.db}"
CONFIG="demo/config.toml"
while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    *) echo "apply: unknown argument $1" >&2; exit 2 ;;
  esac
done
REGISTER="${REGISTER_CLI:-$HOME/projects/00_Governance/scripts/register_cli.py}"
[ -f "$REGISTER" ] || { echo "apply: register_cli.py not found at $REGISTER (set REGISTER_CLI)" >&2; exit 1; }
[ -f "$DB" ] || { echo "apply: registry DB not found at $DB (set REGISTRY_DB or --db)" >&2; exit 1; }

cd "$REPO"

# 0. locate the live feed the config consumes (cli_audit_path in the TOML)
FEED=$(grep -E '^cli_audit_path' "$CONFIG" 2>/dev/null | sed 's/.*=[[:space:]]*"\(.*\)".*/\1/')
[ -n "$FEED" ] || { echo "apply: cannot read cli_audit_path from $CONFIG" >&2; exit 1; }
echo "apply: feed=$FEED  db=$DB  wrapper=$BIN"

command -v pandoc >/dev/null 2>&1 || echo "apply: WARNING pandoc not on PATH — the entry registers but conversions will fail" >&2
command -v weasyprint >/dev/null 2>&1 || echo "apply: WARNING weasyprint not on PATH — the entry registers but conversions will fail" >&2

# 1. upsert the entry into the live feed — replace-by-slug (same idempotency
#    contract as pdf-tools/seed/apply.sh). Also emits the entry's fields on
#    stdout for step 2/3 (one JSON line), so the seed file stays the single
#    source of truth for description and capability.
ENTRY=$(python3 - "$SEED" "$FEED" "$BIN" <<'PY'
import json, sys, os, tempfile
seed_path, feed_path, binpath = sys.argv[1], sys.argv[2], sys.argv[3]
seed = json.load(open(seed_path))
feed = json.load(open(feed_path)) if os.path.exists(feed_path) else {"schema_version":1,"run_id":"seeded","clis":[]}
clis = feed.setdefault("clis", [])
by_slug = {c.get("slug"): i for i, c in enumerate(clis)}
added = updated = 0
entry = None
for e in seed["entries"]:
    e = dict(e); e["path"] = binpath           # resolve the placeholder path
    entry = e
    if e["slug"] in by_slug:
        if clis[by_slug[e["slug"]]] != e:
            clis[by_slug[e["slug"]]] = e; updated += 1
    else:
        clis.append(e); by_slug[e["slug"]] = len(clis) - 1; added += 1
d = os.path.dirname(feed_path) or "."
os.makedirs(d, exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
with os.fdopen(fd, "w") as fh:
    json.dump(feed, fh, indent=2)
os.replace(tmp, feed_path)
print(f"apply: feed upsert — {added} added, {updated} updated, {len(seed['entries'])-added-updated} unchanged", file=sys.stderr)
print(json.dumps(entry))
PY
)
SLUG=$(printf '%s' "$ENTRY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["slug"])')
DESC=$(printf '%s' "$ENTRY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["description"])')

# 2. health: the registry probe is `python <path> --help`; record what it says.
if python3 "$BIN" --help >/dev/null 2>&1; then HEALTH=healthy; else HEALTH=unhealthy; fi

# 3. cli row (manual-register route, like bf-batch). register_cli.py is a
#    keyed upsert: re-running only refreshes path/launch_spec/description.
python3 "$REGISTER" --slug "$SLUG" --path "$BIN" --project a2a-cli-registry \
  --lang python --kind python_module --standalone --health-status "$HEALTH" \
  --description "$DESC" --db "$DB"

# 4. capability row with provenance='manual' (populate() preserves it).
#    The entry rides in argv: with `python3 -` the heredoc IS stdin, so a
#    piped payload would be swallowed by the script source.
python3 - "$DB" "$ENTRY" <<'PY'
import json, sqlite3, sys
db = sys.argv[1]
e = json.loads(sys.argv[2])
cap = e["capability"]
row = (",".join(cap["intent_tags"]), ",".join(cap["input_types"]),
       ",".join(cap["output_types"]), cap["side_effect"], cap["confidence"])
con = sqlite3.connect(db, timeout=30)
try:
    cur = con.execute("SELECT id FROM capability WHERE cli_slug=? AND provenance='manual'", (e["slug"],))
    hit = cur.fetchone()
    if hit:
        con.execute("UPDATE capability SET intent_tags=?, input_types=?, output_types=?, "
                    "side_effect=?, confidence=? WHERE id=?", row + (hit[0],))
        verb = "updated"
    else:
        # drop any feed-owned row for the slug so the planner sees one truth
        con.execute("DELETE FROM capability WHERE cli_slug=?", (e["slug"],))
        con.execute("INSERT INTO capability (cli_slug, intent_tags, input_types, output_types, "
                    "side_effect, confidence, provenance) VALUES (?,?,?,?,?,?,'manual')",
                    (e["slug"],) + row)
        verb = "inserted"
    con.commit()
finally:
    con.close()
print(f"apply: capability row {verb} (provenance=manual): {row[1]} -> {row[2]} [{row[3]}, {row[4]}]")
PY

echo "apply: done (health=$HEALTH). Verify: .venv/bin/python -m core.planner.probe --slug $SLUG --goal-inputs file:md --goal-outputs file:pdf --db $DB"
