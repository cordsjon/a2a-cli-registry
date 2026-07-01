# core/playbooks/index.py
from sqlalchemy import text
from core.playbooks.skillmd import Playbook
from core.playbooks.signature import cli_signature


def _conn(session):
    return session.connection()


def rebuild_index(session, playbooks: list) -> int:
    c = _conn(session)
    c.execute(text("DROP TABLE IF EXISTS playbook_fts"))
    c.execute(text("DROP TABLE IF EXISTS playbook_sig"))
    c.execute(text(
        "CREATE VIRTUAL TABLE playbook_fts USING fts5(slug, description, tags)"
    ))
    c.execute(text(
        "CREATE TABLE playbook_sig (slug TEXT, cli TEXT, sig TEXT)"
    ))
    for pb in playbooks:
        c.execute(
            text("INSERT INTO playbook_fts(slug, description, tags) VALUES (:s, :d, :t)"),
            {"s": pb.slug, "d": pb.description, "t": " ".join(pb.tags)},
        )
        for slug in pb.allowed_tools:
            c.execute(
                text("INSERT INTO playbook_sig(slug, cli, sig) VALUES (:s, :c, :g)"),
                {"s": pb.slug, "c": slug, "g": cli_signature(session, slug) or ""},
            )
    session.commit()
    return len(playbooks)


def retrieve(session, query: str, limit: int = 5) -> list:
    c = _conn(session)
    if not query.strip():
        rows = c.execute(text("SELECT slug FROM playbook_fts ORDER BY slug")).fetchall()
        return [r[0] for r in rows]
    rows = c.execute(
        text(
            "SELECT slug FROM playbook_fts WHERE playbook_fts MATCH :q "
            "ORDER BY bm25(playbook_fts) LIMIT :lim"
        ),
        {"q": query, "lim": limit},
    ).fetchall()
    return [r[0] for r in rows]


def stale_against_index(session, pb: Playbook) -> list:
    c = _conn(session)
    out = []
    for slug in pb.allowed_tools:
        row = c.execute(
            text("SELECT sig FROM playbook_sig WHERE slug = :s AND cli = :c"),
            {"s": pb.slug, "c": slug},
        ).fetchone()
        cached = row[0] if row else None
        current = cli_signature(session, slug) or ""
        if cached is not None and cached != current:
            out.append(slug)
    return out
