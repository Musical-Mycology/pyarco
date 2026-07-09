"""The demo must keep polling O2 after connect: o2lite clients that stop
polling miss clock-sync pings and get dropped by the Arco server."""

import importlib
import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class CountingEngine:
    def __init__(self):
        self.polls = 0

    def poll(self):
        self.polls += 1


class ExplodingEngine:
    def poll(self):
        raise RuntimeError("socket gone")


def _load_init():
    """Import (or re-import) the demo module without starting the server."""
    import init
    return importlib.reload(init)


def test_import_does_not_start_server():
    # ui.run() blocks forever; importing must not reach it.
    _load_init()


def test_page_is_registered_not_script_mode():
    # NiceGUI 3 "script mode" (no @ui.page) re-executes the whole module
    # for EVERY browser client: each tab gets its own DemoState/engine,
    # they collide on server ugen ids, and one tab's Connect breaks
    # another tab's audio. build_page must be a registered page builder.
    init = _load_init()
    from nicegui import Client
    assert Client.page_routes.get(init.build_page) == '/'


def test_poll_timer_registered():
    init = _load_init()
    assert init._poll_timer is not None


def test_poll_callback_polls_engine_when_connected():
    init = _load_init()
    engine = CountingEngine()
    init.state.engine = engine
    init.state.connected = True
    init._poll_arco()
    init._poll_arco()
    assert engine.polls == 2


def test_poll_callback_noop_when_disconnected():
    init = _load_init()
    init.state.engine = None
    init.state.connected = False
    init._poll_arco()  # must not raise


def test_poll_failure_marks_disconnected():
    init = _load_init()
    init.state.engine = ExplodingEngine()
    init.state.connected = True
    init._poll_arco()  # must not raise
    assert init.state.connected is False


class ClosableEngine:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_shutdown_closes_engine():
    # Without close-on-shutdown, a restarted demo collides with the dead
    # session's server-side ugens and the server ignores sum inserts.
    init = _load_init()
    engine = ClosableEngine()
    init.state.engine = engine
    init.state.connected = True
    init._shutdown_arco()
    assert engine.closed
    assert init.state.connected is False
