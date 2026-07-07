import gc

from arco_instr import Instrument, instr_begin
from arco_ugens import Sine
from conftest import pool_free_count


def test_instrument_borrows_output_id_and_leaks_no_slot(engine):
    free_before = pool_free_count(engine)
    instr_begin()
    out = Sine(440, 0.5)
    instr = Instrument("TestInstr", out)
    assert instr.id == out.id
    assert instr.owns_id is False
    # Slots consumed: Sine + its two auto-wrapped Consts. Nothing more.
    assert free_before - pool_free_count(engine) == 3


def test_instrument_del_does_not_free_borrowed_id(engine):
    instr_begin()
    out = Sine(440, 0.5)
    instr = Instrument("TestInstr", out)
    shared_id = out.id
    del instr
    gc.collect()
    # The output ugen still owns the slot: it must remain occupied.
    assert engine.id_pool.array[shared_id] is None  # None == occupied


def test_id_num_ugens_are_not_registered(engine):
    from arco_engine import OUTPUT_ID
    from arco_ugens import Sum
    s = Sum(2, True, id_num=OUTPUT_ID)
    assert s.owns_id is False
    assert OUTPUT_ID not in engine._ugens
