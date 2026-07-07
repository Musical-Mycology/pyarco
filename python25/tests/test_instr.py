import arco_instr


def test_sawtooth_singleton_rebuilds_on_new_engine(make_engine):
    make_engine()
    saw1 = arco_instr.get_sawtooth_waveforms()
    assert arco_instr.get_sawtooth_waveforms() is saw1
    make_engine()  # becomes the new active engine
    saw2 = arco_instr.get_sawtooth_waveforms()
    assert saw2 is not saw1


import threading

from arco_instr import Instrument, instr_begin, param
from arco_ugens import Sine


def test_instr_construction_is_thread_isolated(engine):
    instr_begin()          # main thread starts a construction...
    param('gain', 0.5)     # ...with one pending param
    result = {}

    def build_in_worker():
        instr_begin()
        param('freq', 440)
        out = Sine(440, 0.5)
        result['instr'] = Instrument("Worker", out)

    t = threading.Thread(target=build_in_worker)
    t.start()
    t.join()
    assert 'freq' in result['instr'].parameter_bindings
    assert 'gain' not in result['instr'].parameter_bindings
    # main thread's pending construction is untouched
    out2 = Sine(220, 0.5)
    instr2 = Instrument("Main", out2)
    assert 'gain' in instr2.parameter_bindings


def test_instr_construction_interleaved_threads(engine):
    """Two constructions genuinely interleaved mid-flight: the worker
    pushes its context, then the MAIN thread finishes its own
    construction while the worker is paused. A shared LIFO stack would
    hand main the worker's context."""
    worker_pushed = threading.Event()
    main_done = threading.Event()
    result = {}

    def build_in_worker():
        instr_begin()
        param('freq', 440)
        worker_pushed.set()
        main_done.wait(5)
        out = Sine(440, 0.5)
        result['instr'] = Instrument("Worker", out)

    instr_begin()
    param('gain', 0.5)
    t = threading.Thread(target=build_in_worker)
    t.start()
    worker_pushed.wait(5)
    out2 = Sine(220, 0.5)
    instr_main = Instrument("Main", out2)
    main_done.set()
    t.join()
    assert 'gain' in instr_main.parameter_bindings
    assert 'freq' not in instr_main.parameter_bindings
    assert 'freq' in result['instr'].parameter_bindings
    assert 'gain' not in result['instr'].parameter_bindings


def test_missing_instr_begin_raises_without_leaking(engine):
    import pytest
    from arco_instr import _instr_stacks
    out = Sine(440, 0.5)
    with pytest.raises(RuntimeError):
        Instrument("NoBegin", out)
    assert threading.get_ident() not in _instr_stacks
