import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlmodel import Session

from core.catalog.queries import search_clis
from core.models import Cli, Capability
from core.store.db import init_db
from tools import registry_hygiene as hygiene


PDF_SOURCE = '''
def render(output_path):
    from reportlab.pdfgen import canvas as rl_canvas
    c = rl_canvas.Canvas(str(output_path))
    c.save()
'''


def make_db(tmp_path, *, readable_unknown=False):
    path = tmp_path / 'registry.db'
    producer = tmp_path / 'producer.py'
    producer.write_text(PDF_SOURCE)
    consumer = tmp_path / 'consumer.py'
    consumer.write_text('print(open("input.pdf").read())')
    engine = init_db(str(path))
    with Session(engine) as session:
        session.add(Cli(slug='generate_pdf', lang='python', path=str(producer),
                        description='Renders a document.', description_provenance='llm'))
        session.add(Capability(cli_slug='generate_pdf', output_types='path',
                               intent_tags='generate', provenance='static'))
        session.add(Cli(slug='manual', lang='python', path=str(producer),
                        description='Curated producer.', description_provenance='manual'))
        session.add(Capability(cli_slug='manual', output_types='curated-output', provenance='manual'))
        session.add(Cli(slug='consumer', lang='python', path=str(consumer), description='Reads a document.'))
        session.add(Capability(cli_slug='consumer', output_types='text', provenance='static'))
        for i in range(37):
            slug = f'gone-{i:02d}'
            session.add(Cli(slug=slug, lang='python', path=str(tmp_path / f'{slug}.py'),
                            description=f'unknown purpose ({slug})', description_provenance='llm'))
            session.add(Capability(cli_slug=slug, output_types='', provenance='llm'))
        session.add(Cli(slug='already-disabled', lang='python', enabled=False,
                        path=str(tmp_path / 'disabled.py'), description='unknown purpose (already-disabled)'))
        if readable_unknown:
            session.add(Cli(slug='unresolved', lang='python', path=str(producer),
                            description='unknown purpose (unresolved)'))
        session.commit()
    engine.dispose()
    return str(path)


