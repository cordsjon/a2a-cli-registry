#!/bin/sh
# Reproduce the diar1 registry state on this machine — idempotent.
# Reconstructs what git does NOT carry: the feed entries (demo/ is gitignored)
# and the registry.db rows (registry.db is gitignored). Safe to re-run; each
# step is a no-op if already applied. Clone of fleet-clis/funroadtrip/seed/apply.sh:
# a CLI that lives in its OWN repo rather than under fleet-clis/.
#
#   sh fleet-clis/diar1/seed/apply.sh [--config demo/config.toml]
#
# Requires DIAR1_VENV to point at the venv diar1 is installed in (default: the
# pipeline venv of the TG2 engagement in 75_Coaching) -- the entries' path is
# resolved from there, never hardcoded in feed-entries.json.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(CDPATH= cd -- "$HERE/../../.." && pwd)          # fleet-clis/diar1/seed -> registry repo root
SEED="$HERE/feed-entries.json"
CONFIG="${2:-demo/config.toml}"

DIAR1_VENV="${DIAR1_VENV:-$HOME/projects/75_Coaching/10_Consulting/20_Daimler_Buses/Tg2/pipeline/.venv}"
BIN="$DIAR1_VENV/bin/diar1"
[ -x "$BIN" ] || { echo "apply: no diar1 binary at $BIN -- set DIAR1_VENV or install diar1 into that venv" >&2; exit 1; }

cd "$REPO"

# 0. locate the live feed the config consumes (cli_audit_path in the TOML)
FEED=$(grep -E '^cli_audit_path' "$CONFIG" 2>/dev/null | sed 's/.*=[[:space:]]*"\(.*\)".*/\1/')
[ -n "$FEED" ] || { echo "apply: cannot read cli_audit_path from $CONFIG" >&2; exit 1; }
echo "apply: feed=$FEED  binary=$BIN"

# 1. vocabulary — every diar1 verb takes an engagement folder (dir:engagement),
#    a type the registered vocabulary does not carry. An unregistered type
#    quarantines the capability to "unverified:" and excludes it from chaining
#    (core/discovery/cli_audit_source.py). Idempotent: only appends what is absent.
python3 - "$CONFIG" <<'PY'
import os, re, sys, tempfile
config_path = sys.argv[1]
text = open(config_path, encoding="utf-8").read()
needed = ["dir:engagement"]
match = re.search(r'^registered = \[(.*?)\]', text, re.MULTILINE | re.DOTALL)
if not match:
    print("apply: WARNING no [vocabulary] registered = [...] found; skipping", file=sys.stderr)
else:
    current = re.findall(r'"([^"]+)"', match.group(1))
    missing = [t for t in needed if t not in current]
    if not missing:
        print("apply: vocabulary already carries dir:engagement")
    else:
        body = match.group(1).rstrip()
        sep = "" if not body.strip() or body.endswith(",") else ","
        added = " ".join(f'"{t}",' for t in missing).rstrip(",")
        new = f"registered = [{body}{sep} {added}" + ("\n]" if "\n" in match.group(1) else "]")
        text = text[:match.start()] + new + text[match.end():]
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(config_path) or ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, config_path)
        print(f"apply: added {missing} to [vocabulary] registered")
PY

# 2. upsert the entries into the live feed — replace-by-slug, not skip-if-present,
#    so edits to an existing slug's fields actually land on re-apply (same
#    idempotency contract as pdf-tools/seed/apply.sh).
python3 - "$SEED" "$FEED" "$BIN" <<'PY'
import json, sys, os, tempfile
seed_path, feed_path, binpath = sys.argv[1], sys.argv[2], sys.argv[3]
seed = json.load(open(seed_path, encoding="utf-8"))
feed = json.load(open(feed_path, encoding="utf-8")) if os.path.exists(feed_path) else {"schema_version":1,"run_id":"seeded","clis":[]}
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
with os.fdopen(fd, "w", encoding="utf-8") as fh:
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

echo "apply: done. Verify with: $PY -c \"from core.store.db import init_db,get_session; from core.catalog.queries import search_clis; e=init_db('registry.db'); s=get_session(e).__enter__(); print(sorted(h['slug'] for h in search_clis(s,'diar1')))\""
