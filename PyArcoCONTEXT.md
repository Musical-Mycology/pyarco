# PyArco: Python Bindings for Arco

## Project Overview

Python control-side bindings for [Arco](https://github.com/rbdannenberg/arco),
a real-time audio synthesis and analysis engine by Roger Dannenberg (CMU). Arco
is written in C++ and is designed to be language-agnostic. The primary reference
implementation uses **Serpent** (a Python-like language) for control; the Python
port translates that layer to native Python.

**Status:** Working implementation with ~55 ugen wrapper classes (including
base classes and rate variants), an instrument/synth framework, and a
NiceGUI demo app. The next major milestone
is building a `.ugen → .py` code generator to auto-produce wrappers from the
same `.ugen` source files that drive the C++/FAUST/Serpent toolchain.

---

## What Arco Is

Arco is a **modular, real-time DSP engine** — think lightweight SuperCollider
`scsynth` or libpd. It can run as:

1. A **standalone server process** — your Python app sends it O2 messages
2. **Embedded in an application** — Arco linked as a library, polled in your main loop
3. A **full scripting system** — with Serpent as the frontend

Python communicates with Arco entirely through O2 messages. Ugens are identified
by plain integers (IDs chosen by the client); no pointers cross the interface.

---

## Existing Codebase (`python25/`)

The former `arco.py` monolith is now split in two. `arco_engine.py` owns the
connection and bookkeeping; `arco_ugens.py` holds the `Ugen` base class and
all wrapper classes; `arco.py` is now a thin re-export shim (`from
arco_engine import *; from arco_ugens import *`) kept so existing `import
arco` call sites keep working. `arco_instr.py` and `init.py` are unchanged
in role. `python25/tests/` is a new offline pytest suite (35 tests)
exercising lifecycle, constants, and action-dispatch behavior without a
running Arco server, using a `FakeO2Lite` transport.

### `arco_engine.py` — Engine, connection, pool, actions (~430 lines)

**`ArcoEngine`** — owns the O2lite connection, the `UgenID` pool, and the
registry of live ugens. `connect()` performs the O2 handshake (deferring the
`o2lite` import so the module imports without `o2litepy` installed), resets
the Arco server, sets itself as the active engine, and creates the system
ugens (`Zero`, `Zerob`, `Thru` for input, `Sum` for output) by shadowing
IDs 0-3 with `id_num=`. `close()` frees all pool-allocated ugens in reverse
ID order and clears the active-engine global if it was this engine.
`ArcoEngine` is also a context manager (`with ArcoEngine() as engine:` calls
`connect()`/`close()` automatically). `get_engine()` returns the active
engine or raises if none is connected.

**`UgenID` pool** — linked-list free-slot allocator. Default: 1000 slots,
user IDs start at 100. `request_slot()` / `free_slot()` for alloc/dealloc.
Each `ArcoEngine` owns its own pool instance.

**`ArcoEngine._ugens`** — a `weakref.WeakValueDictionary` mapping id to
`Ugen`. This is the crux of the lifecycle model: a ugen is registered here
only if it owns a pool-allocated id, and the entry disappears automatically
once nothing in Python still references that ugen. See "Ugen lifecycle
model" below.

**Action system** — `register_action()`, `actl_act_handler()`, `Action_list`,
`Ugen_action`. Translates Arco's `/actl/act` callbacks into Python method
calls on target objects. `Ugen_action` holds its target via `weakref.ref`
(`target_ref`); the `.target` property dereferences it, returning the live
object or `None`, so registering an action never keeps its target alive.
`actl_act_handler` prunes dead targets on delivery and isolates each
callback in a try/except so one broken handler doesn't stop the rest from
firing.

**Constants & utilities** (unchanged from prior `arco.py`): rate symbols,
audio params, system IDs, math/unary op enums, fade/blend/downsample mode
enums, step/Hz/dB/velocity conversion functions, panning functions.

### `arco_ugens.py` — Ugen base class + wrappers (~1670 lines)

**`Ugen` base class** — all ugen wrappers inherit from this. Key behavior:

- `__init__` takes `id_num=` (borrow an existing id, e.g. system ugens and
  `Instrument`) or, if omitted, pool-allocates an id and registers itself
  in `engine._ugens` (`owns_id = True`). Converts numeric/list inputs to
  `Const` ugens when the type string says `"U"`, builds and sends the
  `/arco/<class>/new` O2 message. Accepts a `types_` string where `"U"` =
  ugen input, `"i"/"f"/"s"/"d"/"B"` = literal typed value. Inputs are
  passed as alternating `(name, value)` pairs.
- `__del__` frees the id — but only if `owns_id` is true and the server
  hasn't already freed it (`_server_freed`). Borrowed-id ugens (system
  ugens, `Instrument`) are no-ops on `__del__`.
