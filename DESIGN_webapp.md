# Arco Test Webapp — Design

NiceGUI app extending the existing `init.py` demo. Goal: a local tool for
testing Arco components with live parameter control, signal chain building,
monitoring, and the ability to test ugens created with the Python library.

---

## What Exists Today

`init.py` is a single-file NiceGUI app (~1400 lines) with:

- **DemoState** singleton — tracks connection status and active ugens
- **14 demo cards** across 7 tab categories (Oscillators, Filters, Effects,
  Envelopes, Mixing, Math, Utilities)
- Each card is self-contained: creates ugens on play, destroys on cleanup
- Sliders send `set()` calls for real-time parameter changes
- Left drawer with vertical tab navigation
- Connect button in header for o2lite initialization

**What works well:** direct, per-ugen test cards with live sliders. Simple
to understand and extend.

**What's missing:**

1. No way to connect ugens together (each demo is an island)
2. No monitoring — you hear the output but can't see levels, waveforms, or
   spectral data
3. No coverage for Instrument/Synth/Reverb/Supersaw from `arco_instr.py`
4. No way to test custom ugen chains built from the Python library
5. Lots of copy-paste boilerplate across demo functions

---

## Architecture

### File Structure

```
python25/
  arco.py              # unchanged — core library
  arco_instr.py        # unchanged — instrument framework
  webapp/
    __init__.py        # empty
    app.py             # entry point, page layout, header/drawer
    state.py           # AppState (replaces DemoState), connection, ugen registry
    components/
      __init__.py
      ugen_card.py     # base card component (eliminates boilerplate)
      param_control.py # slider/knob/toggle wrappers that auto-bind to ugen params
      monitor.py       # VU meter, waveform, spectral display components
      chain_builder.py # signal chain visual builder
    pages/
      __init__.py
      oscillators.py   # Sine, Sineb, Tableosc demos
      filters.py       # Lowpass, Reson, Allpass demos
      effects.py       # Delay, Blend, Granstream, PitchShift demos
      envelopes.py     # Pwl, Pwe, Pweb demos
      mixing.py        # Fader, Sum, Mix, Fade, Route demos
      math_ops.py      # Math, Mathb, Unary demos
      instruments.py   # NEW: Reverb, Supersaw, custom Instrument demos
      chain.py         # NEW: signal chain builder page
      sandbox.py       # NEW: Python code editor for custom ugen testing
      monitor.py       # NEW: monitoring/visualization page
      utilities.py     # Panning, pitch, velocity (no audio)
```

### Key Design Decisions

**Modular pages** — each tab category lives in its own file. The current
approach of 14 inline functions doesn't scale. Pages register themselves with
the app at import time.

**`UgenCard` base component** — the existing demo cards share ~80% of their
code (status chip, play/stop button, destroy button, slider-to-set wiring).
A base class eliminates this. Each demo just declares its parameters and
creation logic:

```python
class SineCard(UgenCard):
    title = "Sine"
    description = "Audio-rate sine oscillator"

    def define_params(self):
        self.param_slider("freq", 20, 4000, 440, unit="Hz")
        self.param_slider("amp", 0, 1.0, 0.3)

    def create_ugen(self):
        return Sine(self.get("freq"), self.get("amp"))
```

**AppState** — upgraded from DemoState. Adds:

- Ugen registry with parent/child relationships (knows what feeds into what)
- Named output buses (not just the single OUTPUT_ID)
- Event system for monitoring (ugen created, parameter changed, ugen freed)
- Periodic o2lite polling via NiceGUI's `ui.timer`

---

## Feature 1: Live Parameter Control (improve existing)

What changes from current:

- **UgenCard base class** handles the boilerplate. Play/stop, destroy, status
  chip, slider binding all live in one place.
- **ParamControl widgets** — `param_slider`, `param_knob`, `param_toggle`,
  `param_select`. Each auto-wires to `ugen.set(name, value)` on change.
  Supports log-scale for frequency, dB display for amplitude.
- **Hot parameter update** — currently, changing the operation dropdown on
  Math requires destroying and recreating the ugen. The new design should
  support teardown-and-rebuild transparently.
- **Missing ugen demos added:**
  - Oscillators: `Sineb` (block-rate)
  - Filters: `Resonb` (block-rate)
  - Effects: `Feedback`, `Pv` (phase vocoder)
  - Mixing: `Route`, `Addb`, `Sumb`
  - Math: `Unary`/`Unaryb` demo
  - File: `Fileplay`, `Filerec`, `Recplay`
  - Analysis: `Vu`, `Trig`, `Yin`, `Probe`

---

## Feature 2: Signal Chain Builder

A page where you drag ugens onto a canvas and wire outputs to inputs.

### UI Concept

