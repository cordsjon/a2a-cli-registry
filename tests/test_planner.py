from core.models import Cli, Capability, CliEdge
from core.planner.search import plan_chain, Chain


def _fleet(db):
    for slug, intag, ins, outs, se, conf in [
        ("pdf2text", "convert", "file:pdf", "text:doc", "none", "declared"),
        ("summarize", "summarize", "text:doc", "text:summary", "none", "declared"),
        ("shred", "delete", "text:doc", "text:summary", "destructive", "declared"),
    ]:
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags=intag, input_types=ins,
                          output_types=outs, side_effect=se, confidence=conf))
    db.add(CliEdge(from_slug="pdf2text", to_slug="summarize", via_type="text:doc"))
    db.add(CliEdge(from_slug="pdf2text", to_slug="shred", via_type="text:doc"))
    db.commit()


def test_known_goal_yields_expected_chain(db):
    _fleet(db)
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"])
    assert chains[0].slugs == ["pdf2text", "summarize"]   # exact expected, ranked first


def test_unsatisfiable_goal_returns_empty(db):
    _fleet(db)
    assert plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["audio:wav"]) == []


def test_empty_goal_inputs_reaches_no_input_cli(db):
    # Live bug (2026-07-11): `starts = [s for s, c in caps.items() if
    # _slug_consumes(c) & goal_in]` — when goal_inputs=[], goal_in is an empty
    # set, and X & set() is always empty/falsy for any X. So starts=[]
    # unconditionally, regardless of what CLIs exist. This makes EVERY
    # no-declared-input-type CLI (input_types="", the correct shape for a
    # generic "list files"/"find X"/"check status" query-only goal) permanently
    # unreachable whenever the caller can't name an input type — exactly the
    # case for goals like "find syllabus files" (confirmed live: 276 real
    # capability rows have input_types="" in the production registry).
    db.add(Cli(slug="list_files", lang="python"))
    db.add(Capability(cli_slug="list_files", intent_tags="list", input_types="",
                      output_types="text:listing", side_effect="none", confidence="declared"))
    db.commit()
    chains = plan_chain(db, goal_inputs=[], goal_outputs=["text:listing"])
    assert any(c.slugs == ["list_files"] for c in chains)


def test_empty_goal_inputs_does_not_reach_typed_input_cli(db):
    # The fix for the bug above must not become "goal_inputs=[] matches
    # everything" — a CLI that DOES declare a real input type should still
    # require goal_inputs to name it. Only genuinely no-input CLIs are valid
    # starts when goal_inputs is empty.
    _fleet(db)  # pdf2text declares input_types="file:pdf"
    chains = plan_chain(db, goal_inputs=[], goal_outputs=["text:summary"])
    assert chains == []


def test_destructive_excluded_by_default(db):
    _fleet(db)
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"])
    assert all("shred" not in c.slugs for c in chains)    # destructive hop excluded


def test_destructive_included_when_allowed(db):
    _fleet(db)
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"],
                        allow_side_effects=["destructive"])
    assert any("shred" in c.slugs for c in chains)