- `play()` / `mute()` insert/remove from the output `Sum`, and pin/unpin
  the ugen in `engine.output.members` accordingly.
- `fade(dur)` / `fade_in(dur)` create a `Fader` wrapper for smooth
  transitions, swap output membership, and use a `threading.Timer` to
  release the terminated `Fader` after the fade completes.
- `set(input_name, value)` handles scalars (updates Const in-place), arrays
  (multi-channel Const update), and Ugens (sends `repl_<input>`).
- `atend(action)` registers end-of-life callbacks via the action system.
- `term(dur)` enables server-side termination after the ugen ends.

**Container/graph-mirroring classes** — `Sum`, `Sumb`, `Add`, `Addb`,
`Route`, `Stdistr` track inserted ugens in `self.members` (a client-side
mirror of the server graph); `Mix` repurposes `self.inputs` for the same
purpose. `Thru.set_alternate`, `Recplay.borrow`, and `Wavetables.borrow`
each pin their argument via an instance attribute (`_alternate` /
`_lender`) so the server-side wiring can't outlive the client reference.

**Implemented ugen wrappers** (all hand-written):

| Category | Classes (55 total incl. base classes) |
|----------|---------|
| Base/abstract | `Ugen`, `Const_like`, `Envelope`, `Wavetables` |
| Constants/control | `Const`, `Smoothb` |
| Generators | `Sine`, `Sineb`, `Tableosc`, `Tableoscb` |
| Envelopes | `Pwl`, `Pwlb`, `Pwe`, `Pweb` |
| Fading | `Fader` |
| Processors | `Delay`, `Allpass`, `Lowpass`, `Reson`, `Resonb`, `Feedback` |
| Blending | `Blend`, `Blendb` |
| Math | `Math` (21 static ops), `Mathb` (21 static ops), `Multx`, `Unary` (13 ops), `Unaryb` (13 ops) |
| Routing | `Sum`, `Sumb`, `Route`, `Mix`, `Add`, `Addb`, `Stdistr` |
| File I/O | `Fileplay`, `Filerec`, `Recplay` |
| Granular/spectral | `Granstream`, `Pv`, `Ola_pitch_shift` |
| Analysis | `Vu`, `Trig`, `Probe`, `Yin`, `Onset`, `Chorddetect`, `SpectralCentroid`, `SpectralRolloff` |
| Downsampling | `Dnsampleb`, `Dualslewb` |
| MIDI/soundfont | `Flsyn` |
| System | `Zero`, `Zerob`, `Thru`, `Fanout` |

**Constants & utilities:**

- Rate symbols: `A_RATE = 'a'`, `B_RATE = 'b'`, `C_RATE = 'c'`
- Audio params: `AR = 44100.0`, `BL = 32`, `BR = AR/BL`
- System IDs: `ZERO_ID = 0`, `ZEROB_ID = 1`, `INPUT_ID = 2`, `OUTPUT_ID = 3`
- Math op enums: `MATH_OP_MUL` through `MATH_OP_COS` (21 ops)
- Unary op enums: `UNARY_OP_ABS` through `UNARY_OP_LINEAR_TO_DB` (13 ops)
- Fade/blend/downsample mode enums
- Conversion functions: `hz_to_step`, `step_to_hz`, `step_to_ratio`,
  `ratio_to_step`, `steps_to_hzdiff`, `db_to_linear`, `linear_to_db`,
  `vel_to_linear`, `linear_to_vel`, `vel_to_db`, `db_to_vel`
