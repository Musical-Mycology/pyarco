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
