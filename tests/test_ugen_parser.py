from pathlib import Path

from tools.ugen_parser import Param, Signature, parse_signature_line, parse_ugen_file

FIXTURES = Path(__file__).parent / "fixtures"


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


def test_parse_sine_ugen():
    sigs = parse_ugen_file(FIXTURES / "sine.ugen")
    assert len(sigs) == 2
    assert sigs[0].name == "sine"
    assert sigs[0].output_rate == "a"
    assert sigs[0].interpolated == ["freq", "amp"]
    assert sigs[1].name == "sineb"
    assert sigs[1].output_rate == "b"
    assert sigs[1].interpolated == ["freq", "amp"]


def test_parse_lowpass_ugen():
    sigs = parse_ugen_file(FIXTURES / "lowpass.ugen")
    assert len(sigs) == 2
    assert sigs[0].name == "lowpass"
    assert sigs[0].terminate == ["input"]
    assert sigs[1].name == "lowpassb"
    assert sigs[1].terminate == ["input"]


def test_parse_overdrive_ugen():
    sigs = parse_ugen_file(FIXTURES / "overdrive.ugen")
    assert len(sigs) == 1
    assert sigs[0].name == "overdrive"
    assert sigs[0].output_chans == 2
    assert sigs[0].params[0] == Param("snd", "a", chans=2)
    assert sigs[0].interpolated == ["gain", "tone", "volume"]


def test_parse_sttest_ugen():
    sigs = parse_ugen_file(FIXTURES / "sttest.ugen")
    assert len(sigs) == 1
    assert sigs[0].params[1] == Param("hz1", "c")
    assert sigs[0].interpolated == []


def test_parse_noisegate_ugen():
    sigs = parse_ugen_file(FIXTURES / "noisegate.ugen")
    assert len(sigs) == 1
    assert sigs[0].name == "noisegate"
    assert len(sigs[0].params) == 5
    assert sigs[0].interpolated == ["threshold", "attack", "hold", "release"]
