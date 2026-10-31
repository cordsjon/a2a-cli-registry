import json
import os
import sqlite3
from pathlib import Path

import pytest

from core.prober.smoke import run_smoke
from scripts.apply_smoke_seed import main

REPO = Path(__file__).resolve().parents[1]
SEEDS = REPO / "seed" / "smoke"
# consigliere-gaps has no seed: 20_CONSIGLIERE is off limits until the hold lifts.
SLUGS = ["ytx", "decisions_cli", "invoice-fetcher", "gmail_attachments", "wa-bridge"]
OFFLINE = ["ytx", "decisions_cli"]


def _seed(slug):
    return json.loads((SEEDS / f"{slug}.json").read_text())


@pytest.mark.parametrize("slug", SLUGS)
def test_seed_is_runnable(slug):
    smoke = _seed(slug)
    assert os.path.isabs(smoke["argv"][0]) and os.access(smoke["argv"][0], os.X_OK)
    assert smoke["tier"] == "hand"
    assert smoke["side_effects"] in {"none", "network"}
    if "fixture" in smoke:
        assert (REPO / smoke["fixture"]).exists()


@pytest.mark.parametrize("slug", OFFLINE)
def test_a_fixture_smoke_passes(slug):
    assert run_smoke({"smoke": _seed(slug)}, timeout=60) == "pass"


def test_the_decisions_smoke_fails_without_its_fixture():
    # Not repeated for ytx: without its fixture it is a cache miss, which fetches.
    smoke = {**_seed("decisions_cli"), "fixture": None}
    assert run_smoke({"smoke": smoke}, timeout=60) == "fail"


def test_no_fixture_ledger_reaches_the_real_decisions_sweep():
    """find_ledgers walks ~/projects and skips dot directories. A fixture outside
    one would put its open entry in the operator's review queue."""
    for ledger in SEEDS.rglob("DECISIONS.md"):
        assert any(p.startswith(".") for p in ledger.relative_to(REPO).parts), ledger


def _db(tmp_path, rows):
    db = tmp_path / "registry.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE cli (slug TEXT, launch_spec TEXT)")
    con.executemany("INSERT INTO cli VALUES (?, ?)", rows)
    con.commit()
    con.close()
    return db


def _spec(db, slug):
    con = sqlite3.connect(db)
    row = con.execute("SELECT launch_spec FROM cli WHERE slug = ?", (slug,)).fetchone()
    con.close()
    return row[0]


def _write_seed(seed_dir, slug, **smoke):
    seed_dir.mkdir(exist_ok=True)
    (seed_dir / f"{slug}.json").write_text(json.dumps({"argv": ["/bin/true"], **smoke}))


def test_dry_run_writes_nothing(tmp_path):
    original = json.dumps({"argv": ["/bin/a"]})
    db = _db(tmp_path, [("a", original)])
    _write_seed(tmp_path / "seeds", "a")
    assert main(["--db", str(db), "--seed-dir", str(tmp_path / "seeds")]) == 0
    assert _spec(db, "a") == original


def test_apply_upserts_smoke_and_keeps_the_other_keys(tmp_path):
    db = _db(tmp_path, [("a", json.dumps({"argv": ["/bin/a"], "smoke": {"argv": ["/bin/old"]}}))])
    _write_seed(tmp_path / "seeds", "a", timeout=5)
    assert main(["--db", str(db), "--seed-dir", str(tmp_path / "seeds"), "--apply"]) == 0
    assert json.loads(_spec(db, "a")) == {"argv": ["/bin/a"],
                                         "smoke": {"argv": ["/bin/true"], "timeout": 5}}


@pytest.mark.parametrize("rows", [[("a", "{}")],                       # b is not in the DB
                                  [("a", "{}"), ("b", "install:url")]])  # b holds no spec
def test_one_refused_seed_writes_none_of_them(tmp_path, rows):
    db = _db(tmp_path, rows)
    _write_seed(tmp_path / "seeds", "a")
    _write_seed(tmp_path / "seeds", "b")
    assert main(["--db", str(db), "--seed-dir", str(tmp_path / "seeds"), "--apply"]) == 1
    assert _spec(db, "a") == "{}"
