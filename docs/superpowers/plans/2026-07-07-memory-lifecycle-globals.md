# PyArco Memory Lifecycle & Globals Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the audited memory/lifecycle defects in PyArco so ugen IDs are reclaimed during a session (weak-reference registry + `__del__` free path), Instruments stop leaking pool slots, and Arco-related globals are single-sourced and engine/thread-safe — all covered by a new offline pytest suite.

**Architecture:** The engine's ugen registry becomes a `weakref.WeakValueDictionary` so Python refcounting drives `/arco/free`. Because the server-side graph must be mirrored by Python references, container ugens (`Sum`/`Sumb`/`Add`/`Addb`/`Route`/`Stdistr`) and `play()`/`fade()` gain client-side member tracking *before* the weak flip. `Ugen` gains an `owns_id` flag so Instruments borrow their output's ID instead of leaking a slot. Tests run against a `FakeO2Lite` transport recorded in-process — no Arco server, no o2litepy needed.

**Tech Stack:** Python 3 stdlib (`weakref`, `threading`, `logging`), pytest (via project venv). No new runtime dependencies.

**Audit finding → task map:** F3 Smoothb crash → Task 2; F4 ACTION constants → Task 3; F1 registry/`__del__` → Tasks 4+6; F2 Instrument slot leak → Task 5; F5 action-target weakrefs → Task 7; F6 sawtooth singleton → Task 8; F7 `_instr_stack` → Task 9; hygiene → Task 10; F8 + docs → Task 11.

---

## File Structure

- `python25/arco_engine.py` — modify: deferred o2lite import, weak registry, action weakrefs, `close()` cleanup, dead import removal
- `python25/arco_ugens.py` — modify: Smoothb fix, member tracking, `owns_id`, `_server_freed`, `_addr_prefix`, logging
- `python25/arco_instr.py` — modify: constants import, Instrument id borrow, per-thread instr stacks, sawtooth accessor
- `python25/tests/conftest.py` — create: fixtures (`FakeO2Lite`, engine factory, pool helper)
- `python25/tests/test_smoke.py` — create (Task 1)
- `python25/tests/test_ugens.py` — create (Tasks 2, 4)
- `python25/tests/test_constants.py` — create (Task 3)
- `python25/tests/test_lifecycle.py` — create (Tasks 5, 6)
- `python25/tests/test_actions.py` — create (Task 7)
- `python25/tests/test_instr.py` — create (Tasks 8, 9)
- `PyArcoCONTEXT.md`, `CLAUDE.md` — modify (Task 11)

All test commands below assume the repo-root venv created in Task 1:
`.venv/bin/python -m pytest python25/tests -v`

---

### Task 1: Test infrastructure + deferred o2lite import

The o2litepy `sys.path` hack resolves relative to the source file and breaks in worktrees; the module-level `from o2lite import O2lite` makes `arco_engine` unimportable without it. Defer the import into `connect()` (the only user), then build the pytest harness.

**Files:**
- Modify: `python25/arco_engine.py:11` (remove top-level import), `python25/arco_engine.py:293` (import inside `connect`)
- Create: `python25/tests/conftest.py`, `python25/tests/test_smoke.py`

- [ ] **Step 1: Create venv and install pytest**

```bash
cd /Users/chris/projects/pyarco/.claude/worktrees/eager-bose-4ddd15
python3 -m venv .venv
.venv/bin/pip install pytest
echo ".venv/" >> .gitignore
```

Run: `.venv/bin/python -m pytest --version` — Expected: `pytest 8.x`

- [ ] **Step 2: Defer the o2lite import in arco_engine.py**

Delete line 11 (`from o2lite import O2lite`). Keep the `sys.path.append(...)` block (lines 7–9) — it's still needed at connect time. In `connect()`, add the import right after the existing deferred import:

```python
    def connect(self):
        """Connect to Arco server, create system ugens, set as active engine."""
        if self.o2lite is not None:
            return  # already connected
        from arco_ugens import Ugen, Sum  # deferred to break circular import
        from o2lite import O2lite  # deferred so the library imports without o2litepy

        self.o2lite = O2lite()
```

- [ ] **Step 3: Write conftest.py**

Create `python25/tests/conftest.py`:

```python
import gc
import os
import sys

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import arco_engine
from arco_engine import ArcoEngine


class FakeO2Lite:
    """Records every O2 message instead of sending it."""

    def __init__(self):
        self.messages = []  # (address, type_string, params) tuples

    def send_cmd(self, address, time, type_string, *params):
        self.messages.append((address, type_string, params))

    def poll(self):
        pass


def addresses(eng):
    """All O2 addresses sent through this engine's fake transport."""
    return [m[0] for m in eng.o2lite.messages]


def pool_free_count(eng):
    """Walk the UgenID free list and count available slots."""
    count, slot = 0, eng.id_pool.free_head
    while slot is not None:
        count += 1
        slot = eng.id_pool.array[slot]
    return count


@pytest.fixture
def make_engine():
    """Factory for offline engines wired to a FakeO2Lite transport."""
    engines = []

    def _make():
        eng = ArcoEngine()
        eng.o2lite = FakeO2Lite()
        arco_engine._active_engine = eng
        engines.append(eng)
        return eng

    yield _make
    # Detach engines so any surviving ugen's __del__ is a no-op.
    for eng in engines:
        for ugen in list(eng._ugens.values()):
            ugen.engine = None
        for attr in (eng.zero, eng.zerob, eng.input, eng.output):
            if attr is not None:
                attr.engine = None
    arco_engine._active_engine = None
    gc.collect()


@pytest.fixture
def engine(make_engine):
    return make_engine()
```

