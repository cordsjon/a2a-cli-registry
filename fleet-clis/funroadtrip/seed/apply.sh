#!/bin/sh
# Reproduce the funroadtrip registry state on this machine — idempotent.
# Reconstructs what git does NOT carry: the feed entry (demo/ is gitignored)
# and the registry.db row (registry.db is gitignored). Safe to re-run; each
# step is a no-op if already applied. Clone of fleet-clis/pdf-tools/seed/apply.sh,
# adapted for a CLI that lives in its OWN repo rather than under fleet-clis/.
#
#   sh fleet-clis/funroadtrip/seed/apply.sh [--config demo/config.toml]
#
# Requires FUNROADTRIP_REPO to point at the funroadtrip checkout (default
# ~/projects/60_funroadtrip) -- the entry's path is resolved from there, never
# hardcoded in feed-entries.json, so a clone on a different machine still works.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(CDPATH= cd -- "$HERE/../../.." && pwd)          # fleet-clis/funroadtrip/seed -> registry repo root
SEED="$HERE/feed-entries.json"
CONFIG="${2:-demo/config.toml}"

FUNROADTRIP_REPO="${FUNROADTRIP_REPO:-$HOME/projects/60_funroadtrip}"
BIN="$FUNROADTRIP_REPO/.venv/bin/funroadtrip"
[ -x "$BIN" ] || { echo "apply: no funroadtrip binary at $BIN -- set FUNROADTRIP_REPO or check the venv is built" >&2; exit 1; }

cd "$REPO"

# 0. locate the live feed the config consumes (cli_audit_path in the TOML)
FEED=$(grep -E '^cli_audit_path' "$CONFIG" 2>/dev/null | sed 's/.*=[[:space:]]*"\(.*\)".*/\1/')
[ -n "$FEED" ] || { echo "apply: cannot read cli_audit_path from $CONFIG" >&2; exit 1; }
echo "apply: feed=$FEED  binary=$BIN"

# 1. vocabulary — funroadtrip's capability declares two types (text:coordinates,
#    json:poi) neither of which the registered vocabulary in config.toml carries
#    yet. An unregistered type quarantines the capability to "unverified:" and
#    excludes it from cliedge chaining (core/discovery/cli_audit_source.py).
#    Idempotent: only appends a type that is genuinely absent.
python3 - "$CONFIG" <<'PY'
import re, sys
config_path = sys.argv[1]
text = open(config_path).read()
needed = ["text:coordinates", "json:poi"]
match = re.search(r'^registered = \[(.*)\]$', text, re.MULTILINE)
if not match:
    print("apply: WARNING no [vocabulary] registered = [...] line found; skipping", file=sys.stderr)
else:
    current = [t.strip().strip('"') for t in match.group(1).split(",") if t.strip()]
    missing = [t for t in needed if t not in current]
    if not missing:
        print("apply: vocabulary already carries text:coordinates + json:poi")
    else:
        updated = current + missing
        new_line = 'registered = [' + ', '.join(f'"{t}"' for t in updated) + ']'
        text = text[:match.start()] + new_line + text[match.end():]
        open(config_path, "w").write(text)
        print(f"apply: added {missing} to [vocabulary] registered")
PY

# 2. upsert the entry into the live feed — replace-by-slug, not skip-if-present,
#    so edits to an existing slug's fields actually land on re-apply (same
#    idempotency contract as pdf-tools/seed/apply.sh).
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
d = os.path.dirname(feed_path) or "."
fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
with os.fdopen(fd, "w") as fh:
    json.dump(feed, fh, indent=2)
os.replace(tmp, feed_path)
unchanged = len(seed["entries"]) - added - updated
print(f"apply: feed upsert — {added} added, {updated} updated, {unchanged} unchanged")
PY

# 3. populate + probe
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
echo "apply: populating registry..."
"$PY" -m core.cli.main populate --config "$CONFIG" 2>&1 | tail -3

echo "apply: done. Verify with: $PY -c \"from core.store.db import init_db,get_session; from core.catalog.queries import search_clis; e=init_db('registry.db'); s=get_session(e).__enter__(); print([h['slug'] for h in search_clis(s,'funroadtrip')])\""
