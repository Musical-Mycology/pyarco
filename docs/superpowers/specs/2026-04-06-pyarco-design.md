# PyArco Design Specification

## Overview

PyArco is a Python wrapper around [Arco](https://github.com/rbdannenberg/arco), a real-time sound synthesis engine by Roger Dannenberg (CMU). It translates the existing Serpent (`.srp`) wrapper layer into Python, providing a Pythonic API for controlling Arco's unit generator graph via O2 messages.

**Key constraints:**
- Python 3.10+
- Cross-platform (Windows, Linux, macOS)
- pip-installable (`pip install pyarco`), O2 shared library build as documented prerequisite
- Speed and low latency are top priorities
- Faithful to the Serpent reference implementation

---

## Architecture

Layered architecture: thin transport at the bottom, Serpent-derived core in the middle, Pythonic API on top.

```
┌─────────────────────────────┐
│  Instrument Builder Tool    │  ← guided instrument construction, code generation
├─────────────────────────────┤
│  Instruments & Synth        │  ← Instrument, Synth polyphony, ParamDescr
├─────────────────────────────┤
│  Ugen Subclasses            │  ← all 57 .srp files ported, grouped by category
├─────────────────────────────┤
│  Core (Serpent-derived)     │  ← Ugen base, IDPool, Const, ActionRegistry
├─────────────────────────────┤
│  Transport (ctypes O2)      │  ← o2_initialize, o2_send_cmd, o2_poll
└─────────────────────────────┘
```

The `ArcoEngine` context manager owns all state (no globals): O2 connection, ID pool, action registry, system ugens, and the poll loop.

---

## Package Structure

```
pyarco/
├── pyproject.toml
├── README.md
├── docs/
│   └── building-o2.md
├── scripts/
│   └── build_o2.py
├── src/
│   └── pyarco/
│       ├── __init__.py
│       ├── engine.py
│       ├── transport/
│       │   ├── __init__.py
│       │   ├── o2_ctypes.py
│       │   └── o2_types.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── id_pool.py
│       │   ├── ugen.py
│       │   ├── const.py
│       │   ├── actions.py
│       │   └── rates.py
│       ├── ugens/
│       │   ├── __init__.py
│       │   ├── generators.py
│       │   ├── envelopes.py
│       │   ├── routing.py
│       │   ├── processors.py
│       │   ├── analysis.py
│       │   ├── math.py
│       │   ├── io.py
│       │   └── utility.py
│       ├── instruments/
│       │   ├── __init__.py
│       │   ├── instrument.py
│       │   ├── synth.py
│       │   └── builder.py
│       ├── ui/
│       │   ├── __init__.py
│       │   ├── scope.py
│       │   ├── slider.py
│       │   └── audiodev.py
│       └── async_support.py
├── tests/
│   ├── unit/
│   │   ├── test_id_pool.py
│   │   ├── test_ugen.py
│   │   ├── test_const.py
│   │   ├── test_actions.py
│   │   └── test_engine.py
│   └── integration/
│       ├── conftest.py
│       ├── test_sine.py
│       └── test_mix.py
```

Ugens are grouped by category (not one file per class) since many are small. The `transport/` layer is isolated and swappable. The `core/` layer holds Serpent-derived internals. The `instruments/` subpackage includes the builder tool.

---

## Transport Layer

### `transport/o2_ctypes.py`

Thin ctypes wrapper that loads the O2 shared library and exposes C functions with typed signatures.

```python
class O2Library:
    def __init__(self, lib_path: str | None = None):
        # Discovery order:
        # 1. Explicit lib_path argument
        # 2. PYARCO_O2_LIB environment variable
        # 3. Platform defaults: libo2.so / libo2.dylib / o2.dll
        ...

    # Core lifecycle
    def o2_initialize(self, ensemble_name: str) -> int: ...
    def o2_finish(self) -> None: ...
    def o2_poll(self) -> int: ...
    def o2_time_get(self) -> float: ...

    # Sending messages
    def o2_send_cmd(self, address: str, time: float, type_string: str, *args) -> int: ...
    def o2_send(self, address: str, time: float, type_string: str, *args) -> int: ...

    # Receiving messages
    def o2_method_new(self, path: str, type_string: str, handler, info,
                      coerce: bool, parse: bool) -> int: ...

    # Service discovery
    def o2_service_new(self, service_name: str) -> int: ...
```

### `transport/o2_types.py`

O2 type string constants and helpers:

```python
O2_INT32 = "i"
O2_FLOAT = "f"
O2_STRING = "s"
O2_DOUBLE = "d"
O2_INT64 = "h"
```

### Performance

- Pre-allocate reusable ctypes argument buffers to avoid per-call conversion overhead
- Cache ctypes function references as local variables in hot paths
- Use `o2_send` (UDP) for real-time parameter updates; `o2_send_cmd` (TCP) only where reliability is required

---

## Core Layer

### `core/rates.py`

```python
AUDIO = "a"   # 32 samples/block, ~44100 Hz
BLOCK = "b"   # 1 sample/block, ~1378 Hz
CONST = "c"   # scalar, updated by messages
```

### `core/id_pool.py`

```python
class IDPool:
    RESERVED = 10  # IDs 0-9 for system ugens

    def __init__(self, max_ids: int = 1024):
        self._free: list[int]          # available IDs (stack, O(1) pop/append)
        self._pending_free: list[int]  # waiting for flush

    def alloc(self) -> int: ...        # pop from _free
    def free(self, id: int) -> None: ...       # append to _pending_free
    def flush(self, send_fn) -> None: ...      # batch-send /arco/unref, return IDs to _free
```

Pre-allocated fixed array, `O(1)` alloc/free via stack. `flush()` batches all pending `unref` messages into a single poll tick.

### `core/ugen.py`

The base class, closely following Serpent's `Ugen`:

```python
class Ugen:
    __slots__ = ("id", "engine", "classname", "chans", "rate",
                 "inputs", "action_id", "_addr_cache")

    def __init__(self, engine: "ArcoEngine", classname: str, chans: int,
                 rate: str, type_string: str, *input_triples,
                 no_msg: bool = False, omit_chans: bool = False):
        self.id = engine.id_pool.alloc()
        self.engine = engine
        self.classname = classname
        self.chans = chans
        self.rate = rate
        self.inputs: dict[str, Ugen] = {}
        self.action_id: int | None = None
        self._addr_cache: dict[str, str] = {}
        # Auto-coerce numbers to Const, build inputs dict,
        # send /arco/<classname>/new message (unless no_msg)

    # Core methods — all return self for chaining
    def set(self, name: str, value: float | "Ugen", chan: int = 0) -> "Ugen": ...
    def play(self, gain: float = 1.0) -> "Ugen": ...
    def mute(self) -> "Ugen": ...
    def run(self) -> "Ugen": ...
    def unrun(self) -> "Ugen": ...
    def term(self, dur: float = 0) -> "Ugen": ...
    def trace(self, flag: bool = True) -> "Ugen": ...

    # Fade methods
    def fade(self, dur: float, mode: int = FADE_SMOOTH) -> "Ugen": ...
    def fade_in(self, dur: float, mode: int = FADE_SMOOTH) -> "Ugen": ...

    # Lifecycle
    def atend(self, action, arg=None, mask: int = ACTION_END_OR_TERM) -> None: ...
    def __del__(self) -> None: ...  # returns ID to pool
```

**Type string convention (from Serpent):** `"U"` means "Ugen input" — numbers are auto-coerced to `Const`. Other characters (`"f"`, `"i"`, `"s"`) are passed as-is. Input triples are: `(param_name, param_value, valid_rates_string)`.

**Performance:** `__slots__` on all Ugen classes. O2 address strings (e.g., `/arco/sine/set_freq`) are pre-computed at construction time and cached in `_addr_cache`.

### `core/const.py`

```python
class Const_like(Ugen):
    __slots__ = ("_values",)
    def __init__(self, engine, value: float | list[float], chans: int | None = None): ...
    def value(self) -> float: ...

class Const(Const_like):
    def set(self, value: float) -> "Const": ...
    def set_chan(self, chan: int, value: float) -> "Const": ...
```

### `core/actions.py`

```python
ACTION_TERM = 1
ACTION_ERROR = 2
ACTION_EVENT = 8
ACTION_END = 16
ACTION_REM = 32
ACTION_FREE = 64
ACTION_END_OR_TERM = ACTION_END | ACTION_TERM

class UgenAction:
    __slots__ = ("target", "method", "params")
    target: weakref.ref
    method: str
    params: tuple

class ActionRegistry:
    def __init__(self): ...
    def register(self, ugen: Ugen, mask: int, target, method: str, *params) -> int: ...
    def dispatch(self, key: int, status: int, uid: int) -> None: ...
    def remove(self, key: int) -> None: ...
```

The `ActionRegistry` lives on the `ArcoEngine`. When the server sends `/actl/act key status uid`, the engine's O2 handler calls `dispatch()`. Targets are held as weak references so actions don't prevent garbage collection.

---

## ArcoEngine

```python
class ArcoEngine:
    def __init__(self,
                 ensemble: str = "arco",
                 o2_lib_path: str | None = None,
                 max_ids: int = 1024,
                 latency: float = 10.0,
                 buffer_size: int = 512,
                 input_device: int = -1,
                 output_device: int = -1):
        self.o2 = O2Library(o2_lib_path)
        self.id_pool = IDPool(max_ids)
        self.actions = ActionRegistry()
        self._running = False

        # System ugens (created during start)
        self.zero: Ugen          # ZERO_ID = 0
        self.zerob: Ugen         # ZEROB_ID = 1
        self.input: Ugen         # INPUT_ID = 2
        self.output: Ugen        # OUTPUT_ID = 3

    def start(self) -> None:
        """Full startup sequence:
        1. o2_initialize(ensemble)
        2. o2_service_new("arco")
        3. o2_service_new("actl") + register /actl handlers
        4. Send /arco/reset, wait for /actl/reset confirmation
        5. Create system ugens (zero, zerob, input, output)
        6. Send /arco/open with device/buffer/latency config
        7. Wait for /actl/started confirmation
        """

    def stop(self) -> None:
        """Shutdown: flush pending frees, send /arco/reset, o2_finish()"""

    def poll(self) -> None:
        """Single tick: o2_poll() + id_pool.flush(). Minimal work, no allocations."""

    def run_loop(self, callback=None, tick: float = 0.001) -> None:
        """Blocking poll loop. Calls callback() each tick if provided."""

    def send(self, address: str, type_string: str, *args) -> None:
        """Send O2 command (timestamp=0, immediate delivery)."""

    def send_timed(self, address: str, time: float, type_string: str, *args) -> None:
        """Send O2 command with timestamp for scheduled delivery."""

    def time(self) -> float:
        """Current O2 global time."""

    # Context manager
    def __enter__(self) -> "ArcoEngine":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
```

**Usage:**
```python
with ArcoEngine() as engine:
    sine = Sine(engine, chans=1, freq=440.0, amp=0.5)
    sine.play()
    engine.run_loop()
```

The `actl` service handlers are registered in `start()` to handle `/actl/reset`, `/actl/started`, `/actl/act`, and `/actl/free` messages from the server.

---

## Ugen Subclasses

All 57 `.srp` files ported, grouped by category. Every subclass follows the same pattern — call `super().__init__()` with the Serpent-matching type string and input triples. All use `__slots__`.

### `ugens/generators.py`

Sine, Fmosc, Buzz, Tableosc, Tableoscb, Supersaw, Granstream.

```python
class Sine(Ugen):
    __slots__ = ()
    def __init__(self, engine, chans=1, freq=440.0, amp=1.0):
        super().__init__(engine, "sine", chans, AUDIO, "UU",
                         "freq", freq, "bc",
                         "amp", amp, "bc")
```

### `ugens/envelopes.py`

Pwl, Pwlb, Pwe, Pweb, Steps. Inherit from shared Envelope base:

```python
class Envelope(Ugen):
    __slots__ = ()
    def start(self) -> "Envelope": ...
    def stop(self) -> "Envelope": ...
    def decay(self, dur: float) -> "Envelope": ...
```

### `ugens/routing.py`

Mix, Sum, Sumb, Thru, Zero, Zerob, Route, Pan, Stdistr, Blend, Feedback.

```python
class Mix(Ugen):
    __slots__ = ("_named_inputs",)
    def ins(self, name: str, ugen: Ugen, gain: float = 1.0) -> "Mix": ...
    def rem(self, name: str) -> "Mix": ...
    def set_gain(self, name: str, gain: float) -> "Mix": ...
    def swap(self, name: str, ugen: Ugen) -> "Mix": ...
```

### `ugens/processors.py`

Fader, Delay, Delayvi, Reverb, Allpass, OlapitchShift, PV, Chorus.

### `ugens/analysis.py`

Probe, Vu, Yin, Onset, SpectralCentroid, SpectralRolloff, Trig, Chorddetect.

### `ugens/math.py`

Mult, Add, Sub, Div, Max, Min, Clip, and unary operations.

### `ugens/io.py`

Fileplay, Filerec, Recplay, Granstream, Flsyn.

### `ugens/utility.py`

Dnsampleb, Upsample, DualSlewb, Smoothb.

Every subclass is verified against its `.srp` counterpart for: constructor parameters, O2 message format (address, type string, parameter order), available methods, and valid input rates. Where the Serpent file has audio/block rate pairs (e.g., `Sum`/`Sumb`), both are ported.

---

## Instruments & Builder

### `instruments/instrument.py`

Direct port of `instr.srp`:

```python
class ParamDescr:
    __slots__ = ("name", "ugen", "input_name", "low", "high", "smooth")
    def __init__(self, name: str, ugen: Ugen, input_name: str,
                 low: float = 0, high: float = 1, smooth: float = 0): ...

class Instrument(Ugen):
    def __init__(self, engine, name: str, chans: int = 1): ...
    def param(self, name: str, ugen: Ugen, input_name: str, **kwargs) -> ParamDescr: ...
    def set(self, name: str, value: float) -> "Instrument": ...
    def finish(self, status: int = 0) -> None: ...
```

### `instruments/synth.py`

Direct port of `synth.srp`:

```python
class Synth:
    def __init__(self, engine, instrument_class: type[Instrument],
                 max_voices: int = 16): ...
    def note_on(self, pitch: float, vel: float, **params) -> Instrument: ...
    def note_off(self, pitch: float) -> None: ...
    def all_off(self) -> None: ...
```

### `instruments/builder.py`

User-facing tool for guided instrument construction with code generation:

```python
class InstrumentBuilder:
    def __init__(self, engine, name: str, chans: int = 1): ...

    def add_ugen(self, name: str, ugen_class: type[Ugen], **kwargs) -> "InstrumentBuilder": ...
    def add_param(self, name: str, target_ugen: str, input_name: str,
                  low: float = 0, high: float = 1,
                  smooth: float = 0) -> "InstrumentBuilder": ...
    def set_output(self, ugen_name: str) -> "InstrumentBuilder": ...
    def build(self) -> type[Instrument]: ...
    def to_python(self) -> str: ...
```

**Usage:**
```python
SubSynth = (InstrumentBuilder(engine, "SubSynth")
    .add_ugen("osc", Supersaw, freq=440.0)
    .add_ugen("filt", Biquad, input="osc", freq=2000.0, q=1.0)
    .add_ugen("env", Pwlb)
    .add_ugen("amp", Mult, input1="filt", input2="env")
    .add_param("freq", "osc", "freq", low=20, high=20000)
    .add_param("cutoff", "filt", "freq", low=100, high=15000, smooth=0.01)
    .set_output("amp")
    .build())

synth = Synth(engine, SubSynth, max_voices=8)
synth.note_on(60, 0.8, freq=261.6, cutoff=5000)
```

`to_python()` generates standalone Python source code for the instrument class so users can customize further.

---

## UI

### `ui/scope.py`

Port of `arcoscope.srp` — oscilloscope display.

### `ui/slider.py`

Port of `arcoslider.srp` — slider controls.

### `ui/audiodev.py`

Port of `audiodev.srp` — audio device enumeration and management.

---

## Async Support

Thin asyncio adapter that wraps the synchronous engine:

```python
class AsyncArcoEngine:
    def __init__(self, engine: ArcoEngine, tick: float = 0.001): ...

    async def start(self) -> None:
        self._engine.start()
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._task.cancel()
        self._engine.stop()

    async def _poll_loop(self) -> None:
        while True:
            self._engine.poll()
            await asyncio.sleep(self._tick)

    async def __aenter__(self) -> "AsyncArcoEngine":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    def __getattr__(self, name):
        return getattr(self._engine, name)
```

All ugen creation and manipulation stays synchronous (O2 message sends are non-blocking). The adapter just runs the poll loop as an asyncio task. Users can trade CPU for latency via the `tick` parameter (e.g., `tick=0.0005` for sub-millisecond response).

---

## Performance

Speed and low latency are top priorities throughout:

- **`__slots__`** on `Ugen` and all subclasses — eliminates per-instance `__dict__`, faster attribute access, lower memory
- **Cached O2 addresses** — pre-computed at construction time (e.g., `self._addr_cache["set_freq"] = "/arco/sine/set_freq"`)
- **Pre-allocated ctypes buffers** — reusable argument buffers to avoid per-call conversion overhead
- **Cached ctypes function references** — local variables in hot paths to avoid attribute lookup
- **UDP for real-time** — `o2_send` (UDP) for parameter updates, `o2_send_cmd` (TCP) only where reliability is required
- **Minimal poll loop** — `o2_poll()` → `id_pool.flush()` → optional callback. No allocations per tick.
- **Batched unref** — `flush()` sends all pending `/arco/unref` messages in one poll tick
- **No validation in hot paths** — server rejects invalid input; avoid redundant Python-side checks on `set()` and `repl_*`
- **`set()` on Const** — single O2 message directly, no intermediate objects

---

## Testing Strategy

### Unit Tests (`tests/unit/`)

Run without Arco server using a mock O2 layer:

```python
class MockO2Library:
    def __init__(self):
        self.messages: list[tuple[str, str, tuple]] = []

    def o2_send_cmd(self, addr, time, types, *args):
        self.messages.append((addr, types, args))
        return 0
```

Coverage:
- **IDPool** — alloc/free/flush cycles, exhaustion, double-free prevention
- **Ugen base** — constructor sends correct `/arco/<class>/new`, `set()` sends `set_*` or `repl_*`, `__del__` returns ID to pool
- **Each ugen subclass** — O2 message format matches the corresponding `.srp` file (address, type string, parameter order)
- **Actions** — register, dispatch, weak ref cleanup
- **Engine** — startup sequence sends correct messages in correct order

### Serpent Parity Tests

A special category within unit tests. For each `.srp` file, verify the Python class produces identical O2 messages for the same inputs. These are the primary correctness guarantee.

### Integration Tests (`tests/integration/`)

Require a running Arco server:
- **Smoke test** — engine start, create Sine, play 100ms, mute, stop
- **Parameter updates** — `set()` a Const, `repl_*` with a ugen, confirm no errors
- **Mix routing** — `ins`/`rem`/`swap`, verify output changes
- **Envelope lifecycle** — Pwlb with `atend(MUTE)`, confirm termination and disconnect
- **Instrument test** — build a multi-ugen instrument via InstrumentBuilder, play notes, tear down
- **Synth polyphony** — `note_on`/`note_off` cycling, voice stealing, `all_off`
- **Stress test** — rapid ugen creation/destruction, confirm no ID leaks or server crashes

### CI

Unit tests run on every commit. Integration tests run on-demand (tagged or manual trigger) since they require a running Arco server.

---

## Distribution

- **Package:** pip-installable via `pip install pyarco`
- **Python:** 3.10+
- **Prerequisite:** O2 shared library must be compiled and accessible. `docs/building-o2.md` provides cross-platform instructions. `scripts/build_o2.py` wraps CMake for convenience.
- **Library discovery:** explicit path → `PYARCO_O2_LIB` env var → platform defaults

---

## Implementation Order

1. Transport layer — ctypes O2 wrapper, library discovery
2. Core — IDPool, rates, Const, Ugen base class, ActionRegistry
3. Engine — ArcoEngine with startup/shutdown sequence
4. System ugens — Zero, Zerob, Thru (needed for startup)
5. Generator ugens — Sine, Fmosc, Buzz, Tableosc, Supersaw
6. Envelope ugens — Pwl, Pwlb, Pwe, Pweb, Steps
7. Routing ugens — Mix, Sum, Route, Pan, Blend, Feedback
8. Processor ugens — Fader, Delay, Reverb, Allpass, PV, OlapitchShift
9. Analysis ugens — Probe, Vu, Yin, Onset, SpectralCentroid
10. Math/utility ugens — Mult, Add, Clip, Dnsampleb, Upsample
11. I/O ugens — Fileplay, Filerec, Recplay, Granstream, Flsyn
12. Instruments — Instrument, Synth, InstrumentBuilder
13. UI — Arcoscope, Arcoslider, audiodev
14. Async support — AsyncArcoEngine
15. Build script — `scripts/build_o2.py`
16. Packaging — pyproject.toml, README, docs