```
┌─────────────────────────────────────────────────────┐
│  Chain Builder                          [▶ Play All] │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐       │
│  │  Sine    │───▶│ Lowpass  │───▶│ [Output] │       │
│  │ 440 Hz   │    │ 2kHz cut │    │          │       │
│  │ amp: 0.3 │    │          │    │          │       │
│  └──────────┘    └──────────┘    └──────────┘       │
│                       ▲                              │
│  ┌──────────┐         │                              │
│  │  Sineb   │─────────┘                              │
│  │ 3 Hz LFO │  (modulates cutoff)                   │
│  └──────────┘                                        │
│                                                      │
│  [+ Add Ugen ▼]                                     │
├─────────────────────────────────────────────────────┤
│  Selected: Lowpass │ cutoff: [====●====] 2000 Hz    │
│                    │ snd: ← Sine (id 102)           │
└─────────────────────────────────────────────────────┘
```

### Implementation Approach

NiceGUI doesn't have a native node-graph widget, so two options:

**Option A: List-based chain builder (simpler, recommended to start)**

- Each ugen is a card in a vertical/grid layout
- Dropdowns to select which ugen feeds each input
- A "connections" summary panel shows the current signal flow
- Uses `ugen.set(input_name, other_ugen)` for wiring

**Option B: Canvas node graph (richer, more work)**

- Use NiceGUI's `ui.html` or `ui.element` with a JS library like
  `@xyflow/react` (React Flow) embedded via `ui.add_body_html`
- Nodes are ugens, edges are signal connections
- Drag-to-connect wiring
- More intuitive but significantly more JS integration work

**Recommendation: start with Option A**, move to Option B later if the
list-based approach feels too clunky.

### How Wiring Works

The chain builder maintains a directed graph of ugen connections. When the
user connects "Sine.output → Lowpass.snd":

```python
# Under the hood:
lowpass_ugen.set('snd', sine_ugen)  # calls repl_snd on the server
state.register_connection(sine_ugen, lowpass_ugen, 'snd')
```

When a ugen is destroyed, the chain builder walks the graph and disconnects
dependents (or replaces with Zero).

---

## Feature 3: Monitoring / Visualization

### VU Meter

Uses Arco's `Vu` ugen. The app creates a Vu instance, attaches it to
whatever ugen the user selects, and polls for level data.

```python
# Arco's Vu sends periodic level reports to a reply address
vu = Vu("/actl/vu", period=0.05)  # 50ms update rate
vu.set('input', some_ugen)

# Register handler for /actl/vu messages
def vu_handler(timestamp, address, types, *args):
    # args contain peak/rms levels
    update_meter_ui(args)
```

Display: horizontal bar with peak hold, green/yellow/red zones.
NiceGUI's `ui.linear_progress` or a custom SVG element.

### Waveform Display

Uses Arco's `Probe` ugen to capture a buffer of samples:

```python
probe = Probe(some_ugen, "/actl/probe")
probe.probe(period=0.1, frames=512, chan=0, nchans=1, stride=32)

# Handler receives sample data
def probe_handler(timestamp, address, types, *args):
    samples = list(args)
    update_waveform(samples)
```

Display: `ui.plotly` or `ui.chart` (Chart.js via NiceGUI) showing the
waveform. Update at ~10 Hz for smooth animation without overloading the UI.

### Spectral Display

Option 1: compute FFT client-side from Probe sample data (simple, good enough).
Option 2: use `SpectralCentroid`/`SpectralRolloff` for summary features.

Recommendation: start with client-side FFT from Probe data. NumPy's
`np.fft.rfft` on 512–1024 samples gives a decent spectrum view.

### Monitor Panel

A collapsible footer or side panel that can attach to any active ugen:

```
┌─ Monitor ─────────────────────────────────────────┐
│ Watching: Lowpass (id 103)  [Change ▼]            │
│                                                    │
│ Level: ████████████░░░░░░░░  -12.3 dB  peak -8.1 │
│                                                    │
│ Waveform:  ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿   │
│                                                    │
│ Spectrum:  ▁▂▅█▇▅▃▂▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁  │
│            20Hz        1kHz        10kHz           │
└────────────────────────────────────────────────────┘
```

---

## Feature 4: Python Sandbox (Test Custom Ugens)

A code editor where you write Python using the arco/arco_instr API directly,
execute it, and hear the result.

### UI

```
┌─ Sandbox ─────────────────────────────────────────┐
│ ┌───────────────────────────────────────────────┐ │
│ │ from arco import Sine, Lowpass, Math          │ │
│ │                                                │ │
│ │ osc = Sine(440, 0.3)                          │ │
│ │ lfo = Sine(5, 200)                            │ │
│ │ fm = Math.add(osc, lfo)                       │ │
│ │ filt = Lowpass(fm, 2000)                      │ │
│ │ filt.play()                                   │ │
│ └───────────────────────────────────────────────┘ │
│                                                    │
│ [▶ Run]  [■ Stop All]  [🗑 Clear]                 │
│                                                    │
│ Output:                                            │
│ > Ugen 102 created and ID allocated                │
│ > Ugen 103 created and ID allocated                │
│ > ...                                              │
│                                                    │
│ Active ugens: osc(102), lfo(103), fm(104),        │
│               filt(105)                            │
└────────────────────────────────────────────────────┘
```

