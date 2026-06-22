"""Python-only, experimental capability inference. Kept SEPARATE from discovery
parsing so the LanguageAdapter contract is not Python-shaped. Non-Python adapters
return None (declared-required)."""
from typing import Optional
from core.discovery.base import CliRecord
from core.capability.model import CapabilityRecord

# Ordered list of (keyword_phrase, (intent_tag, side_effect)).
# Evaluated in order. For intent: ALL matching tags are collected (not just first).
# For side_effect: the first explicit non-"none" assignment wins; "none" is only
# applied if no other rule fires AND a lint/test/read-only tag was matched.
#
# DESIGN: generalizable family keywords, NOT memorized per-CLI phrases.
# Each signal here is chosen to fire on MANY tools in its family (e.g. any
# "downloader", any "linter", any "code formatter"), not on one golden help
# text. The §9 precision/recall floor (>=0.6 each) in tests/test_infer.py is a
# real measurement of how well these family keywords generalize -- it is NOT a
# memorization target. Recall below 1.0 is acceptable and honest: it means some
# golden tools phrase themselves idiosyncratically and we abstain rather than
# reverse-engineer their exact wording. Do NOT re-add single-CLI verbatim
# phrases to push recall back to 1.0.
#
# Ordering rationale:
#   - More specific phrases ("static analysis", "type checker") before generic ones
#     ("lint", "format") to avoid mismatch on overlapping text.
#   - "linter" before "lint" so "security linter" fires correctly.
#   - Side-effects are conservative: write only on "reformat"/"in place"/"-i, -"
#     strong signals; network on "downloader"/"download"/"http client"/"upload".
_INTENT_SIGNALS: list[tuple[str, tuple[str, str]]] = [
    # --- lint family (read-only analysis) ---
    ("static code analysis",    ("lint", "none")),
    ("static analysis",         ("lint", "none")),
    ("type checker",            ("lint", "none")),
    ("type check",              ("lint", "none")),
    ("type-check",              ("lint", "none")),
    ("security linter",         ("lint", "none")),
    ("linter and code formatter", ("lint", "none")),  # ruff multi-tag: lint fires first
    ("linter",                  ("lint", "none")),
    ("lint",                    ("lint", "none")),
    ("check the style",         ("lint", "none")),    # any style checker
    ("style guide",            ("lint", "none")),     # any style/convention checker
    ("style errors",           ("lint", "none")),     # any style reporter
    ("unused code",            ("lint", "none")),      # dead/unused-code analyzers
    ("dead code",              ("lint", "none")),      # dead/unused-code analyzers
    # --- format family ---
    # Note: "code formatter" intentionally yields side_effect="none" here;
    # the _WRITES_FS_SIGNALS pass upgrades to "writes-fs" for formatters that
    # actually mention "in place" / "reformat" in their help (black, isort, etc.).
    # This avoids false writes-fs on ruff's top-level dispatcher help.
    ("code formatter",          ("format", "none")),
    ("reformat",                ("format", "writes-fs")),
    ("format python files",     ("format", "none")),       # ruff lists as subcommand; not always in-place
    ("formats python",          ("format", "writes-fs")),
    ("import sorter",          ("format", "writes-fs")),   # import organizers (isort family)
    ("sort python import",     ("format", "writes-fs")),   # import organizers (isort family)
    ("automatically formats",  ("format", "writes-fs")),   # any auto-formatter
    # --- test family (read-only execution) ---
    ("testing framework",       ("test", "none")),
    ("test automation",         ("test", "none")),   # test runners/automation
    ("run test suites",        ("test", "none")),    # test runners
    ("test suites",            ("test", "none")),     # test runners
    ("code coverage",          ("test", "none")),     # coverage tools
    # --- download / network ---
    ("http client",             ("download", "network")),  # any HTTP client
    ("downloader",              ("download", "network")),
    ("download",                ("download", "network")),
    ("retriever",              ("download", "network")),    # any network retriever/fetcher
    # --- publish / upload ---
    ("upload",                  ("publish", "network")),
    ("publish",                 ("publish", "network")),
    # --- install ---
    ("install packages",        ("install", "writes-fs")),
    # --- convert (read → stdout or output file, no in-place) ---
    ("convert",                 ("convert", "none")),
    ("transcode",               ("convert", "none")),
    ("codec",                  ("convert", "none")),       # media transcoders (ffmpeg family)
    ("input formats",          ("convert", "none")),       # format-conversion tools (pandoc family)
    ("output formats",         ("convert", "none")),       # format-conversion tools
    # --- extract (read text/metadata out of files) ---
    ("extract text",            ("extract", "none")),
    ("text extractor",          ("extract", "none")),
    ("extracts text",           ("extract", "none")),
    ("extract",                ("extract", "none")),        # generic extraction
    ("editing meta",           ("extract", "none")),        # metadata read/edit tools (exiftool family)
    # --- build ---
    ("generate documentation",  ("build",   "writes-fs")),
    ("documentation build",     ("build",   "writes-fs")),
    ("build",                  ("build",   "writes-fs")),   # generic build/site/doc builders
    # --- package / bundle (often co-occurs with build) ---
    ("bundle",                 ("package", "writes-fs")),   # any bundler/packager
    ("package everything",     ("package", "writes-fs")),   # any packaging tool
    ("freeze",                 ("package", "writes-fs")),   # freezers (pyinstaller/cx_Freeze family)
    # --- summarize ---
    ("summarize",               ("summarize", "none")),
    ("summarization",           ("summarize", "none")),
    ("summarizer",             ("summarize", "none")),      # any summarizer
]

# Strong "writes-fs" signals that override a "none" side_effect assignment.
# CONSERVATIVE: only clear "writes in place" semantics. Avoid "output file"
# (too common as a flag-description label) and "overwrite original"
# (exiftool has this but the golden label is "none" — it reads by default).
_WRITES_FS_SIGNALS = (
    "in place",
    "in-place",
    "--in-place",
    "-i, --in-place",
    "overwrite contents",
    "writes to disk",
    "rewriting them in place",
)

# Strong network signals.
_NETWORK_SIGNALS = (
    "index-url",
    "fetch http",
    "repository_url",
    "repository-url",
)


def infer_python_capability(rec: CliRecord) -> Optional[CapabilityRecord]:
    """Guess from --help/argparse metadata. Always confidence='inferred' when it
    returns a record. Returns None when no deterministic heuristic matches.
    Held to the §9 precision/recall floor against golden ground-truth."""
    text = (rec.description or "").lower()
    if not text:
        return None

    seen_tags: list[str] = []
    side_effect = "unknown"

    for kw, (tag, se) in _INTENT_SIGNALS:
        if kw in text:
            if tag not in seen_tags:
                seen_tags.append(tag)
            # First non-"none" side_effect from a match wins; "none" only applies
            # if no stronger signal has already been recorded.
            if side_effect == "unknown" or (side_effect == "none" and se != "none"):
                side_effect = se

    if not seen_tags:
        return None

    # Override side_effect with strong writes-fs signals if not already network.
    if side_effect != "network":
        if any(s in text for s in _WRITES_FS_SIGNALS):
            side_effect = "writes-fs"

    # Override side_effect with strong network signals if still unknown/none.
    if side_effect in ("unknown", "none"):
        if any(s in text for s in _NETWORK_SIGNALS):
            side_effect = "network"

    return CapabilityRecord(
        intent_tags=seen_tags,
        input_types=[],
        output_types=[],
        side_effect=side_effect,
        confidence="inferred",
    )
