from arco_ugens import Smoothb
from conftest import addresses


def test_smoothb_constructs_without_error(engine):
    sm = Smoothb(0.5)
    assert sm.chans == 1
    assert "/arco/smoothb/newn" in addresses(engine)


def test_smoothb_newn_sends_cutoff_then_all_values(engine):
    sm = Smoothb(0.5, cutoff=7)
    msg = [m for m in engine.o2lite.messages
           if m[0] == "/arco/smoothb/newn"][-1]
    assert msg[1] == "iff"  # id, cutoff, x0 -- server needs argc > 2
    assert msg[2] == (sm.id, 7, 0.5)


def test_smoothb_multichannel(engine):
    sm = Smoothb([0.1, 0.2, 0.3], cutoff=10)
    assert sm.chans == 3
    msg = [m for m in engine.o2lite.messages
           if m[0] == "/arco/smoothb/newn"][-1]
    assert msg[1] == "iffff"
    assert msg[2] == (sm.id, 10, 0.1, 0.2, 0.3)
