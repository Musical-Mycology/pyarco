"""Shared pytest fixtures for offline PyArco tests.

These let ugen construction and messaging run without a live Arco server: a
``FakeO2Lite`` records every command instead of putting bytes on the wire, and
the ``engine`` fixture installs an ``ArcoEngine`` wired to it as the active
engine (mirroring ``ArcoEngine.connect()`` minus the network handshake).
"""

import os
import sys

# Put the flat python25 module dir on sys.path so tests can `import arco_engine`
# etc. the same way the application modules import each other.
_PYTHON25 = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PYTHON25 not in sys.path:
    sys.path.insert(0, _PYTHON25)


def _ensure_o2litepy_importable():
    """Make ``o2lite`` importable regardless of checkout location.

    arco_engine hardcodes o2litepy at ``../../o2/o2litepy/src`` relative to
    itself, which only resolves when the repo sits directly beside the ``o2``
    checkout. Running from a git worktree (nested under ``.claude/worktrees/``)
    breaks that path, so walk up the tree to find ``o2/o2litepy/src``.
    """
    try:
        import o2lite  # noqa: F401
        return
    except ImportError:
        pass
    directory = os.path.dirname(os.path.abspath(__file__))
    while True:
        candidate = os.path.join(directory, "o2", "o2litepy", "src")
        if os.path.isdir(candidate):
            sys.path.insert(0, candidate)
            return
        parent = os.path.dirname(directory)
        if parent == directory:
            return  # not found; let the import fail with its normal message
        directory = parent


_ensure_o2litepy_importable()

import pytest

import arco_engine
from arco_engine import (
    ArcoEngine, A_RATE, B_RATE, ZERO_ID, ZEROB_ID, INPUT_ID, OUTPUT_ID,
)
from arco_ugens import Ugen, Sum


class FakeO2Lite:
    """Minimal stand-in for the O2lite transport.

    Records every ``send_cmd`` call in ``self.sent`` instead of transmitting,
    so ugen construction can be exercised entirely offline.
    """

    def __init__(self):
        self.sent = []

    def send_cmd(self, *args):
        self.sent.append(args)

    def poll(self):
        pass

    def time_get(self):
        return 0.0


@pytest.fixture
def engine():
    """An ``ArcoEngine`` backed by a ``FakeO2Lite`` and set as the active engine.

    Recreates the system ugens at IDs 0-3 exactly as ``connect()`` does, then
    tears everything down so tests don't leak the global active-engine state.
    """
    eng = ArcoEngine()
    eng.o2lite = FakeO2Lite()
    prev = arco_engine._active_engine
    arco_engine._active_engine = eng

    # System ugen shadows, exactly as connect() creates them.
    eng.zero = Ugen("Zero", 1, A_RATE, "", no_msg=True, engine=eng,
                    id_num=ZERO_ID)
    eng.zerob = Ugen("Zerob", 1, B_RATE, "", no_msg=True, engine=eng,
                     id_num=ZEROB_ID)
    eng.input = Ugen("Thru", eng.input_chans, A_RATE, "", no_msg=True,
                     engine=eng, id_num=INPUT_ID)
    eng.output = Sum(eng.output_chans, True, OUTPUT_ID)

    try:
        yield eng
    finally:
        eng.close()
        arco_engine._active_engine = prev