def rows(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as con:
        return (
            con.execute('SELECT * FROM cli ORDER BY slug').fetchall(),
            con.execute('SELECT * FROM capability ORDER BY id').fetchall(),
        )


def test_preview_is_read_only_and_targets_only_missing_unknowns(tmp_path):
    path = make_db(tmp_path)
    before = rows(path)
    report = hygiene.inspect_db(path)
    assert len(report['disable']) == 37
    assert report['unresolved'] == []
    assert [r['slug'] for r in report['outputs']] == ['generate_pdf']
    assert report['outputs'][0]['after'] == 'path,file:pdf'
    assert rows(path) == before
    assert list(tmp_path.glob('*.bak')) == []
    assert not Path(path + '.lock').exists()


def test_apply_satisfies_ac01_ac02_without_losing_rows(tmp_path):
    path = make_db(tmp_path)
    before = rows(path)
    report = hygiene.apply_hygiene(path, expected_missing=37)
    assert rows(report['backup']) == before
    after = rows(path)
    assert len(after[0]) == len(before[0])
    assert len(after[1]) == len(before[1])
    with closing(sqlite3.connect(path)) as con:
        assert con.execute("SELECT COUNT(*) FROM cli WHERE enabled=1 AND lower(trim(description)) LIKE 'unknown purpose%'").fetchone()[0] == 0
        assert con.execute("SELECT description, description_provenance, enabled FROM cli WHERE slug='gone-00'").fetchone() == ('unknown purpose (gone-00)', 'llm', 0)
        assert con.execute("SELECT output_types, provenance FROM capability WHERE cli_slug='manual'").fetchone() == ('curated-output', 'manual')
        assert con.execute("SELECT output_types FROM capability WHERE cli_slug='consumer'").fetchone() == ('text',)
    engine = init_db(path)
    try:
        with Session(engine) as session:
            assert [r['slug'] for r in search_clis(session, 'file:pdf')] == ['generate_pdf']
    finally:
        engine.dispose()
    assert hygiene.inspect_db(path)['outputs'] == []
    repeat = hygiene.apply_hygiene(path, expected_missing=0)
    assert repeat['disable'] == [] and repeat['outputs'] == [] and repeat['backup'] is None
    assert rows(path) == after


@pytest.mark.parametrize('readable_unknown', [False, True])
def test_refuses_wrong_count_or_readable_placeholder_before_any_write(tmp_path, readable_unknown):
    path = make_db(tmp_path, readable_unknown=readable_unknown)
    before = rows(path)
    expected = 37 if readable_unknown else 36
    with pytest.raises(ValueError, match='unresolved|expected'):
        hygiene.apply_hygiene(path, expected_missing=expected)
    assert rows(path) == before
    assert list(tmp_path.glob('*.bak')) == []


def test_reviewed_descriptions_resolve_live_placeholders(tmp_path):
    path = make_db(tmp_path, readable_unknown=True)
    report = hygiene.apply_hygiene(path, expected_missing=37,
                                   descriptions={'unresolved': 'Renders a document to PDF.'})
    assert report['described'] == ['unresolved']
    with closing(sqlite3.connect(path)) as con:
        assert con.execute(
            "SELECT description, description_provenance, enabled FROM cli WHERE slug='unresolved'"
        ).fetchone() == ('Renders a document to PDF.', 'manual', 1)
        assert con.execute("SELECT COUNT(*) FROM cli WHERE enabled=1 AND lower(trim(description)) LIKE 'unknown purpose%'").fetchone()[0] == 0


@pytest.mark.parametrize('descriptions', [{'generate_pdf': 'Not a placeholder.'}, {'unresolved': '   '}])
def test_descriptions_must_target_live_placeholders_and_be_nonempty(tmp_path, descriptions):
    path = make_db(tmp_path, readable_unknown=True)
    before = rows(path)
    with pytest.raises(ValueError, match='not live placeholders|unresolved'):
        hygiene.apply_hygiene(path, expected_missing=37, descriptions=descriptions)
    assert rows(path) == before
    assert list(tmp_path.glob('*.bak')) == []


def test_permission_error_does_not_mean_source_is_missing(tmp_path, monkeypatch):
    path = make_db(tmp_path)
    real_stat = Path.stat

    def denied(self, *args, **kwargs):
        if self.name == 'gone-00.py':
            raise PermissionError('fixture denial')
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', denied)
    report = hygiene.inspect_db(path)
    assert 'gone-00' not in report['disable']
    assert 'gone-00' in report['unresolved']
    with pytest.raises(ValueError, match='unresolved'):
        hygiene.apply_hygiene(path, expected_missing=37)


def test_backup_failure_prevents_any_mutation(tmp_path, monkeypatch):
    path = make_db(tmp_path)
    before = rows(path)

    def fail(path):
        raise OSError('disk full')

    monkeypatch.setattr(hygiene, '_backup', fail)
    with pytest.raises(OSError, match='disk full'):
        hygiene.apply_hygiene(path, expected_missing=37)
    assert rows(path) == before


def test_sql_failure_rolls_back_output_and_enabled_changes(tmp_path):
    path = make_db(tmp_path)
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TRIGGER reject_disable BEFORE UPDATE OF enabled ON cli
            WHEN NEW.enabled=0 BEGIN SELECT RAISE(ABORT, 'fixture rejection'); END""")
    before = rows(path)
    with pytest.raises(sqlite3.IntegrityError, match='fixture rejection'):
        hygiene.apply_hygiene(path, expected_missing=37)
    assert rows(path) == before


def test_missing_database_is_not_created(tmp_path):
    path = str(tmp_path / 'absent.db')
    with pytest.raises(FileNotFoundError):
        hygiene.inspect_db(path)
    assert not Path(path).exists()
