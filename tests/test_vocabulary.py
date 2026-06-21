from core.vocabulary import VocabularyRegistry


def test_alias_canonicalizes_before_admission():
    v = VocabularyRegistry(registered={"file:pdf", "text"}, aliases={"pdf": "file:pdf", "PDF": "file:pdf"})
    assert v.canonicalize("pdf") == "file:pdf"
    assert v.admit("PDF") == ("file:pdf", True)


def test_unregistered_port_quarantined():
    v = VocabularyRegistry(registered={"text"}, aliases={})
    canonical, registered = v.admit("file:weird")
    assert registered is False
    assert canonical == "unverified:file:weird"
    assert v.is_edge_eligible("unverified:file:weird") is False


def test_namespaced_types_distinct_do_not_collide():
    v = VocabularyRegistry(registered={"json:invoice", "json:resume"}, aliases={})
    assert v.admit("json:invoice") == ("json:invoice", True)
    assert v.admit("json:resume") == ("json:resume", True)
    # they are distinct registered ports; matching is exact-string elsewhere