def test_ranking_keys_are_independently_ordered(db):
    """Two equal-length chains where key-2 (side-effect count) and key-3
    (min-confidence) DISAGREE. A has fewer side-effects but lower confidence;
    B has more side-effects but higher confidence. A MUST rank first — proving
    side-effect-count strictly precedes min-confidence."""
    # chain A: clean but inferred ; chain B: writes-fs but declared
    db.add(Cli(slug="src", lang="python"))
    db.add(Capability(cli_slug="src", intent_tags="g", input_types="file:pdf",
                      output_types="text:x", side_effect="none", confidence="declared"))
    for slug, se, conf in [("A", "none", "inferred"), ("B", "writes-fs", "declared")]:
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags="g", input_types="text:x",
                          output_types="text:goal", side_effect=se, confidence=conf))
        db.add(CliEdge(from_slug="src", to_slug=slug, via_type="text:x"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"],
                        allow_side_effects=["writes-fs"])
    # A (fewer side-effects) ranks before B (more side-effects), despite lower confidence
    assert chains[0].slugs[-1] == "A"


def test_chain_hops_carry_routing_fields(db):
    _fleet(db)
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"])
    assert chains, "expected at least one chain"
    chain = chains[0]
    assert chain.slugs == ["pdf2text", "summarize"]
    # every hop must have side_effect and provenance
    for hop in chain.hops:
        assert "side_effect" in hop, f"missing side_effect in hop: {hop}"
        assert "provenance" in hop, f"missing provenance in hop: {hop}"
    # second hop (index 1) must carry the routing edge fields
    hop1 = chain.hops[1]
    assert hop1["from"] == "pdf2text", f"expected from=pdf2text, got {hop1.get('from')}"
    assert hop1["to"] == "summarize", f"expected to=summarize, got {hop1.get('to')}"
    assert "via_type" in hop1, f"missing via_type in second hop: {hop1}"
    assert hop1["via_type"] == "text:doc"


def _inferred_fleet(db, se="writes-fs"):
    """Only path file:pdf -> text:goal passes through 'mid', which carries an
    INFERRED side_effect. Used to prove inferred-side-effect exclusion."""
    db.add(Cli(slug="src", lang="python"))
    db.add(Capability(cli_slug="src", intent_tags="g", input_types="file:pdf",
                      output_types="text:x", side_effect="none", confidence="declared"))
    db.add(Cli(slug="mid", lang="python"))
    db.add(Capability(cli_slug="mid", intent_tags="g", input_types="text:x",
                      output_types="text:goal", side_effect=se, confidence="inferred"))
    db.add(CliEdge(from_slug="src", to_slug="mid", via_type="text:x"))
    db.commit()


def test_inferred_side_effect_excluded_by_default(db):
    # the ONLY path to text:goal goes through an inferred writes-fs hop -> excluded
    _inferred_fleet(db, se="writes-fs")
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"])
    assert all("mid" not in c.slugs for c in chains)
    assert chains == []   # no alternative path exists


def test_inferred_side_effect_included_when_allowed(db):
    # same goal, operator opts into writes-fs blast-radius class -> chain returned
    _inferred_fleet(db, se="writes-fs")
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"],
                        allow_side_effects=["writes-fs"])
    assert any("mid" in c.slugs for c in chains)


def test_inferred_network_side_effect_excluded_by_default(db):
    # network inferred side-effect is also excluded by default
    _inferred_fleet(db, se="network")
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"])
    assert chains == []


def test_inferred_none_side_effect_still_allowed(db):
    # inferred confidence with NO blast radius (none) is harmless -> NOT excluded
    _inferred_fleet(db, se="none")
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"])
    assert any("mid" in c.slugs for c in chains)