- [ ] **Step 4: Write the smoke test**

Create `python25/tests/test_smoke.py`:

```python
from arco_ugens import Sine
from conftest import addresses


def test_sine_creation_sends_new_message(engine):
    s = Sine(440, 0.5)
    addrs = addresses(engine)
    assert "/arco/sine/new" in addrs
    assert addrs.count("/arco/const/newn") == 2  # freq and amp auto-wrapped
    assert s.id >= engine.id_pool.start_id
    assert s.inputs["freq"].id != s.inputs["amp"].id
```

- [ ] **Step 5: Run the suite — must pass**

Run: `.venv/bin/python -m pytest python25/tests -v`
Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add python25/arco_engine.py python25/tests/ .gitignore
git commit -m "test: add offline pytest harness with FakeO2Lite; defer o2lite import to connect()"
```

---

### Task 2: Fix Smoothb TypeError (audit finding 3)

`Smoothb.__init__` ends with `return self`, which raises `TypeError: __init__() should return None`. Every construction — including `param(..., smooth=True)` — crashes.

**Files:**
- Modify: `python25/arco_ugens.py:341`
- Test: `python25/tests/test_ugens.py`

- [ ] **Step 1: Write the failing test**

Create `python25/tests/test_ugens.py`:

```python
from arco_ugens import Smoothb
from conftest import addresses


def test_smoothb_constructs_without_error(engine):
    sm = Smoothb(0.5)
    assert sm.chans == 1
    assert "/arco/smoothb/newn" in addresses(engine)


def test_smoothb_multichannel(engine):
    sm = Smoothb([0.1, 0.2, 0.3])
    assert sm.chans == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest python25/tests/test_ugens.py -v`
Expected: FAIL with `TypeError: __init__() should return None, not 'Smoothb'`

- [ ] **Step 3: Fix — delete the return**

In `python25/arco_ugens.py`, `Smoothb.__init__`, delete the line `return self` (line 341). Nothing replaces it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest python25/tests -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add python25/arco_ugens.py python25/tests/test_ugens.py
git commit -m "fix: Smoothb.__init__ raised TypeError by returning self"
```

---

### Task 3: Single-source the ACTION_* constants (audit finding 4)

`arco_instr.py` redefines `ACTION_REM=1, ACTION_TERM=2, ACTION_END=4` which conflict with the engine's `ACTION_TERM=1, ACTION_END=16, ACTION_REM=32`. `Instrument.finish` masks server status with the wrong bits.

**Files:**
- Modify: `python25/arco_instr.py:4-57`
- Test: `python25/tests/test_constants.py`

- [ ] **Step 1: Write the failing test**

Create `python25/tests/test_constants.py`:

```python
import arco_engine
import arco_instr


def test_action_constants_single_sourced():
    assert arco_instr.ACTION_TERM == arco_engine.ACTION_TERM == 1
    assert arco_instr.ACTION_END == arco_engine.ACTION_END == 16
    assert arco_instr.ACTION_REM == arco_engine.ACTION_REM == 32
    assert (arco_instr.ACTION_END_OR_TERM
            == arco_engine.ACTION_END_OR_TERM == 17)


def test_mute_finish_single_sourced():
    assert arco_instr.MUTE is arco_engine.MUTE
    assert arco_instr.FINISH is arco_engine.FINISH
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest python25/tests/test_constants.py -v`
Expected: FAIL — `arco_instr.ACTION_TERM == 2`, not 1

- [ ] **Step 3: Replace the local definitions with imports**

