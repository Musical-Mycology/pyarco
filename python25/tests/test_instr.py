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
