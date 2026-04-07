from tools.ugen_parser import Param, Signature
from tools.ugen_codegen import generate_class


def test_generate_sine():
    sig = Signature(
        name="sine",
        params=[Param("freq", "ab"), Param("amp", "ab")],
        output_rate="a",
    )
    code = generate_class(sig)
    assert "class Sine(Ugen):" in code
    assert "def __init__(self, freq, amp, chans=None):" in code
    assert 'chans = max_chans(max_chans(1, freq), amp)' in code
    assert 'super().__init__("Sine", chans, A_RATE, "UU", None, None,' in code
    assert "'freq', freq," in code
    assert "'amp', amp)" in code
    # No rate validation for ab params
    assert "ERROR" not in code
    assert "isinstance" not in code


def test_generate_sineb():
    sig = Signature(
        name="sineb",
        params=[Param("freq", "b"), Param("amp", "b")],
        output_rate="b",
    )
    code = generate_class(sig)
    assert "class Sineb(Ugen):" in code
    assert "B_RATE" in code
    assert "if not isinstance(freq, (int, float)) and freq.rate != B_RATE:" in code
    assert "if not isinstance(amp, (int, float)) and amp.rate != B_RATE:" in code
    assert "ERROR: 'freq' input to Ugen 'sineb' must be block rate" in code


def test_generate_lowpass_audio_rate_check():
    sig = Signature(
        name="lowpass",
        params=[Param("input", "a"), Param("cutoff", "ab")],
        output_rate="a",
    )
    code = generate_class(sig)
    assert "class Lowpass(Ugen):" in code
    # input: a gets checked
    assert "if not isinstance(input, (int, float)) and input.rate != A_RATE:" in code
    # cutoff: ab does NOT get checked
    assert "cutoff.rate" not in code