def test_declared_writes_fs_still_allowed_by_default(db):
    # a DECLARED writes-fs hop must STILL be included by default (only INFERRED
    # writes-fs/network is newly excluded)
    db.add(Cli(slug="src", lang="python"))
    db.add(Capability(cli_slug="src", intent_tags="g", input_types="file:pdf",
                      output_types="text:x", side_effect="none", confidence="declared"))
    db.add(Cli(slug="dmid", lang="python"))
    db.add(Capability(cli_slug="dmid", intent_tags="g", input_types="text:x",
                      output_types="text:goal", side_effect="writes-fs", confidence="declared"))
    db.add(CliEdge(from_slug="src", to_slug="dmid", via_type="text:x"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"])
    assert any("dmid" in c.slugs for c in chains)


def test_declared_external_side_effect_always_allowed(db):
    # a DECLARED external hop must be included by default, mirroring the
    # writes-fs precedent above. Nonempty output_types on the synthetic
    # capability is required — Bug 2 (empty output_types) is a separate,
    # independently-tested gap; this test isolates Bug 1 only.
    db.add(Cli(slug="src", lang="python"))
    db.add(Capability(cli_slug="src", intent_tags="g", input_types="file:pdf",
                      output_types="text:x", side_effect="none", confidence="declared"))
    db.add(Cli(slug="emid", lang="python"))
    db.add(Capability(cli_slug="emid", intent_tags="g", input_types="text:x",
                      output_types="text:goal", side_effect="external", confidence="declared"))
    db.add(CliEdge(from_slug="src", to_slug="emid", via_type="text:x"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"])
    assert any("emid" in c.slugs for c in chains)


def test_inferred_external_side_effect_excluded_by_default(db):
    # inferred (unverified) external side-effect must fail UNSAFE by default,
    # same rule as inferred writes-fs/network above.
    _inferred_fleet(db, se="external")
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"])
    assert chains == []


def test_inferred_external_side_effect_included_when_allowed(db):
    # same goal, operator opts into the external blast-radius class -> included
    _inferred_fleet(db, se="external")
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"],
                        allow_side_effects=["external"])
    assert any("mid" in c.slugs for c in chains)


def test_terminates_on_cyclic_typegraph(db):
    db.add(Cli(slug="a", lang="python")); db.add(Cli(slug="b", lang="python"))
    db.add(Capability(cli_slug="a", input_types="t", output_types="t", intent_tags="x",
                      side_effect="none", confidence="declared"))
    db.add(Capability(cli_slug="b", input_types="t", output_types="t", intent_tags="x",
                      side_effect="none", confidence="declared"))
    db.add(CliEdge(from_slug="a", to_slug="b", via_type="t"))
    db.add(CliEdge(from_slug="b", to_slug="a", via_type="t"))
    db.commit()
    # must terminate (cycle guard), not hang
    plan_chain(db, goal_inputs=["t"], goal_outputs=["nonexistent"], max_chain_depth=4)


def test_favorably_ranked_start_not_starved_by_worse_earlier_candidates(db):
    # 100 "worse" starts (writes-fs side effect -> side_effect_count=1) each
    # produce ONE matching candidate immediately. A 101st start, "winner"
    # (side_effect='none' -> side_effect_count=0, strictly better per
    # Chain.sort_key()), is inserted LAST. Before the fix: the 100 worse
    # candidates fill max_candidate_chains before winner's start is ever
    # visited, so winner is starved out entirely -- not merely ranked last,
    # ABSENT. After the fix: every start is enumerated before sorting, so
    # winner (fewest side effects) correctly sorts to position 0.
    #
    # This shape is deliberately NOT "N dead-end starts + 1 winner" (that
    # never fills the cap at all, since dead ends append nothing, and does
    # not reproduce the bug -- confirmed during spec review). Starvation
    # requires earlier starts that actually contend for cap space.
    for i in range(100):
        slug = f"worse{i:03d}"
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags="g", input_types="file:pdf",
                          output_types="text:goal", side_effect="writes-fs", confidence="declared"))
    db.add(Cli(slug="winner", lang="python"))
    db.add(Capability(cli_slug="winner", intent_tags="g", input_types="file:pdf",
                      output_types="text:goal", side_effect="none", confidence="declared"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:goal"],
                        max_candidate_chains=100)
    assert chains, "expected at least 100 candidates"
    assert chains[0].slugs == ["winner"], (
        f"winner should rank first (fewest side effects) but got "
        f"{chains[0].slugs}; winner present at all: "
        f"{any(c.slugs == ['winner'] for c in chains)}"
    )


import os as _os
import pytest as _pytest

_LIVE_REGISTRY_DB = _os.path.expanduser("~/.hermes/cli-registry.db")


@_pytest.mark.skipif(not _os.path.exists(_LIVE_REGISTRY_DB),
                     reason="live registry ~/.hermes/cli-registry.db not present")
def test_send_mail_reachable_at_default_cap_live():
    # AC-02: `send_mail` (the live `external` terminal) is reachable at the
    # DEFAULT candidate cap (max_candidate_chains=100) via type-routing against
    # the LIVE registry. This is the meaningful reachability assertion: a
    # synthetic fixture cannot prove it honestly, because send_mail's `external`
    # side effect makes Chain.sort_key() rank it behind every competing
    # side-effect-free producer — stacking N perfect `none`-producers would
    # correctly sort send_mail last, which is not the live behavior. Against the
    # real 474-CLI registry send_mail sits at sorted position 18/100 (the
    # BACKLOG-documented probe result), because the real competitor mix is not
    # all-perfect-none-producers.
    #
    # This pins two shipped fixes together: the cap-starvation fix (16798e3,
    # enumerate-all -> sort -> cap) and the declared-`external` recognition +
    # output_types backfill (3a78aa8). If either regresses, send_mail drops out
    # of the default-cap window and this test fails.
    #
    # The dedicated cap-starvation MECHANISM is pinned separately and
    # synthetically by test_favorably_ranked_start_not_starved_by_worse_earlier_candidates
    # above; this test guards the live-data reachability the mechanism enables.
    from sqlmodel import Session, create_engine

    engine = create_engine(f"sqlite:///{_LIVE_REGISTRY_DB}")
    with Session(engine) as session:
        chains = plan_chain(session, goal_inputs=["text"], goal_outputs=["text"],
                            allow_side_effects=set())
    assert any("send_mail" in c.slugs for c in chains), (
        "send_mail absent from the default-cap (100) plan output against the live "
        "registry — cap-starvation fix 16798e3 or external-recognition 3a78aa8 regressed"
    )


# --- US-CLIREG-GOALACTIONS-01: §2.2 action map -------------------------------
from core.planner.search import _action_terminals, _cap_index


def _mail_fleet(db, mailer_tags="send"):
    """Producer (text) + a mail-terminal CLI. NO persisted edge between them —
    edge synthesis (§2.5) is what must connect them."""
    for slug, intag, ins, outs, se, conf in [
        ("report_gen", "report", "file:pdf", "text", "none", "declared"),
        ("mailer", mailer_tags, "text", "text", "external", "declared"),
    ]:
        db.add(Cli(slug=slug, lang="python"))
        db.add(Capability(cli_slug=slug, intent_tags=intag, input_types=ins,
                          output_types=outs, side_effect=se, confidence=conf))
    db.commit()


def test_action_terminals_matches_email_via_send_tag(db):
    _mail_fleet(db)
    caps = _cap_index(db)
    assert _action_terminals(caps, ["email"]) == {"mailer"}


def test_unknown_action_verb_raises_structured_valueerror(db):
    # spec §2.2/§2.8 test (f): never silently dropped, never routed wrong
    _mail_fleet(db)
    caps = _cap_index(db)
    with _pytest.raises(ValueError, match=r"unknown action verb: telegram; known:"):
        _action_terminals(caps, ["telegram"])


def test_multi_match_terminal_is_hard_integrity_error(db):
    # spec §2.2 + test (h) hermetic twin: a double-tagged terminal (notify,send)
    # matches both 'email' and 'notify' — hard error, never a silent pick.
    _mail_fleet(db, mailer_tags="notify,send")
    caps = _cap_index(db)
    with _pytest.raises(ValueError,
                        match=r"action verb integrity: terminal 'mailer' matches multiple verbs"):
        _action_terminals(caps, ["email"])


@_pytest.mark.skipif(not _os.path.exists(_LIVE_REGISTRY_DB),
                     reason="live registry ~/.hermes/cli-registry.db not present")
def test_max_one_verb_per_live_terminal():
    # spec §5 test (h), RED-first: for EVERY live terminal, at most one verb in
    # _ACTION_REQUIRES_TAG matches its actual intent_tags. Reproduces the
    # send_mail double-match ('notify,send' -> email AND notify) as RED, goes
    # GREEN after the §8-step-0 retag, and stays as the permanent tripwire: a
    # feed re-run reintroducing 'notify' (populate.py delete+recreate) or a new
    # multi-tagged terminal turns it RED again, forcing a fresh design decision.
    from sqlmodel import Session, create_engine
    from core.planner.search import _ACTION_REQUIRES_TAG, _slug_intent_tags

    engine = create_engine(f"sqlite:///{_LIVE_REGISTRY_DB}")
    with Session(engine) as session:
        caps = _cap_index(session)
    offenders = {}
    for slug, caps_for_slug in caps.items():
        tags = _slug_intent_tags(caps_for_slug)
        verbs = [a for a in _ACTION_REQUIRES_TAG if _ACTION_REQUIRES_TAG[a] & tags]
        if len(verbs) > 1:
            offenders[slug] = sorted(verbs)
    assert not offenders, (
        f"live terminals matching >1 action verb: {offenders} — the §2.2 "
        f"max-one-verb-per-live-terminal invariant is violated; decide a fresh "
        f"disambiguation (do NOT silently pick)"
    )


def test_compound_goal_plans_producer_then_mailer_via_persisted_edge(db):
    # §2.3/§2.4 core predicate, isolated from §2.5 synthesis by a PERSISTED edge.
    _mail_fleet(db)
    db.add(CliEdge(from_slug="report_gen", to_slug="mailer", via_type="text"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        goal_actions=["email"])
    assert any(c.slugs == ["report_gen", "mailer"] for c in chains)


def test_producer_does_not_short_circuit_when_goal_actions_set(db):
    # spec §5 test (b): with goal_actions, a bare producer path is NOT terminal.
    _mail_fleet(db)
    db.add(CliEdge(from_slug="report_gen", to_slug="mailer", via_type="text"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        goal_actions=["email"])
    assert all(c.slugs != ["report_gen"] for c in chains)


def test_empty_goal_actions_is_byte_identical_to_today(db):
    # spec §5 test (c): regression guard — goal_actions=[] output == legacy output.
    _fleet(db)
    legacy = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"])
    gated = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text:summary"],
                       goal_actions=[])
    assert [c.slugs for c in legacy] == [c.slugs for c in gated]
    assert [c.hops for c in legacy] == [c.hops for c in gated]


def test_dual_capable_cli_does_not_satisfy_compound_in_one_hop(db):
    # spec §5 test (e) / §2.3: artifact must come from an EARLIER hop.
    db.add(Cli(slug="dual", lang="python"))
    db.add(Capability(cli_slug="dual", intent_tags="send", input_types="text",
                      output_types="text", side_effect="external", confidence="declared"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["text"], goal_outputs=["text"],
                        goal_actions=["email"])
    assert all(c.slugs != ["dual"] for c in chains)


def test_more_than_one_action_verb_raises(db):
    # spec §7: multi-action-per-goal is OUT — explicit error, not silent.
    _mail_fleet(db)
    with _pytest.raises(ValueError, match="multiple action verbs"):
        plan_chain(db, goal_inputs=["text"], goal_outputs=[],
                   goal_actions=["email", "webhook"])


def test_compound_goal_reaches_mailer_with_zero_persisted_edges(db):
    # spec §5 test (a) + §2.5: live send_mail has ZERO persisted incoming edges
    # (edges.py down-weights bare hub types); synthesis must connect
    # producer -> mailer at plan time. _mail_fleet adds NO CliEdge rows.
    _mail_fleet(db)
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        goal_actions=["email"])
    assert any(c.slugs == ["report_gen", "mailer"] for c in chains)
    # via_type preserved for hop tracing (§2.5)
    two_hop = next(c for c in chains if c.slugs == ["report_gen", "mailer"])
    assert two_hop.hops[1]["via_type"] == "text"


def test_synthesis_does_not_create_chains_into_non_requested_terminals(db):
    # spec §5 test (d): a 'webhook' terminal exists, only 'email' is requested —
    # no chain may end in the webhook CLI.
    _mail_fleet(db)
    db.add(Cli(slug="webhooker", lang="python"))
    db.add(Capability(cli_slug="webhooker", intent_tags="webhook", input_types="text",
                      output_types="text", side_effect="external", confidence="declared"))
    db.commit()
    chains = plan_chain(db, goal_inputs=["file:pdf"], goal_outputs=["text"],
                        goal_actions=["email"])
    assert chains, "email chain must still plan"
    assert all("webhooker" not in c.slugs for c in chains)
