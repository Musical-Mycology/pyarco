import arco_instr


def test_sawtooth_singleton_rebuilds_on_new_engine(make_engine):
    make_engine()
    saw1 = arco_instr.get_sawtooth_waveforms()
    assert arco_instr.get_sawtooth_waveforms() is saw1
    make_engine()  # becomes the new active engine
    saw2 = arco_instr.get_sawtooth_waveforms()
    assert saw2 is not saw1
