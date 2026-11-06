"""US-CAPLOOP-04: additive typed outputs and reversible missing-source hygiene.

Run from the registry root with python -m tools.registry_hygiene.
Preview is read-only. Application requires an explicit missing-source count.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from core.store.db import with_file_lock
from core.store.migrations import migrate_description_provenance
from tools.capability_extractor import typed_file_outputs


def _connect(db_path: str, *, readonly: bool = True) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    mode = 'ro' if readonly else 'rw'
    con = sqlite3.connect(path.as_uri() + f'?mode={mode}', uri=True, timeout=5.0)
    con.row_factory = sqlite3.Row
    return con


def _inspect(con: sqlite3.Connection) -> dict:
    rows = con.execute(
        'SELECT slug, lang, path, description FROM cli WHERE enabled=1 ORDER BY slug'
    ).fetchall()
    report = {'enabled': len(rows), 'disable': [], 'unresolved': [], 'outputs': []}
    for row in rows:
        slug = row['slug']
        unknown = (row['description'] or '').strip().lower().startswith('unknown purpose')
        path = Path(row['path']).expanduser() if row['path'] else None
        missing = False
        regular = False
        try:
            regular = path is not None and stat.S_ISREG(path.stat().st_mode)
        except FileNotFoundError:
            missing = True
        except OSError:
            regular = False
        if unknown:
            report['disable' if missing else 'unresolved'].append(slug)
            continue
        if row['lang'] != 'python' or not regular:
            continue
        try:
            source = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        typed = typed_file_outputs(source)
        if not typed:
            continue
        caps = con.execute(
            'SELECT id, output_types, provenance FROM capability WHERE cli_slug=? ORDER BY id',
            (slug,),
        ).fetchall()
        for cap in caps:
            if cap['provenance'] not in (None, 'static', 'llm'):
                continue
            before = cap['output_types'] or ''
            ports = [p for p in before.split(',') if p]
            additions = [p for p in typed if p not in ports]
            if additions:
                report['outputs'].append({
                    'id': cap['id'], 'slug': slug, 'before': before,
                    'after': ','.join(ports + additions),
                })
    return report


def inspect_db(db_path: str) -> dict:
    with closing(_connect(db_path)) as con:
        return _inspect(con)


def _backup(db_path: str) -> str:
    path = Path(db_path).expanduser().resolve()
    fd, name = tempfile.mkstemp(prefix=path.name + '.hygiene-', suffix='.bak', dir=path.parent)
    os.close(fd)
    with closing(_connect(str(path))) as source:
        with closing(sqlite3.connect(name)) as target:
            source.backup(target)
    return name


def apply_hygiene(db_path: str, *, expected_missing: int,
                  descriptions: dict[str, str] | None = None) -> dict:
    """descriptions: reviewed text for placeholder rows whose source still exists."""
    descriptions = {s: (t or '').strip() for s, t in (descriptions or {}).items()}
    path = str(Path(db_path).expanduser().resolve())
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    with with_file_lock(path + '.lock'):
        with closing(_connect(path, readonly=False)) as con:
            try:
                # Block other SQLite writers, including Governance's upsert.
                # The backup uses a separate read connection before mutation.
                con.execute('BEGIN IMMEDIATE')
                report = _inspect(con)
                stray = sorted(set(descriptions) - set(report['unresolved']))
                if stray:
                    raise ValueError(f"descriptions for rows that are not live placeholders: {stray}")
                blocked = [s for s in report['unresolved'] if not descriptions.get(s)]
                if blocked:
                    raise ValueError(f"unresolved unknown purpose rows: {blocked}")
                if len(report['disable']) != expected_missing:
                    raise ValueError(f"expected {expected_missing} missing rows, found {len(report['disable'])}")
                report['described'] = sorted(descriptions)
                needs_migration = 'description_provenance' not in {
                    r[1] for r in con.execute('PRAGMA table_info(cli)')
                }
                if (not needs_migration and not report['outputs']
                        and not report['disable'] and not descriptions):
                    con.rollback()
                    return {**report, 'backup': None}
                backup = _backup(path)
                migrate_description_provenance(con)
                for change in report['outputs']:
                    result = con.execute("""
                        UPDATE capability SET output_types=?
                        WHERE id=? AND output_types=?
                          AND (provenance IS NULL OR provenance IN ('static','llm'))
                    """, (change['after'], change['id'], change['before']))
                    if result.rowcount != 1:
                        raise RuntimeError(f"capability changed during hygiene: {change['id']}")
                for slug in report['disable']:
                    con.execute('UPDATE cli SET enabled=0 WHERE slug=?', (slug,))
                for slug, text in descriptions.items():
                    result = con.execute("""
                        UPDATE cli SET description=?, description_provenance='manual'
                        WHERE slug=? AND enabled=1
                          AND lower(trim(description)) LIKE 'unknown purpose%'
                    """, (text, slug))
                    if result.rowcount != 1:
                        raise RuntimeError(f"placeholder changed during hygiene: {slug}")
                remaining = con.execute("""
                    SELECT COUNT(*) FROM cli WHERE enabled=1
                      AND lower(trim(description)) LIKE 'unknown purpose%'
                """).fetchone()[0]
                if remaining:
                    raise RuntimeError(f'{remaining} enabled unknown purpose rows remain')
                con.commit()
                return {**report, 'backup': backup}
            except Exception:
                con.rollback()
                raise


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expect-missing', type=int)
    parser.add_argument('--descriptions', help='JSON object {slug: reviewed description}')
    args = parser.parse_args(argv)
    if args.apply and (args.expect_missing is None or args.expect_missing < 0):
        parser.error('--apply requires --expect-missing with a nonnegative count')
    descriptions = (json.loads(Path(args.descriptions).read_text(encoding='utf-8'))
                    if args.descriptions else None)
    result = (apply_hygiene(args.db, expected_missing=args.expect_missing,
                            descriptions=descriptions)
              if args.apply else inspect_db(args.db))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
