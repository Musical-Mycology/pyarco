from arco_ugens import Smoothb
from conftest import addresses


def test_smoothb_constructs_without_error(engine):
    sm = Smoothb(0.5)
    assert sm.chans == 1
    assert "/arco/smoothb/newn" in addresses(engine)


def test_smoothb_multichannel(engine):
    sm = Smoothb([0.1, 0.2, 0.3])
    assert sm.chans == 3
