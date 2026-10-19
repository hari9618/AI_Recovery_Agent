from app.observability.tracing import Tracer


class ExplodingClient:
    """Simulates Langfuse being down / misconfigured: every SDK call raises."""

    def __getattr__(self, name):
        def boom(*a, **k):
            raise RuntimeError(f"langfuse down: {name}")

        return boom


def test_null_tracer_is_noop():
    t = Tracer(None)
    with t.trace("x") as root, t.observation("y", as_type="tool") as span:
        span.update(output={"a": 1})
        root.score("s", 1.0)
    assert not t.enabled and t.trace_url("abc") is None


def test_broken_langfuse_never_breaks_business_code():
    t = Tracer(ExplodingClient())
    result = None
    with t.trace("RevenueRecovery", user_id="u") as root, t.observation("step", as_type="generation", model="m") as obs:
        obs.update(output="ok")
        obs.error("bad")
        result = 42
    root.update(output="done")
    t.score_trace("tid", "x", 1.0)
    t.flush()
    assert result == 42
    assert t.health()["reachable"] is False


def test_exceptions_in_body_still_propagate():
    t = Tracer(None)
    try:
        with t.observation("x"):
            raise KeyError("business error")
    except KeyError:
        pass
    else:
        raise AssertionError("exception swallowed")
