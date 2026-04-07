# tests/test_validation.py
"""Validate generated classes match hand-written equivalents in arco.py."""
from tools.ugen_parser import Param, Signature
from tools.ugen_codegen import generate_class


def test_sine_matches_handwritten():
    sig = Signature(
        name="sine",
        params=[Param("freq", "ab"), Param("amp", "ab")],
        output_rate="a",
    )
    code = generate_class(sig)
    assert '"UU"' in code
    assert "'freq', freq" in code
    assert "'amp', amp" in code
    assert "A_RATE" in code
    assert "isinstance" not in code


def test_sineb_matches_handwritten():
    sig = Signature(
        name="sineb",
        params=[Param("freq", "b"), Param("amp", "b")],
        output_rate="b",
    )
    code = generate_class(sig)
    assert '"UU"' in code
    assert "B_RATE" in code
    assert "freq.rate != B_RATE" in code
    assert "amp.rate != B_RATE" in code


def test_lowpass_matches_handwritten():
    """lowpass(input: a, cutoff: ab): a — input gets A_RATE check, cutoff doesn't."""
    sig = Signature(
        name="lowpass",
        params=[Param("input", "a"), Param("cutoff", "ab")],
        output_rate="a",
    )
    code = generate_class(sig)
    assert '"UU"' in code
    assert "input.rate != A_RATE" in code
    assert "cutoff.rate" not in code


def test_reson_matches_handwritten():
    """reson(input: a, center: ab, q: ab): a"""
    sig = Signature(
        name="reson",
        params=[Param("input", "a"), Param("center", "ab"), Param("q", "ab")],
        output_rate="a",
    )
    code = generate_class(sig)
    assert '"UUU"' in code
    assert "input.rate != A_RATE" in code
    assert "center.rate" not in code
    assert "q.rate" not in code
    assert "max_chans(max_chans(max_chans(1, input), center), q)" in code


def test_resonb_matches_handwritten():
    """resonb(input: b, center: b, q: b): b — all three get B_RATE checks."""
    sig = Signature(
        name="resonb",
        params=[Param("input", "b"), Param("center", "b"), Param("q", "b")],
        output_rate="b",
    )
    code = generate_class(sig)
    assert '"UUU"' in code
    assert "input.rate != B_RATE" in code
    assert "center.rate != B_RATE" in code
    assert "q.rate != B_RATE" in code
