"""End-to-end construction of a Supersaw voice.

Supersaw_instr builds block-rate modulation from Const inputs (e.g.
``Mathb(MATH_OP_SUB, self.pitch_const, ldp)``), so it exercises the exact
rate-guard path that used to reject c-rate Const inputs. This test drives a full
``noteon``/``noteoff`` cycle offline to guard against regressions.
"""

import arco_instr
from arco_instr import Supersaw_synth


def test_supersaw_noteon_noteoff_cycle(engine):
    # Wavetables are cached in a module global; reset so the voice is built
    # against this test's engine and the test is order-independent.
    arco_instr._sawtooth_waveforms = None

    synth = Supersaw_synth({})

    instr = synth.noteon(60, 100)
    assert instr is not None
    assert instr.id is not None
    # A default supersaw has n detuned oscillator components.
    assert len(instr.components) == instr.n
    assert instr.n >= 1

    synth.noteoff(60)
    assert 60 not in synth.notes


def test_supersaw_multiple_voices(engine):
    arco_instr._sawtooth_waveforms = None

    synth = Supersaw_synth({})
    a = synth.noteon(60, 100)
    b = synth.noteon(64, 90)

    assert a.id is not None and b.id is not None
    assert a.id != b.id

    synth.noteoff(60)
    synth.noteoff(64)
    assert synth.notes == {}
