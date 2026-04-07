from tools.ugen_parser import Param, Signature


def test_param_defaults():
    p = Param(name="freq", rate="ab")
    assert p.name == "freq"
    assert p.rate == "ab"
    assert p.chans == 0


def test_param_fixed_chans():
    p = Param(name="input", rate="a", chans=2)
    assert p.chans == 2


def test_signature_defaults():
    s = Signature(
        name="sine",
        params=[Param("freq", "ab"), Param("amp", "ab")],
        output_rate="a",
    )
    assert s.name == "sine"
    assert s.output_chans == 0
    assert s.interpolated == []
    assert s.terminate == []