In `python25/arco_instr.py`, delete these lines from the "Action / callback constants" block (keep `SIGNAL`, `GAIN`, `BOTH` — they're instr-specific):

```python
ACTION_REM = 1
ACTION_TERM = 2
ACTION_END = 4
ACTION_END_OR_TERM = ACTION_TERM | ACTION_END
MUTE = 'mute'
FINISH = 'finish'
```

Add to the existing `from arco import (...)` list (after `MATH_OP_SUB,`):

```python
    ACTION_REM,
    ACTION_TERM,
    ACTION_END,
    ACTION_END_OR_TERM,
    MUTE,
    FINISH,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest python25/tests -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add python25/arco_instr.py python25/tests/test_constants.py
git commit -m "fix: import ACTION_* constants from arco_engine instead of diverged local copies"
```

---

### Task 4: Client-side graph reference tracking (prerequisite for weak registry)

`Sum.ins(child)` inserts server-side but keeps no Python reference. Once the registry is weak (Task 6), a child referenced only by a server-side container would be GC'd and freed while audible (e.g. Supersaw's `blend_ugen`, Reverb's combs held only via `rvb.ins`). Containers and `play()`/`fade()` must mirror the server graph with Python references *first*.

**Files:**
- Modify: `python25/arco_ugens.py` — `Ugen.__init__`/`__del__`/`play`/`mute`/`fade`/`fade_in`, `Sum`, `Sumb`, `Add`, `Addb`, `Route`, `Stdistr`; add module-level `import threading` and `_FADE_CLEANUP_MARGIN`
- Test: `python25/tests/test_ugens.py`

- [ ] **Step 1: Write the failing tests**

Append to `python25/tests/test_ugens.py`:

```python
import time

import arco_ugens
from arco_engine import OUTPUT_ID
from arco_ugens import Add, Route, Sine, Stdistr, Sum


def test_sum_ins_tracks_members(engine):
    s = Sum(1)
    child = Sine(440, 0.1)
    s.ins(child)
    assert s.members[child.id] is child
    s.rem(child)
    assert child.id not in s.members


def test_sum_swap_tracks_members(engine):
    s = Sum(1)
    a, b = Sine(440, 0.1), Sine(660, 0.1)
    s.ins(a)
    s.swap(a, b)
    assert a.id not in s.members
    assert s.members[b.id] is b


def test_add_route_stdistr_track_members(engine):
    child = Sine(440, 0.1)
    add = Add(1)
    add.ins(child)
    assert add.members[child.id] is child
    route = Route(1)
    route.ins(child, 0, 0)
    assert route.members[child.id] is child
    route.reminput(child)
    assert child.id not in route.members
    st = Stdistr(4, 0.5)
    st.ins(2, child)
    assert st.members[2] is child
    st.rem(2)
    assert 2 not in st.members


def test_play_and_mute_track_engine_output(engine):
    engine.output = Sum(2, True, id_num=OUTPUT_ID)
    s = Sine(440, 0.1)
    s.play()
    assert engine.output.members[s.id] is s
    s.mute()
    assert s.id not in engine.output.members


def test_fade_swaps_membership_and_releases_fader(engine, monkeypatch):
    monkeypatch.setattr(arco_ugens, "_FADE_CLEANUP_MARGIN", 0.05)
    engine.output = Sum(2, True, id_num=OUTPUT_ID)
    s = Sine(440, 0.1)
    s.play()
    faded = s.fade(0.05)
    assert s.id not in engine.output.members
    assert engine.output.members[faded.id] is faded
    time.sleep(0.3)
    assert faded.id not in engine.output.members
    assert faded._server_freed is True


def test_fade_in_completion_swaps_source_back(engine, monkeypatch):
    monkeypatch.setattr(arco_ugens, "_FADE_CLEANUP_MARGIN", 0.05)
    engine.output = Sum(2, True, id_num=OUTPUT_ID)
    s = Sine(440, 0.1)
    s.fade_in(0.05)
    fader = engine.fade_in_lookup[s.id]
    assert engine.output.members[fader.id] is fader
    time.sleep(0.3)
    assert s.id not in engine.fade_in_lookup
    assert engine.output.members[s.id] is s
    assert fader.id not in engine.output.members
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest python25/tests/test_ugens.py -v`
Expected: new tests FAIL with `AttributeError: 'Sum' object has no attribute 'members'`

- [ ] **Step 3: Implement tracking in arco_ugens.py**

3a. At the top of the file (after the `from arco_engine import (...)` block):

```python
import threading

# Seconds past a fade's duration before the client drops its reference to
# a terminated Fader (server frees it at termination).
_FADE_CLEANUP_MARGIN = 0.5
```

Remove the `import threading` inside `fade_in`.

3b. In `Ugen.__init__`, after `self.action_id = None`, add:

```python
        self._server_freed = False  # set when the server has already freed this id
```

3c. In `Ugen.__del__`, skip the redundant server free:

```python
    def __del__(self):
        if getattr(self, 'engine', None) is not None:
            if not getattr(self, '_server_freed', False):
                self.engine.send_cmd("/arco/free", 0, "i", self.id)
            self.engine.id_pool.free_slot(self.id)
            self.engine.unregister(self.id)
```

3d. Replace `play`, `mute`, `fade`, `fade_in` and add `_drop_after`:

```python
    def play(self):
        output = self.engine.output
        if output is not None:
            output.members[self.id] = self
        self.engine.send_cmd("/arco/sum/ins", 0, "ii", OUTPUT_ID, self.id)

    def mute(self, status=None):
        # status is accepted (passed by atend actions) but ignored here
        output = self.engine.output
        if output is not None:
            output.members.pop(self.id, None)
        self.engine.send_cmd("/arco/sum/rem", 0, "ii", OUTPUT_ID, self.id)

    def fade(self, dur, mode=FADE_SMOOTH):
        """Fade output to zero over dur seconds, then disconnect."""
        fader = self.engine.fade_in_lookup.get(self.id)
        if fader:
            # fade_in is in progress; convert to fade out
            del self.engine.fade_in_lookup[self.id]
            fader.set_dur(dur)
            fader.set_goal(0)
            fader.set_mode(mode)
            self._drop_after(fader, dur)
            return fader
        faded = create_fader(self, 1, dur, 0)
        faded.term()
        output = self.engine.output
        if output is not None:
            output.members.pop(self.id, None)
            output.members[faded.id] = faded
        # swap self out of output, put faded in
        self.engine.send_cmd("/arco/sum/swap", 0, "iii", OUTPUT_ID,
                             self.id, faded.id)
        faded.set_mode(mode)
        self._drop_after(faded, dur)
        return faded

    def _drop_after(self, fader, dur):
        """After a terminating fade completes, the server frees the Fader;
        drop the client-side reference so its slot can be reclaimed."""
        engine = self.engine

        def _cleanup():
            fader._server_freed = True
            output = engine.output
            if output is not None:
                output.members.pop(fader.id, None)

        threading.Timer(dur + _FADE_CLEANUP_MARGIN, _cleanup).start()

    def fade_in(self, dur, mode=FADE_SMOOTH, term=True):
        """Fade in from silence. Ugen must NOT already be playing."""
        fader = create_fader(self, 0, dur, 1)
        if term:
            fader.term()
        self.engine.fade_in_lookup[self.id] = fader
        fader.set_mode(mode)
        fader.play()
        engine = self.engine

        def _fade_in_complete():
            f = engine.fade_in_lookup.pop(self.id, None)
            if f is not None:
                # swap fader out, put the original ugen directly in output
                engine.send_cmd("/arco/sum/swap", 0, "iii", OUTPUT_ID,
                                f.id, self.id)
                f._server_freed = True
                output = engine.output
                if output is not None:
                    output.members.pop(f.id, None)
                    output.members[self.id] = self

        threading.Timer(dur + _FADE_CLEANUP_MARGIN,
                        _fade_in_complete).start()
```

3e. Containers — add `self.members = {}` after each `super().__init__` call and maintain it. For `Sum`:

```python
class Sum(Ugen):

    def __init__(self, chans, wrap=True, id_num=None):
        super().__init__("Sum", chans, A_RATE, "i", None, None, 'wrap',
                         1 if wrap else 0, id_num=id_num)
        self.members = {}  # id -> Ugen: mirror server graph client-side

    def ins(self, *ugens):
        for ugen in ugens:
            self.members[ugen.id] = ugen
            self.engine.send_cmd("/arco/sum/ins", 0, "ii", self.id, ugen.id)
        return self

    def rem(self, *ugens):
        for ugen in ugens:
            self.members.pop(ugen.id, None)
            self.engine.send_cmd("/arco/sum/rem", 0, "ii", self.id, ugen.id)
        return self

    def swap(self, ugen, replacement):
        self.members.pop(ugen.id, None)
        self.members[replacement.id] = replacement
        self.engine.send_cmd("/arco/sum/swap", 0, "iii", self.id, ugen.id,
                             replacement.id)
        return self
```

`Sumb` gets the same change with `/arco/sumb/...` addresses:

```python
class Sumb(Ugen):

    def __init__(self, chans, wrap=True, id_num=None):
        super().__init__("Sumb", chans, B_RATE, "i", None, None, 'wrap',
                         1 if wrap else 0, id_num=id_num)
        self.members = {}  # id -> Ugen: mirror server graph client-side

    def ins(self, *ugens):
        for ugen in ugens:
            self.members[ugen.id] = ugen
            self.engine.send_cmd("/arco/sumb/ins", 0, "ii", self.id, ugen.id)
        return self

    def rem(self, *ugens):
        for ugen in ugens:
            self.members.pop(ugen.id, None)
            self.engine.send_cmd("/arco/sumb/rem", 0, "ii", self.id, ugen.id)
        return self

    def swap(self, ugen, replacement):
        self.members.pop(ugen.id, None)
        self.members[replacement.id] = replacement
        self.engine.send_cmd("/arco/sumb/swap", 0, "iii", self.id, ugen.id,
                             replacement.id)
        return self
```

`Add` and `Addb` (note `Add.ins` is variadic, `Addb.ins` takes one ugen — keep the existing signatures):

```python
class Add(Ugen):

    def __init__(self, chans=1, wrap=True):
        super().__init__("Add", chans, A_RATE, "i", None, None, 'wrap',
                         1 if wrap else 0)
        self.members = {}  # id -> Ugen: mirror server graph client-side

    def ins(self, *ugens):
        for ugen in ugens:
            self.members[ugen.id] = ugen
            self.engine.send_cmd("/arco/add/ins", 0, "ii", self.id, ugen.id)
        return self

    def rem(self, ugen):
        self.members.pop(ugen.id, None)
        self.engine.send_cmd("/arco/add/rem", 0, "ii", self.id, ugen.id)
        return self

    def swap(self, ugen, replacement):
        self.members.pop(ugen.id, None)
        self.members[replacement.id] = replacement
        self.engine.send_cmd("/arco/add/swap", 0, "iii", self.id, ugen.id,
                             replacement.id)
        return self


class Addb(Ugen):

    def __init__(self, chans=1, wrap=True):
        super().__init__("Addb", chans, B_RATE, "i", None, None, 'wrap',
                         1 if wrap else 0)
        self.members = {}  # id -> Ugen: mirror server graph client-side

    def ins(self, ugen):
        self.members[ugen.id] = ugen
        self.engine.send_cmd("/arco/addb/ins", 0, "ii", self.id, ugen.id)
        return self

    def rem(self, ugen):
        self.members.pop(ugen.id, None)
        self.engine.send_cmd("/arco/addb/rem", 0, "ii", self.id, ugen.id)
        return self

    def swap(self, ugen, replacement):
        self.members.pop(ugen.id, None)
        self.members[replacement.id] = replacement
        self.engine.send_cmd("/arco/addb/swap", 0, "iii", self.id, ugen.id,
                             replacement.id)
        return self
```

For `Route` (retain on `ins`, release on `reminput` — `rem` removes individual routes, not necessarily the input, so over-retain):

```python
class Route(Ugen):

    def __init__(self, chans):
        super().__init__("Route", chans, A_RATE, "", None, None)
        self.members = {}  # id -> Ugen; released by reminput()

    def ins(self, input, *routes):
        self.members[input.id] = input
        self._send_ins_rem(input, routes, "/arco/route/ins")
        return self

    def reminput(self, input):
        self.members.pop(input.id, None)
        self.engine.send_cmd("/arco/route/reminput", 0, "ii", self.id,
                             input.id)
        return self
```

(`rem` and `_send_ins_rem` unchanged.)

For `Stdistr` (keyed by index):

```python
    # in Stdistr.__init__, after super().__init__:
        self.members = {}  # index -> Ugen

    def ins(self, index, ugen):
        self.members[index] = ugen
        self.engine.send_cmd("/arco/stdistr/ins", 0, "iii", self.id, index,
                             ugen.id)
        return self

    def rem(self, index):
        self.members.pop(index, None)
        self.engine.send_cmd("/arco/stdistr/rem", 0, "ii", self.id, index)
        return self
```

(`Mix` already tracks via `self.inputs` — no change.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest python25/tests -v`
Expected: all pass (fade tests take ~0.6s)

- [ ] **Step 5: Commit**

```bash
git add python25/arco_ugens.py python25/tests/test_ugens.py
git commit -m "feat: track container/play/fade graph references client-side"
```

---

### Task 5: Ugen ID ownership — stop Instrument leaking pool slots (audit finding 2)

`Instrument.__init__` allocates a fresh slot via `super().__init__()`, registers under it, then overwrites `self.id = output_ugen.id` — leaking the slot and priming a future double-free. Rule: **pool-allocated IDs are owned (freed by `__del__`, tracked in the registry); explicit `id_num` IDs are borrowed (engine/caller manages them).**

**Files:**
- Modify: `python25/arco_ugens.py` (`Ugen.__init__`, `Ugen.__del__`), `python25/arco_engine.py` (`close`), `python25/arco_instr.py` (`Instrument.__init__`)
- Test: `python25/tests/test_lifecycle.py`

- [ ] **Step 1: Write the failing tests**

Create `python25/tests/test_lifecycle.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest python25/tests/test_lifecycle.py -v`
Expected: FAIL — `AttributeError: ... no attribute 'owns_id'` and slot-count mismatch (4, not 3)

- [ ] **Step 3: Implement ownership in Ugen**

In `python25/arco_ugens.py`, `Ugen.__init__`, replace the id/register block:

```python
        inputs_ = list(inputs_)
        if id_num is not None:
            self.id = id_num
            self.owns_id = False  # caller/engine manages this id's lifetime
        else:
            self.id = self.engine.id_pool.request_slot()
            self.owns_id = True
            self.engine.register(self)
```

Replace `__del__` (builds on Task 4's version):

```python
    def __del__(self):
        engine = getattr(self, 'engine', None)
        if engine is None or not getattr(self, 'owns_id', False):
            return
        if not getattr(self, '_server_freed', False):
            engine.send_cmd("/arco/free", 0, "i", self.id)
        engine.id_pool.free_slot(self.id)
        engine.unregister(self.id)
```

- [ ] **Step 4: Instrument borrows the output's id**

In `python25/arco_instr.py`, `Instrument.__init__`, pass `id_num` and delete the overwrite:

```python
        self.output = output_ugen
        # Borrow the output ugen's id so that wiring this Instrument
        # into the graph is the same as wiring its output. The output
        # ugen owns the id; this wrapper never frees it.
        super().__init__(name,
                         output_ugen.chans,
                         output_ugen.rate,
                         "",
                         no_msg=True,
                         id_num=output_ugen.id)
```

(Delete the line `self.id = output_ugen.id`.)

- [ ] **Step 5: Adapt `ArcoEngine.close()`**

The registry now holds only pool-allocated ugens, so the `>= 100` guard goes away; system ugens are detached via their attributes:

```python
    def close(self):
        """Free all ugens, disconnect, and clear active engine."""
        if self.o2lite is None:
            return
        # Free pool-allocated ugens in reverse id order
        for ugen_id, ugen in sorted(list(self._ugens.items()), reverse=True):
            self.send_cmd("/arco/free", 0, "i", ugen_id)
            ugen.engine = None  # prevent double-free in __del__
        self._ugens.clear()
        for ugen in (self.zero, self.zerob, self.input, self.output):
            if ugen is not None:
                ugen.engine = None
        self.id_pool = UgenID()
        self.action_dict.clear()
        self.next_action_id = 1
        self.fade_in_lookup.clear()
        self.zero = None
        self.zerob = None
        self.input = None
        self.output = None
        self.o2lite = None
        global _active_engine
        if _active_engine is self:
            _active_engine = None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest python25/tests -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add python25/arco_ugens.py python25/arco_engine.py python25/arco_instr.py python25/tests/test_lifecycle.py
git commit -m "fix: Instrument borrows output ugen id; introduce owns_id ownership rule"
```

---

### Task 6: Weak-reference registry (audit finding 1)

With graph tracking (Task 4) and ownership (Task 5) in place, flip `_ugens` to a `WeakValueDictionary`. Dropping the last Python reference now triggers `__del__` → `/arco/free` + slot reclaim. Objects that must survive are pinned by real references: engine attributes (system ugens), container `members`/`inputs`, `fade_in_lookup`, and each ugen's `inputs` dict.

**Files:**
- Modify: `python25/arco_engine.py:277` (registry), imports
- Test: `python25/tests/test_lifecycle.py`

- [ ] **Step 1: Write the failing tests**

Append to `python25/tests/test_lifecycle.py`:

```python
from arco_ugens import Const, Sum


def test_dropping_last_reference_frees_ugen_and_slot(engine):
    free_before = pool_free_count(engine)
    s = Sine(440, 0.5)
    sid = s.id
    del s
    gc.collect()
    assert ("/arco/free", "i", (sid,)) in engine.o2lite.messages
    assert pool_free_count(engine) == free_before  # sine + consts reclaimed


def test_container_membership_keeps_child_alive(engine):
    mixer = Sum(1)
    child = Sine(440, 0.1)
    cid = child.id
    mixer.ins(child)
    del child
    gc.collect()
    assert ("/arco/free", "i", (cid,)) not in engine.o2lite.messages
    assert engine._ugens[cid] is not None


def test_replacing_input_releases_old_const(engine):
    s = Sine(440, 0.5)
    old_id = s.inputs['freq'].id
    s.set('freq', Const(220))
    gc.collect()
    assert ("/arco/free", "i", (old_id,)) in engine.o2lite.messages


def test_close_frees_survivors_and_resets_pool(engine):
    # capture the transport first: close() sets engine.o2lite to None
    transport = engine.o2lite
    s = Sine(440, 0.5)
    sid = s.id
    engine.close()
    assert ("/arco/free", "i", (sid,)) in transport.messages
    assert s.engine is None
    assert engine.o2lite is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest python25/tests/test_lifecycle.py -v`
Expected: `test_dropping_last_reference_frees_ugen_and_slot` FAILS — no `/arco/free` sent (strong registry pins the object)

- [ ] **Step 3: Flip the registry to weak references**

In `python25/arco_engine.py`, add `import weakref` to the imports, then in `ArcoEngine.__init__`:

```python
        self._ugens = weakref.WeakValueDictionary()  # id -> Ugen (weak)
```

Update the `register` docstring (it no longer prevents GC):

```python
    def register(self, ugen):
        """Track a pool-allocated ugen. References are weak: a ugen lives
        as long as user code or the client-side graph references it."""
        self._ugens[ugen.id] = ugen
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest python25/tests -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add python25/arco_engine.py python25/tests/test_lifecycle.py
git commit -m "feat: weak-reference ugen registry -- dropping last ref frees server ugen and pool slot"
```

---

### Task 7: Weak action targets + handler pruning (audit finding 5)

`Ugen_action.target` is a strong reference (despite its comment), so registered actions would pin ugens forever even after Task 6. Store a weakref; prune dead entries when actions fire.

**Files:**
- Modify: `python25/arco_engine.py` (`Ugen_action`, `actl_act_handler`)
- Test: `python25/tests/test_actions.py`

- [ ] **Step 1: Write the failing tests**

Create `python25/tests/test_actions.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest python25/tests/test_actions.py -v`
Expected: `test_action_target_does_not_pin_ugen` FAILS (strong target ref keeps the ugen in the weak registry)

- [ ] **Step 3: Implement weak targets**

In `python25/arco_engine.py`, replace `Ugen_action`:

```python
class Ugen_action:
    def __init__(self, target, method):
        self.target_ref = weakref.ref(target)  # do not pin the target
        self.method = method

    @property
    def target(self):
        return self.target_ref()

    def __repr__(self):
        return f"<Ugen_action {self.target} {self.method!r}>"
```

Replace `actl_act_handler`:

```python
    def actl_act_handler(self, timestamp, address, types, key, status, uid):
        """Handler for /actl/act messages from Arco server."""
        al = self.action_dict.get(key)
        if al is None:
            return
        if status & ACTION_FREE:
            self.action_dict.pop(key, None)
            return
        live = []
        for ua in al.ugen_actions:
            target = ua.target
            if target is None:
                continue  # target was garbage-collected; drop the action
            live.append(ua)
            if status & al.action_mask and hasattr(target, ua.method):
                getattr(target, ua.method)(status)
        al.ugen_actions = live
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest python25/tests -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add python25/arco_engine.py python25/tests/test_actions.py
git commit -m "fix: action targets held by weakref; handler prunes dead targets"
```

---

### Task 8: Engine-scoped sawtooth singleton (audit finding 6)

`_sawtooth_waveforms` survives `engine.close()` holding a `Tableosc` bound to the dead engine; after reconnect, Supersaw uses a stale ugen. Rebuild the singleton whenever the active engine changes.

**Files:**
- Modify: `python25/arco_instr.py` (`Sawtooth_waveforms`, `Supersaw_instr`); add `get_engine` to the `from arco import (...)` list
- Test: `python25/tests/test_instr.py`

- [ ] **Step 1: Write the failing test**

Create `python25/tests/test_instr.py`:

```python
import arco_instr


def test_sawtooth_singleton_rebuilds_on_new_engine(make_engine):
    make_engine()
    saw1 = arco_instr.get_sawtooth_waveforms()
    assert arco_instr.get_sawtooth_waveforms() is saw1
    make_engine()  # becomes the new active engine
    saw2 = arco_instr.get_sawtooth_waveforms()
    assert saw2 is not saw1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest python25/tests/test_instr.py -v`
Expected: FAIL with `AttributeError: module 'arco_instr' has no attribute 'get_sawtooth_waveforms'`

- [ ] **Step 3: Implement the accessor**

In `python25/arco_instr.py`, add `get_engine,` to the `from arco import (...)` list. Replace the `_sawtooth_waveforms`/`Sawtooth_waveforms` block:

```python
_sawtooth_waveforms = None


def get_sawtooth_waveforms():
    """Return the sawtooth wavetable singleton for the active engine,
    rebuilding it if the engine changed since it was created."""
    global _sawtooth_waveforms
    engine = get_engine()
    if (_sawtooth_waveforms is None
            or _sawtooth_waveforms.engine is not engine):
        _sawtooth_waveforms = Sawtooth_waveforms(engine)
    return _sawtooth_waveforms


class Sawtooth_waveforms:
    """Per-engine manager for anti-aliased sawtooth wavetables."""

    def __init__(self, engine):
        self.engine = engine
        self.created = [None] * 36
        self.tables = Tableosc(1, 1)
        self.next_index = 0
```

(`get_index` unchanged. Note the constructor no longer assigns the global — `get_sawtooth_waveforms()` does.)

In `Supersaw_instr.__init__`, replace the singleton usage: delete `global _sawtooth_waveforms` and the `if _sawtooth_waveforms is None: Sawtooth_waveforms()` block; instead, right after `instr_begin()`:

```python
        self.saw = get_sawtooth_waveforms()
```

Then replace the two lookups:
- `table_index = _sawtooth_waveforms.get_index(pitch, self.antialias != 0)` → `table_index = self.saw.get_index(pitch, self.antialias != 0)`
- In `_supersaw_component`: `comp.borrow(_sawtooth_waveforms.tables)` → `comp.borrow(self.saw.tables)`
- In `_calc_tableosc_index`: `table_index = _sawtooth_waveforms.get_index(self.pitch, self.antialias != 0)` → `table_index = self.saw.get_index(self.pitch, self.antialias != 0)`

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest python25/tests -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add python25/arco_instr.py python25/tests/test_instr.py
git commit -m "fix: sawtooth wavetable singleton is engine-scoped, rebuilt on reconnect"
```

---

### Task 9: Per-thread instrument construction stacks (audit finding 7)

NiceGUI runs callbacks on worker threads; the single global `_instr_stack` lets two concurrent constructions cross-wire parameter bindings. Construction is scoped to one callback (one thread), so thread-keyed stacks are correct here — unlike the active engine, which must stay a shared module global (see `feedback_thread_local` memory).

**Files:**
- Modify: `python25/arco_instr.py` (stack machinery, `Instrument.__init__`)
- Test: `python25/tests/test_instr.py`

- [ ] **Step 1: Write the failing test**

Append to `python25/tests/test_instr.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest python25/tests/test_instr.py -v`
Expected: FAIL — the worker pops the main thread's context: `'gain' in result['instr'].parameter_bindings` is True

- [ ] **Step 3: Implement per-thread stacks**

In `python25/arco_instr.py`, add `import threading` and `from collections import defaultdict` to the imports. Replace the `_instr_stack` block:

```python
# Instrument-construction contexts, keyed by thread id. Each NiceGUI
# callback runs a full instr_begin() -> Instrument.__init__() sequence on
# one worker thread, so per-thread stacks stop concurrent constructions
# from cross-wiring parameters. (The active engine is deliberately a
# shared module global instead -- construction state is the exception
# because it never crosses a callback boundary.)
_instr_stacks = defaultdict(list)


def _instr_stack():
    return _instr_stacks[threading.get_ident()]


def instr_begin():
    """Call at the start of an Instrument subclass __init__."""
    _instr_stack().append({})


def _add_param_descr_to_context(pd, name):
    context = _instr_stack()[-1]
    if name in context:
        print("WARNING: Parameter", name, "is already specified. Ignored.")
    else:
        context[name] = pd
    return pd.value
```

In `Instrument.__init__`, replace the stack pop:

```python
        stack = _instr_stack()
        if not stack:
            raise RuntimeError(
                "instr stack is empty. Did you forget instr_begin()?")
        self.parameter_bindings = stack.pop()
        if not stack:
            # don't accumulate an entry per worker thread
            del _instr_stacks[threading.get_ident()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest python25/tests -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add python25/arco_instr.py python25/tests/test_instr.py
git commit -m "fix: instrument construction stacks are per-thread for NiceGUI callback safety"
```

---

### Task 10: Hygiene — logging, address prefix, dead code

**Files:**
- Modify: `python25/arco_ugens.py`, `python25/arco_engine.py:5`, `python25/arco_instr.py:280`
- Test: `python25/tests/test_smoke.py` (assertion added)

- [ ] **Step 1: Add a prefix assertion to the smoke test**

Append to `test_sine_creation_sends_new_message` in `python25/tests/test_smoke.py`:

```python
    assert s._addr_prefix == "/arco/sine"
```

Run: `.venv/bin/python -m pytest python25/tests/test_smoke.py -v` — Expected: FAIL (`_addr_prefix` doesn't exist yet)

- [ ] **Step 2: Implement in arco_ugens.py**

2a. Add near the top (after the imports):

```python
import logging

log = logging.getLogger("pyarco")
```

2b. In `Ugen.__init__`, after `self.rate = rate_`, add:

```python
        self._addr_prefix = "/arco/" + classname_.lower()
```

Use it for the creation address: `address = f"{self._addr_prefix}/new"`. Replace the creation print with:

```python
        log.debug("Ugen %d (%s) created", self.id, self.classname)
```

2c. In `Ugen.set`, replace `addr_prefix = "/arco/" + self.classname.lower()` with `addr_prefix = self._addr_prefix`.

2d. Replace the three debug prints in `Vu.set`, `Chorddetect.set`, `SpectralCentroid.set`, `SpectralRolloff.set` (e.g. `print(f"Vu set {self.id} {value.id}")`) with `log.debug(...)` equivalents, e.g.:

```python
        log.debug("Vu set %d %d", self.id, value.id)
```

- [ ] **Step 3: Remove dead code**

- `python25/arco_engine.py`: delete `import threading` (line 5, unused since the thread-local → global refactor).
- `python25/arco_instr.py`: delete `_mix_name_counter = 0` (unused; `Synth._prev_mixer_id` superseded it).

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest python25/tests -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add python25/arco_ugens.py python25/arco_engine.py python25/arco_instr.py python25/tests/test_smoke.py
git commit -m "chore: logging instead of prints, precomputed addr prefix, remove dead code"
```

---

### Task 11: Documentation — lifecycle model + known follow-ups

**Files:**
- Modify: `PyArcoCONTEXT.md`, `CLAUDE.md`

- [ ] **Step 1: Update PyArcoCONTEXT.md**

In the "Existing Codebase" section, update the stale file description (it still says `arco.py` is a ~1860-line monolith; it's now a re-export shim over `arco_engine.py` + `arco_ugens.py`). Add a new subsection after the `arco.py` description:

```markdown
### Ugen lifecycle model

- `ArcoEngine._ugens` is a `weakref.WeakValueDictionary`. A ugen lives as
  long as Python references it; dropping the last reference triggers
  `__del__`, which sends `/arco/free` and returns the id to the pool.
- Client-side references mirror the server graph: each ugen's `inputs`
  dict holds its input ugens; container ugens (`Sum`, `Sumb`, `Add`,
  `Addb`, `Route`, `Stdistr`) track inserted ugens in `self.members`;
  `Mix` uses `self.inputs`. `play()` pins the ugen in
  `engine.output.members` until `mute()` — audible implies alive.
- `owns_id`: pool-allocated ids are owned (freed by `__del__`); ugens
  created with an explicit `id_num` (system ugens, `Instrument` wrappers
  borrowing their output's id) never free their id.
- `_server_freed`: set when the server is known to have freed the ugen
  (terminating faders); `__del__` then skips the redundant `/arco/free`.

### Known follow-ups (deliberate gaps)

- `term(dur)` outside the fade helpers still desyncs client pool from
  server: the server frees the id at termination but the client slot
  stays allocated until the Python object dies. Full fix needs
  client-side `ACTION_FREE` handling.
- `/actl/act` is never registered as an o2lite method handler in
  `connect()`, so server-initiated actions (`atend`, `Instrument.finish`
  / `Synth.is_finished` note recycling) do not fire yet.
- Instrument-construction contexts orphaned by an exception between
  `instr_begin()` and `Instrument.__init__()` linger on that thread's
  stack (bounded leak, no corruption).
```

Also update the "What's Next" list: add these follow-ups; note the test suite now exists (`python25/tests`, offline via `FakeO2Lite`).

- [ ] **Step 2: Update CLAUDE.md**

In "Key Files", replace the `arco.py` line with:

```markdown
- `python25/arco_engine.py` — ArcoEngine (O2 connection, weak-ref ugen
  registry, UgenID pool, action system), constants, conversion utilities
- `python25/arco_ugens.py` — Ugen base class and ~55 ugen wrapper classes
- `python25/arco.py` — thin re-export of arco_engine + arco_ugens
```

In "Conventions", update the `__del__` bullet:

```markdown
- `__del__` sends `/arco/free` and returns the ID to the pool — but only
  for pool-allocated ids (`owns_id`), and only when the server hasn't
  already freed it (`_server_freed`). The engine registry is weak; keep a
  Python reference (or `play()` the ugen) to keep it alive.
- Tests: `.venv/bin/python -m pytest python25/tests -v` (offline, no Arco
  server needed — FakeO2Lite records messages).
```

- [ ] **Step 3: Run the full suite one last time**

Run: `.venv/bin/python -m pytest python25/tests -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add PyArcoCONTEXT.md CLAUDE.md
git commit -m "docs: document ugen lifecycle model, ownership rules, and known follow-ups"
```

---

## Final verification (manual, live server — optional but recommended)

The suite is offline by design. Before merging, if an `arcobasic` server is available: run `python3 python25/init.py` from the main checkout, connect, exercise Sine play/stop/destroy and the Fade card, and confirm sound behaves and the console shows no `Slot is already free` / `No free slots` errors. This validates the weak-registry semantics against real server timing, which the fakes cannot.
