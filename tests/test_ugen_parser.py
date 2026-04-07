from tools.ugen_parser import Param, Signature, parse_signature_line


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


def test_parse_simple_signature():
    sig = parse_signature_line("sine(freq: ab, amp: ab): a")
    assert sig.name == "sine"
    assert sig.output_rate == "a"
    assert sig.output_chans == 0
    assert len(sig.params) == 2
    assert sig.params[0] == Param("freq", "ab")
    assert sig.params[1] == Param("amp", "ab")


def test_parse_block_rate_signature():
    sig = parse_signature_line("sineb(freq: b, amp: b): b")
    assert sig.name == "sineb"
    assert sig.output_rate == "b"
    assert sig.params[0] == Param("freq", "b")


def test_parse_fixed_channels():
    sig = parse_signature_line("overdrive(snd: 2a, gain: b, tone: b, volume: b): 2a")
    assert sig.name == "overdrive"
    assert sig.output_chans == 2
    assert sig.output_rate == "a"
    assert sig.params[0] == Param("snd", "a", chans=2)
    assert sig.params[1] == Param("gain", "b")


def test_parse_constant_params():
    sig = parse_signature_line("sttest(input: 2a, hz1: c, hz2: c): 2a")
    assert sig.name == "sttest"
    assert sig.params[1] == Param("hz1", "c")
    assert sig.params[2] == Param("hz2", "c")


def test_parse_many_block_params():
    sig = parse_signature_line(
        "noisegate(input: a, threshold: b, attack: b, hold: b, release: b): a"
    )
    assert sig.name == "noisegate"
    assert sig.output_rate == "a"
    assert len(sig.params) == 5
    assert sig.params[0] == Param("input", "a")
    assert sig.params[4] == Param("release", "b")


def test_parse_no_spaces():
    sig = parse_signature_line("sine(freq:ab,amp:ab):a")
    assert sig.name == "sine"
    assert sig.params[0] == Param("freq", "ab")
    assert sig.output_rate == "a"
