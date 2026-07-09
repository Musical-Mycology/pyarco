"""connect() must attach to a running server without destructive messages:
no /arco/reset (refused + warning while audio runs) and no /arco/free of
OUTPUT_ID (the audio callback warns during the free/create gap). The output
Sum lives at a pool id, spliced in via one /arco/thru/repl_input."""

import os
import sys
import types

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import arco_engine
from arco_engine import ArcoEngine, OUTPUT_ID, ZERO_ID


class FakeConnectedO2Lite:
    """Stands in for o2lite.O2lite: already clock-synced, records sends."""

    def __init__(self):
        self.messages = []

    def initialize(self, ensemble, debug_flags=""):
        self.ensemble = ensemble

    def time_get(self):
        return 1.0  # clock sync already complete

    def poll(self):
        pass

    def send_cmd(self, address, time, type_string, *params):
        self.messages.append((address, type_string, params))


@pytest.fixture
def connected_engine(monkeypatch):
    fake_module = types.ModuleType("o2lite")
    fake_module.O2lite = FakeConnectedO2Lite
    monkeypatch.setitem(sys.modules, "o2lite", fake_module)
    eng = ArcoEngine()
    eng.connect()
    yield eng
    for ugen in list(eng._ugens.values()):
        ugen.engine = None
    for attr in (eng.zero, eng.zerob, eng.input, eng.output):
        if attr is not None:
            attr.engine = None
    arco_engine._active_engine = None


def addresses(eng):
    return [m[0] for m in eng.o2lite.messages]


def test_connect_sends_no_reset_or_free(connected_engine):
    sent = addresses(connected_engine)
    assert "/arco/reset" not in sent
    assert "/arco/free" not in sent


def test_connect_splices_pool_sum_into_output_thru(connected_engine):
    eng = connected_engine
    assert eng.output is not None
    assert eng.output.id != OUTPUT_ID  # pool id, system ugen untouched
    assert ("/arco/thru/repl_input", "ii",
            (OUTPUT_ID, eng.output.id)) in eng.o2lite.messages


def test_play_targets_engine_output_sum(connected_engine):
    from arco_ugens import Sine
    eng = connected_engine
    s = Sine(440, 0.1)
    s.play()
    assert ("/arco/sum/ins", "ii",
            (eng.output.id, s.id)) in eng.o2lite.messages
    s.mute()
    assert ("/arco/sum/rem", "ii",
            (eng.output.id, s.id)) in eng.o2lite.messages


def test_close_detaches_output_before_freeing(monkeypatch):
    fake_module = types.ModuleType("o2lite")
    fake_module.O2lite = FakeConnectedO2Lite
    monkeypatch.setitem(sys.modules, "o2lite", fake_module)
    eng = ArcoEngine()
    eng.connect()
    transport = eng.o2lite
    sum_id = eng.output.id
    eng.close()
    detach = transport.messages.index(
        ("/arco/thru/repl_input", "ii", (OUTPUT_ID, ZERO_ID)))
    free = transport.messages.index(("/arco/free", "i", (sum_id,)))
    assert detach < free  # detach from output Thru, then free the Sum
    arco_engine._active_engine = None