- Panning: `pan_linear`, `pan_eqlpow`, `pan_45`

### `arco_instr.py` — Instrument framework (~830 lines)

Higher-level abstractions built on `arco_engine.py` / `arco_ugens.py`
(imported via the `arco.py` re-export shim):

**Parameter system** — `param()`, `param_map()`, `param_method()` declare
named, settable parameters backed by `Const`/`Smoothb` ugens or method calls.
Uses a construction-time stack (`_instr_stacks`, keyed by
`threading.get_ident()` so concurrent construction on different threads
doesn't cross-contaminate) collected between `instr_begin()` and
`Instrument.__init__()`. `Param_descr` handles conditioning (clamp, map)
and dispatches `set()` to the right target.

**`Instrument`** — wraps a ugen graph with named parameters. Inherits `Ugen`
but borrows its id from the output ugen via `id_num=` (so wiring an
Instrument into the graph is identical to wiring a plain Ugen, and
`Instrument.__del__` never frees the output ugen's id — the output ugen
owns it). Holds `parameter_bindings` dict.

**`Synth`** — polyphonic note manager. Maintains `notes` (active), `free_notes`
(recyclable), `finishing_notes` (fading out). `noteon()` creates or reuses an
instrument, wires it into an internal `Mix`, handles gain and panning.
`noteoff()` triggers instrument release. Subclasses implement `instr_create()`.

**`Note` / `Score`** — simple event representation. `Score` supports `append`,
`merge`, `stretch`, and blocking `play()`.

**`Reverb` / `Multi_reverb`** — comb + allpass reverb (ported from Nyquist).
Configurable RT60, wet/dry, lowpass cutoff. Multi_reverb splits to stereo.

**`Supersaw_instr` / `Supersaw_synth`** — multi-oscillator supersaw with
detune, animate, rolloff, anti-aliased wavetables, LFO vibrato, lowpass filter,
envelope. Demonstrates the full Instrument/Synth pattern.

### `init.py` — NiceGUI demo app (~700+ lines)

Interactive browser-based UI for testing ugens against a running Arco server.
Uses NiceGUI (`nicegui` package). Features:

- `DemoState` singleton managing connection and active ugens
- Individual demo cards for: Sine, Delay, Granstream, Fileplay, Math,
  Blend, Envelope, Fader, Mix, and others
- Each card has sliders/controls wired to live ugen parameters
- Connect button constructs an `ArcoEngine()` and calls `engine.connect()`

---

### Ugen lifecycle model

- `ArcoEngine._ugens` is a `weakref.WeakValueDictionary`. A ugen lives as
  long as Python references it; dropping the last reference triggers
  `__del__`, which sends `/arco/free` and returns the id to the pool.
- Client-side references mirror the server graph: each ugen's `inputs`
  dict holds its input ugens; container ugens (`Sum`, `Sumb`, `Add`,
  `Addb`, `Route`, `Stdistr`) track inserted ugens in `self.members`;
  `Mix` uses `self.inputs`. `play()` pins the ugen in
  `engine.output.members` until `mute()` — audible implies alive.
  `Thru.set_alternate`, `Recplay.borrow`, and `Wavetables.borrow` pin
  their argument (`_alternate` / `_lender`) — the server-side wiring
  must never outlive the client-side reference.
- `owns_id`: pool-allocated ids are owned (freed by `__del__`); ugens
  created with an explicit `id_num` (system ugens, `Instrument` wrappers
  borrowing their output's id) never free their id and are not in the
  registry.
- `_server_freed`: set when the server is known to have freed the ugen
  (terminating faders); `__del__` then skips the redundant `/arco/free`.
- Fades: `fade()`/`fade_in()` swap output membership and release the
  terminated `Fader` after `dur + _FADE_CLEANUP_MARGIN` via a timer.
  A second `fade()` adjusts the in-flight fader instead of re-swapping;
  `mute()` during a fade targets the live fader.
- Action targets (`atend`, `register_action`) are weakrefs — the action
  system never keeps a ugen alive; dead targets are pruned on delivery
  and callback exceptions are isolated per dispatch.

### Known follow-ups (deliberate gaps)

- `term(dur)` outside the fade helpers still desyncs client pool from
  server: the server frees the id at termination but the client slot
  stays allocated until the Python object dies. Full fix needs
  client-side `ACTION_FREE` handling.
- `/actl/act` is never registered as an o2lite method handler in
  `connect()`, so server-initiated actions (`atend`, `Instrument.finish`
  / `Synth.is_finished` note recycling) do not fire yet.
- `play()` during an in-flight `fade_in()` inserts the ugen at full
  volume while the fader is still ramping — audible overlap until the
  fade-in timer completes. `play()` could check `fade_in_lookup`.
- A `fade()` call racing the previous fade's cleanup timer at the exact
  firing instant can send dur/mode messages for an already-freed fader
  id (stale message, no crash, no leak).
- Instrument-construction contexts orphaned by an exception between
  `instr_begin()` and `Instrument.__init__()` linger on that thread's
  stack; if the OS reuses the thread id, the orphan can corrupt a later
  construction (documented in code; callback wrappers should
  catch-and-clear).
- Remaining `print("ERROR/WARNING: ...")` calls in arco_ugens.py /
  arco_instr.py could migrate to the `pyarco` logger for consistency.

---

## Core Concepts

### Signal Rates

| Rate | Symbol | Description |
|------|--------|-------------|
| Audio rate | `A_RATE = 'a'` | 32 samples per block (44,100 Hz) |
| Block rate | `B_RATE = 'b'` | 1 sample per block (~1,378 Hz) |
| Constant rate | `C_RATE = 'c'` | Float updated by control messages; stored in a `Const` ugen |

Many ugens come in audio/block pairs (e.g. `Sine`/`Sineb`, `Math`/`Mathb`).
The block-rate variants enforce rate checks on their inputs at construction time.

### Multichannel Signals

- Channel count set at creation (`chans` parameter)
- Default = `max_chans()` across all inputs
- Single-channel inputs broadcast across all output channels
- `Const` supports per-channel values via `set_chan(chan, value)`

### Ugen `__init__` Convention

```python
super().__init__(classname, chans, rate, types_string, no_msg, omit_chans,
                 'input_name1', value1, 'input_name2', value2, ...)
```

`types_string` has one character per input pair: `"U"` = ugen (auto-wraps
numbers in `Const`), `"i"/"f"/"s"/"d"/"B"` = literal typed value. The base
class builds and sends the O2 creation message automatically.

---

## O2: The Control Protocol

All communication goes through **O2** via `o2litepy`. The connection lives
on `ArcoEngine.o2lite` (an instance attribute, set up in `connect()`); code
sends messages via `ArcoEngine.send_cmd(address, time, type_string,
*params)`, which no-ops if the engine isn't currently connected.

### Message Address Format

```
/arco/<class>/<method>  [typed parameters...]
```

### Standard Methods (all ugens)

| Method | O2 address | Description |
|--------|-----------|-------------|
| Create | `/arco/<class>/new` | `id chans input_ids...` |
| Set const input | `/arco/<class>/set_<input>` | `id chan value:float` |
| Swap in ugen | `/arco/<class>/repl_<input>` | `id other_ugen_id` |
| Free | `/arco/free` | `id` |
| Insert into output | `/arco/sum/ins` | `output_id ugen_id` |
| Remove from output | `/arco/sum/rem` | `output_id ugen_id` |

### O2 Type String Characters

| Char | Type |
|------|------|
| `i` | int32 |
| `f` | float |
| `s` | string |
| `d` | double |
| `B` | boolean |

---

## O2 Integration

### o2litepy (the transport layer)

`o2litepy` is a pure-Python O2lite implementation. No C++ compilation or
dynamic library loading required. O2lite connects to the first O2 host it
finds; since Arco links the full O2 library, it serves as that host. All
messages route through Arco.

O2lite lacks some scheduling and peer-to-peer connection management features
of full O2, but these aren't needed for control-side work. The overhead of
Python-side message assembly is negligible relative to complex control logic.

Current initialization (from `ArcoEngine.connect()` in `arco_engine.py`):

```python
from o2lite import O2lite  # imported lazily, inside connect()

self.o2lite = O2lite()
self.o2lite.initialize(self.ensemble, debug_flags="a")
while self.o2lite.time_get() < 0:
    self.o2lite.poll()
    time.sleep(0.01)  # wait for host discovery, bounded by self.timeout
```

`ArcoEngine` is a context manager, so typical usage is
`with ArcoEngine() as engine: ...` (or `engine = ArcoEngine(); engine.connect()`
/ `engine.close()`). The `o2lite` import is deferred into `connect()` so the
rest of the codebase (and the offline test suite) can import `arco_engine`
without `o2litepy` installed.

The `sys.path` currently points to a relative `../../o2/o2litepy/src` —
this should eventually be a proper package dependency.

### Fallback options

**ctypes binding to libo2.so** — lower latency but requires compiling O2.
Only worth it if message-send overhead becomes measurable.

**OSC bridge** — `o2host` relays OSC→O2. Use `python-osc` for UDP.
Extra process hop; good for quick prototyping only.

---

## Key Source Files

### In the Arco repo

| Path | Purpose |
|------|---------|
| `doc/design.md` | System architecture, threading, audio callback model |
| `doc/ugens.md` | Full O2 message reference for every ugen |
| `doc/building.md` | Build system, FAUST toolchain, ugen code generation |
| `arco/ugen.h` | C++ Ugen base class |
| `arco/audioio.cpp` | PortAudio integration, startup/shutdown protocol |
| `apps/basic/` | Minimal server app — good reference for startup sequence |
| `apps/test/` | wxSerpent + Arco integration — control-side reference |
| `serpent/` | Serpent ugen wrapper classes — cross-reference for Python port |
| `arco/preproc/u2f.py` | `.ugen` → FAUST + `.srp` generator — **model for `.ugen` → `.py` generator** |
| `arco/ugens/*/` | `.ugen` source files — **authoritative input for code generation** |

### In this project (`python25/`)

| File | Purpose |
|------|---------|
| `arco_engine.py` | ArcoEngine: O2 connection, weak-ref ugen registry, UgenID pool, action system; constants; conversion utilities |
| `arco_ugens.py` | Ugen base class and ~55 ugen wrapper classes |
| `arco.py` | Thin re-export shim over `arco_engine` + `arco_ugens` |
| `arco_instr.py` | Instrument framework: Param system, Instrument, Synth, Note/Score, Reverb, Supersaw |
| `python25/tests/` | Offline pytest suite (35 tests) — lifecycle, constants, actions; `FakeO2Lite` transport, no server needed |
| `init.py` | NiceGUI demo app for interactive testing |

---

## FAUST Integration & Code Generation

Most Arco ugens are specified in `.ugen` files (a custom DSL) and compiled
via FAUST to C++. The toolchain auto-generates all 2^N rate-combination
variants. Critically, `arco/preproc/u2f.py` already generates Serpent (`.srp`)
wrapper classes from these same `.ugen` descriptions.

**The Python wrappers should ultimately be auto-generated the same way.**
Either extend `u2f.py` or write a sibling script to emit `.py` files from
`.ugen` descriptions (e.g., `arco/ugens/sine/sine.ugen` → `sine.py`).

Strategy: use the existing hand-crafted wrappers in `arco_ugens.py` as the
target template, then build the `.ugen → .py` generator modeled on what
`u2f.py` does for Serpent. The ~55 existing wrapper classes serve as both
reference and validation — generated output should match or improve upon
them.

### The `.ugen` DSL

Each `.ugen` file contains one or more **signatures** followed by a
`FAUST` keyword and the FAUST implementation. The signatures define the
Python/Serpent wrapper interface; the FAUST code defines the DSP.

**Signature syntax:**

```
classname(param1: <rate>, param2: <rate>, ...): <output_rate>
```

Rate specifiers: `a` = audio only, `b` = block only, `ab` = either
(generates both variants), `c` = constant (float set at construction,
updatable by messages). A digit prefix means fixed channel count
(e.g. `2a` = stereo audio-rate).

**Examples from the Arco repo:**

```
# Simple — audio/block pairs auto-generated from "ab" params:
sine(freq: ab, amp: ab): a
sineb(freq: b, amp: b): b

# Filter with terminate declaration (auto-frees when input ends):
lowpass(input: a, cutoff: ab): a
lowpassb(input: b, cutoff: b): b

# Fixed stereo I/O with constant params:
sttest(input: 2a, hz1: c, hz2: c): 2a

# Fixed stereo with block-rate controls:
zitarev(input: 2a, wet: b, gain: b, rt60: b): 2a
overdrive(snd: 2a, gain: b, tone: b, volume: b): 2a

# Multiple block-rate control inputs:
noisegate(input: a, threshold: b, attack: b, hold: b, release: b): a
```

**FAUST `declare` directives** (between signature and `process`):

- `declare interpolated "param1 param2"` — these params get linear
  interpolation when block-rate feeds audio-rate
- `declare terminate "input"` — auto-terminate when this input's ugen ends

### How `u2f.py` Generates `.srp` Wrappers

The codegen pipeline (`arco/preproc/`): `u2f.py` + `params.py` +
`implementation.py`.

1. **Parse signatures** — `params.py::get_signatures()` parses the header
   lines into `Signature` objects (name, list of `Param`, output `Param`).
   Each `Param` has: `name`, `abtype` (rate string), `chans` (int),
   `fixed` (bool).

2. **Parse FAUST** — `implementation.py::prepare_implementation()` extracts
   `process()` parameter names and the `declare interpolated` list.

3. **Generate `.srp`** — for each signature, `u2f.py` emits a Serpent
   function that:
   - Computes `chans` via nested `max_chans()` calls (unless fixed)
   - Validates fixed channel counts
   - Constructs a `Ugen(id, classname, chans, rate, typestring, ...params)`
   - Maps `ab` → `"abc"`, `b` → `"bc"`, `c` → `"f"` for Serpent rate types
   - Maps all signal params to `"U"` in the O2 typestring, constants to `"f"`

**Generated `.srp` example** (from `sine.ugen`):

```serpent
def sine(freq, amp, optional chans):
    if not chans:
        chans = max_chans(max_chans(1, freq), amp)
    Ugen(create_ugen_id(), "sine", chans, 'a', "UU",
         'freq', freq, "abc", 'amp', amp, "abc")

def sineb(freq, amp, optional chans):
    if not chans:
        chans = max_chans(max_chans(1, freq), amp)
    Ugen(create_ugen_id(), "sineb", chans, 'b', "UU",
         'freq', freq, "bc", 'amp', amp, "bc")
```

**For the Python generator**, the equivalent output would be:

```python
class Sine(Ugen):
    def __init__(self, freq, amp, chans=None):
        if chans is None:
            chans = max_chans(max_chans(1, freq), amp)
        super().__init__("Sine", chans, A_RATE, "UU", None, None,
                         "freq", freq, "amp", amp)

class Sineb(Ugen):
    def __init__(self, freq, amp, chans=None):
        if not isinstance(freq, (int, float)) and freq.rate != B_RATE:
            print("ERROR: 'freq' input to Ugen 'sineb' must be block rate")
            return
        if not isinstance(amp, (int, float)) and amp.rate != B_RATE:
            print("ERROR: 'amp' input to Ugen 'sineb' must be block rate")
            return
        if chans is None:
            chans = max_chans(max_chans(1, freq), amp)
        super().__init__("Sineb", chans, B_RATE, "UU", None, None,
                         "freq", freq, "amp", amp)
```

### Available `.ugen` Files (in `arco/ugens/`)

| File | Signatures | Notes |
|------|-----------|-------|
| `sine.ugen` | `sine(freq:ab, amp:ab):a` / `sineb` | Basic oscillator |
| `mult.ugen` | `mult(x1:ab, x2:ab):a` / `multb` | Multiply, with interpolation |
| `lowpass.ugen` | `lowpass(input:a, cutoff:ab):a` / `lowpassb` | First-order LP |
| `highpass.ugen` | `highpass(input:a, cutoff:ab):a` / `highpassb` | First-order HP |
| `reson.ugen` | `reson(input:a, center:ab, q:ab):a` / `resonb` | Resonant BP |
| `notch.ugen` | `notch(...)` | Notch filter |
| `noisegate.ugen` | `noisegate(input:a, threshold:b, attack:b, hold:b, release:b):a` | Gate |
| `overdrive.ugen` | `overdrive(snd:2a, gain:b, tone:b, volume:b):2a` | Stereo distortion |
| `sttest.ugen` | `sttest(input:2a, hz1:c, hz2:c):2a` | Stereo filter test |
| `stnoisegate.ugen` | `stnoisegate(...)` | Stereo noise gate |
| `zitarev.ugen` | `zitarev(input:2a, wet:b, gain:b, rt60:b):2a` | Zita reverb |

**Not all ugens have `.ugen` files.** Many wrappers in `arco_ugens.py` (Mix,
Sum, Route, Envelope, Wavetables, Probe, Vu, Flsyn, etc.) are hand-written
because they have complex custom methods or don't follow the FAUST pattern.
The code generator handles the straightforward FAUST-based ugens; the rest
stay manual.

---

## What's Next

The core library and instrument framework are functional. Remaining work:

1. **`.ugen → .py` code generator** — the main deliverable. Study `u2f.py`
   to understand the `.ugen` DSL, then write a generator that emits Python
   wrapper classes matching the patterns established in `arco_ugens.py`.
   Use the existing hand-written wrappers as validation targets.

2. **Package structure** — currently a flat `python25/` directory with a
   hardcoded `sys.path` to o2litepy. Needs proper Python packaging
   (`pyproject.toml`, `o2litepy` as a dependency).

3. **Non-generated ugen classes** — some wrappers (Mix, Sum, Route, Envelope
   subclasses, Wavetables) have custom methods beyond what `.ugen` files
   describe. These will remain hand-written; the generator handles the
   straightforward cases.

4. **Startup sequence** — `ArcoEngine` now exists as a context manager
   (`connect()` / `close()`, or `with ArcoEngine() as engine:`), replacing
   the old direct `initialize_o2lite()` call. The demo app (`init.py`)
   already uses it. Remaining gap: `/actl/act` is never registered as an
   o2lite method handler in `connect()`, so server-initiated actions
   (`atend`, `Instrument.finish`) don't fire against a live server yet —
   see "Known follow-ups" above.

5. **Testing** — `python25/tests/` now covers ugen lifecycle (ownership,
   weak-ref registry, container membership, fades, borrowing), constants,
   and the action-dispatch system offline, against a `FakeO2Lite` transport.
   What's still untested automatically: behavior against a live Arco
   server (message semantics the server actually enforces, timing/audio
   correctness). That remains manual via the NiceGUI demo (`init.py`).
