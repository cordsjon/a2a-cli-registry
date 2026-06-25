from core.remediation.paperclip_adapter import (
    PaperclipAdapter, cluster_hash,
)
from core.remediation.proposal import (
    SCHEMA_VERSION, RemediationProposal, FailureClass, FixKind, Confidence,
)


def _p(slug, fc, fk, target):
    return RemediationProposal(
        schema_version=SCHEMA_VERSION, slug=slug, failure_class=fc, fix_kind=fk,
        target=target, confidence=Confidence.DECLARED_BY_REGEX, evidence="e")


class FakeClient:
    def __init__(self, available=True, open_hashes=None):
        self._available = available
        self._open = open_hashes or set()
        self.created = []
    def available(self):
        return self._available
    def list_open_hashes(self):
        return set(self._open)
    def bulk_create(self, yaml_text):
        self.created.append(yaml_text)


def test_cluster_hash_is_order_independent():
    h1 = cluster_hash("wrong-cwd", "syllabus_v2", ["b", "a", "c"])
    h2 = cluster_hash("wrong-cwd", "syllabus_v2", ["c", "b", "a"])
    assert h1 == h2
    assert len(h1) == 12


def test_clusters_by_class_and_target():
    props = [
        _p("a", FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "syllabus_v2"),
        _p("b", FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "syllabus_v2"),
        _p("c", FailureClass.PIP_UNKNOWN, FixKind.PROPOSE_ONLY, "romsorter"),
    ]
    client = FakeClient()
    refs = PaperclipAdapter(client, session_id="s1").file(props, dry_run=True)
    # 2 clusters: (wrong-cwd, syllabus_v2) with 2 members, (pip-unknown, romsorter) with 1
    by_members = sorted(len(r["members"]) for r in refs)
    assert by_members == [1, 2]


def test_dry_run_default_writes_no_issue():
    client = FakeClient()
    PaperclipAdapter(client, session_id="s1").file(
        [_p("a", FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "x")])  # dry_run defaults True
    assert client.created == []


def test_actual_file_shells_bulk_create():
    client = FakeClient()
    PaperclipAdapter(client, session_id="s1").file(
        [_p("a", FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "x")], dry_run=False)
    assert len(client.created) == 1


def test_existing_open_hash_is_skipped():
    props = [_p("a", FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "x")]
    h = cluster_hash("wrong-cwd", "x", ["a"])
    client = FakeClient(open_hashes={h})
    refs = PaperclipAdapter(client, session_id="s1").file(props, dry_run=False)
    assert refs == []  # already open -> skipped
    assert client.created == []


def test_needs_human_proposals_are_filed():
    props = [_p("a", FailureClass.UNKNOWN, FixKind.NEEDS_HUMAN, "")]
    client = FakeClient()
    refs = PaperclipAdapter(client, session_id="s1").file(props, dry_run=True)
    assert len(refs) == 1


def test_auto_safe_proposals_excluded():
    props = [_p("a", FailureClass.PIP_3RD_PARTY, FixKind.AUTO_SAFE, "numpy")]
    client = FakeClient()
    refs = PaperclipAdapter(client, session_id="s1").file(props, dry_run=True)
    assert refs == []


def test_missing_paperclip_warns_and_skips(capsys):
    props = [_p("a", FailureClass.WRONG_CWD, FixKind.PROPOSE_ONLY, "x")]
    client = FakeClient(available=False)
    refs = PaperclipAdapter(client, session_id="s1").file(props, dry_run=False)
    assert refs == []
    assert client.created == []