### Implementation

- NiceGUI's `ui.codemirror` (or `ui.textarea` with monospace font) for the
  editor
- `exec()` in a controlled namespace that includes all arco imports
- Capture stdout/stderr and display in the output panel
- Track all ugens created during execution so "Stop All" can mute and destroy
  them
- **Safety**: wrap execution in try/except, limit to arco module namespace

### Presets / Examples

Dropdown with pre-built code examples:

- "Simple sine" — basic play/mute
- "FM synthesis" — Sine modulating Sine
- "Filtered noise" — use Math.rand + Lowpass
- "Supersaw chord" — Supersaw_synth with noteon
- "Reverb chain" — source → Multi_reverb → output
- "Envelope + fade" — Pwl controlling amplitude, then fade out

---

## Feature 5: Instrument Page (from arco_instr.py)

New tab for testing the higher-level constructs:

### Reverb Demo

```
Source: [Sine ▼]  freq: [===●===] 440Hz
RT60:   [====●====] 2.0 s
Wet:    [====●====] 0.5
Cutoff: [====●====] 10000 Hz
Type:   (•) Mono Reverb  ( ) Multi Reverb
Chans:  [1 ▼]
[▶ Play]  [■ Stop]  [🗑 Destroy]
```

### Supersaw Demo

```
Pitch: [====●====] 60 (C4)    Velocity: [====●====] 100
N oscillators: [====●====] 8
Detune:  [====●====] 0.5      Animate: [====●====] 0.3
Rolloff: [====●====] 0.5      Attack:  [====●====] 0.04
Decay:   [====●====] 0.1      Cutoff:  [====●====] 100
LFO freq: [====●====] 5       LFO depth: [====●====] 0
Width: [====●====] 0.5  (stereo only)
[▶ Note On]  [■ Note Off]  [🗑 Destroy]
```

### Synth Polyphony Demo

Keyboard-style interface (or MIDI input if available) that triggers
`noteon`/`noteoff` on a Supersaw_synth instance. Shows active note count,
free notes, finishing notes.

---

## Refactoring Plan

### Phase 1: Extract and restructure (no new features)

1. Create `webapp/` directory structure
2. Extract `DemoState` → `state.py` as `AppState`
3. Build `UgenCard` base component
4. Build `ParamControl` widgets
5. Migrate existing 14 demos to page files using new components
6. Wire up `app.py` entry point
7. Verify everything still works identically

### Phase 2: Missing ugen demos

8. Add demos for uncovered ugens (Sineb, Resonb, Feedback, Route, Unary,
   Fileplay, Vu, Trig, etc.)
9. Add Instrument page (Reverb, Supersaw, Synth)

### Phase 3: Monitoring

10. Implement VU meter component using Arco's Vu ugen
11. Implement waveform display using Probe ugen
12. Implement spectral display (client-side FFT)
13. Add monitor panel (attachable to any ugen)

### Phase 4: Chain builder

14. List-based chain builder (ugen palette, connection dropdowns, flow summary)
15. AppState connection graph tracking
16. Auto-disconnect on ugen destroy

### Phase 5: Sandbox

17. Code editor with exec() in arco namespace
18. Output capture and display
19. Ugen tracking and "Stop All"
20. Preset examples dropdown

---

## Dependencies

Current: `nicegui`, `o2litepy` (via sys.path hack)

To add:
- `numpy` — for client-side FFT in spectral display
- No additional NiceGUI plugins needed; all UI uses built-in components

---

## Open Questions

1. **O2 polling** — the current app doesn't explicitly poll o2lite in a timer.
   For monitoring (Vu, Probe), we need regular polling. NiceGUI's `ui.timer`
   can call `o2lite.poll()` at ~100Hz. Need to verify this works and doesn't
   block the UI event loop.

2. **Probe data format** — need to check exactly what `/actl/probe` sends back.
   The Probe ugen's handler registration pattern needs to be wired through
   o2lite's callback system.

3. **MIDI input** — NiceGUI can receive keyboard events via `ui.keyboard`.
   Mapping computer keyboard to MIDI notes would make the Synth demo much
   more interactive. Not essential for v1.

4. **Hot reload** — NiceGUI supports `reload=True` for development. With the
   modular file structure, this becomes more useful. Verify it works with
   active o2lite connections (may need reconnect logic).
