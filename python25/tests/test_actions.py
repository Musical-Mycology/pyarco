import gc

from arco_engine import ACTION_END, ACTION_END_OR_TERM, ACTION_FREE
from arco_ugens import Sine


def test_action_target_does_not_pin_ugen(engine):
    s = Sine(440, 0.5)
    sid = s.id
    engine.register_action(s, ACTION_END_OR_TERM, s, 'mute')
    del s
    gc.collect()
    assert engine._ugens.get(sid) is None


def test_handler_calls_live_target(engine):
    calls = []

    class Target:
        def mute(self, status):
            calls.append(status)

    s = Sine(440, 0.5)
    t = Target()
    engine.register_action(s, ACTION_END_OR_TERM, t, 'mute')
    engine.actl_act_handler(0, "/actl/act", "iii", s.action_id, ACTION_END, 0)
    assert calls == [ACTION_END]


def test_handler_prunes_dead_targets(engine):
    s = Sine(440, 0.5)
    engine.register_action(s, ACTION_END_OR_TERM, s, 'mute')
    aid = s.action_id
    del s
    gc.collect()
    engine.actl_act_handler(0, "/actl/act", "iii", aid, ACTION_END, 0)
    assert engine.action_dict[aid].ugen_actions == []


def test_action_free_removes_entry(engine):
    s = Sine(440, 0.5)
    engine.register_action(s, ACTION_END_OR_TERM, s, 'mute')
    aid = s.action_id
    engine.actl_act_handler(0, "/actl/act", "iii", aid, ACTION_FREE, 0)
    assert aid not in engine.action_dict
