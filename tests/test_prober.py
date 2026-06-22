from core.prober.prober import probe_one


def test_probe_healthy_on_zero_exit():
    assert probe_one("true") == "healthy"


def test_probe_unhealthy_on_nonzero_exit():
    assert probe_one("false") == "unhealthy"


def test_probe_unhealthy_on_timeout():
    # sleeps longer than the timeout -> killed -> unhealthy, does not hang
    assert probe_one("sleep 5", timeout=0.5) == "unhealthy"
