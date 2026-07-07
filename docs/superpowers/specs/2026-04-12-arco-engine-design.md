# ArcoEngine: Lifecycle, Registry, and Module Split

## Summary

Introduce an `ArcoEngine` class that owns the O2lite connection, UgenID pool,
and a registry of all live Python ugen shadows. Split the monolithic `arco.py`
into three modules with clear responsibilities. Remove `initialize_o2lite()` in
favor of the engine's context manager API.

## Problem

1. **Accidental GC of ugen shadows.** Python ugen objects are "shadows" of C++
   ugens in the Arco server. When a Python shadow goes out of scope and nothing
   references it, Python's GC destroys it, sending `/arco/free` to the C++ side
   even if the ugen is still active in the audio graph. This causes audio
   glitches and memory issues on the C++ side.

2. **No teardown or reconnection path.** `initialize_o2lite()` sets module-level
   globals (`o2lite`, `output`, `zero`, `zerob`) with no corresponding shutdown.
   Reconnecting to a restarted Arco server means fighting stale state.

3. **Monolithic module.** `arco.py` is ~1900 lines containing connection logic,
   ID management, the Ugen base class, ~50 concrete wrappers, constants, and
   utilities all in one file.

## Design

### Approach: Engine as Context with Module-Level Global

`ArcoEngine` works as a context manager that sets itself as the "active engine"
via a module-level global. Ugens grab the active engine automatically via
`get_engine()`, but can accept an explicit `engine=` kwarg to override. This
gives a clean API for the common single-engine case while supporting
multi-engine scenarios if ever needed.

> **Note:** An earlier draft used `threading.local()` but this was changed to a
> plain module global because NiceGUI callbacks run in different threads, causing
> them to lose the thread-local engine reference.

### ArcoEngine Class

```python
class ArcoEngine:
    def __init__(self, input_chans=2, output_chans=2, ensemble="arco", timeout=30):
        # Stores config. Does NOT connect yet.
        self.input_chans = input_chans
        self.output_chans = output_chans
        self.ensemble = ensemble
        self.timeout = timeout
        self.o2lite = None
        self.id_pool = UgenID()
        self._ugens = {}        # int -> Ugen, strong references
        self.fade_in_lookup = {} # moved from module-level

    def connect(self):
        # Creates O2lite instance, blocks until connected (with timeout).
        # Sends reset, creates system ugens (zero, zerob, input, output).
        # Sets self as the active engine via thread-local.

    def close(self):
        # Frees all registered ugens in reverse creation order (skip system IDs 0-3).
        # Sets ugen.engine = None on each to prevent double-free in __del__.
        # Clears registry, resets ID pool.
        # Disconnects O2lite.
        # Removes self from thread-local.

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def send_cmd(self, *args):
        # Delegates to self.o2lite.send_cmd(...)

    def register(self, ugen):
        self._ugens[ugen.id] = ugen

    def unregister(self, ugen_id):
        self._ugens.pop(ugen_id, None)
```

### Active Engine Access

```python
_active_engine = None

def get_engine() -> ArcoEngine:
    if _active_engine is None:
        raise RuntimeError(
            "No active ArcoEngine -- call engine.connect() first")
    return _active_engine
```

### Ugen Base Class Changes

`Ugen` no longer references module-level `o2lite`. Instead it gets its
connection and registry from the engine:

```python
class Ugen:
    def __init__(self, classname, chans, rate_, types_, *inputs_,
                 no_msg=False, omit_chans=False, engine=None):
        self.engine = engine or get_engine()
        self.id = self.engine.id_pool.request_slot()
        self.engine.register(self)
        # ... rest of init unchanged, but all o2lite.send_cmd(...)
        # becomes self.engine.send_cmd(...)

    def __del__(self):
        if self.engine is not None:
            self.engine.send_cmd("/arco/free", 0, "i", self.id)
            self.engine.id_pool.free_slot(self.id)
            self.engine.unregister(self.id)

    def play(self):
        self.engine.send_cmd("/arco/sum/ins", 0, "ii", OUTPUT_ID, self.id)
```

- `self.engine` replaces all bare `o2lite` references throughout every ugen.
- Registration at birth: the engine holds a strong reference, preventing
  accidental GC as long as the engine is alive.
- `__del__` checks `self.engine is not None` — if the engine already freed
  this ugen during `close()`, `engine` will have been set to `None`.

### Teardown

```python
def close(self):
    for ugen_id in sorted(self._ugens.keys(), reverse=True):
        ugen = self._ugens[ugen_id]
        if ugen_id >= 100:  # skip system ugens (0-3)
            self.send_cmd("/arco/free", 0, "i", ugen_id)
        ugen.engine = None  # prevent double-free in __del__ (all ugens, including system)
    self._ugens.clear()
    self.id_pool = UgenID()
    self.o2lite = None
    global _active_engine
    if _active_engine is self:
        _active_engine = None
```

Reverse order ensures dependents are freed before their dependencies.
Setting `ugen.engine = None` prevents `__del__` from sending a redundant
`/arco/free` after the engine has already cleaned up.

### Module Split

**`arco_engine.py`** — Engine, connection, infrastructure:
- `ArcoEngine` class
- `get_engine()` module-level accessor
- `UgenID` pool
- Action system (`register_action`, `actl_act_handler`, `Action_list`,
  `Ugen_action`)
- Constants (rate symbols, system IDs, audio params, math/unary op enums)
- Conversion utilities (`hz_to_step`, `db_to_linear`, panning functions, etc.)

**`arco_ugens.py`** — Ugen base class and all wrappers:
- `Ugen` base class (uses `get_engine()` instead of module globals)
- `Const`, `Const_like`, `Envelope`, `Wavetables` (base/abstract)
- All ~50 concrete ugen classes
- Imports constants and `get_engine` from `arco_engine`

**`arco.py`** — Thin re-export layer:
- `from arco_engine import *`
- `from arco_ugens import *`
- No other content. Existing imports like `from arco import Sine` keep working.

**`arco_instr.py`** — Unchanged in structure. `Instrument` and `Synth` inherit
from `Ugen` and get `self.engine` for free. `param()` / `Param_descr` create
`Const`/`Smoothb` ugens that auto-register with the active engine.

**`init.py`** — Initialization changes from `initialize_o2lite()` to:
```python
engine = ArcoEngine()
engine.connect()
```
Store engine reference on `DemoState` or similar. Reconnection becomes
`engine.close()` followed by creating a new `ArcoEngine`.

### Per-Session State

Module-level mutable state that is per-session moves onto the engine:
- `fade_in_lookup` dict
- Any other dicts/lists that track live ugen relationships

### What's Removed

- `initialize_o2lite()` — replaced by `ArcoEngine.connect()`
- Module-level `o2lite` global — owned by engine
- Module-level `output`, `zero`, `zerob` globals — owned by engine as
  `engine.output`, `engine.zero`, `engine.zerob`
- `Ugen.uid_pool` class variable — replaced by `engine.id_pool`

## Usage

```python
from arco import ArcoEngine, Sine, Mix

with ArcoEngine(input_chans=2, output_chans=2) as engine:
    sine = Sine(440, 0.5)
    sine.play()
    # ... interact with Arco ...
# engine.__exit__ frees all remaining ugens and disconnects
```

## Out of Scope

- `.ugen -> .py` code generator (separate effort, will target the new module
  structure)
- Python packaging (`pyproject.toml`) — separate effort
- Test suite — separate effort, though this design is more testable
