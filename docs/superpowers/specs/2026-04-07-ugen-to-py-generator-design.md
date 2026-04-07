# `.ugen` to `.py` Code Generator — Design Spec

## Summary

A standalone Python script that reads Arco `.ugen` DSL files and generates
Python wrapper classes for PyArco. Produces a single `arco_generated.py` file
that integrates with the existing `arco.py` via wildcard import.

## Decisions

- **Location:** `tools/ugen2py.py` in the PyArco repo
- **Output:** Single file `python25/arco_generated.py`
- **Parser:** Standalone, no dependency on Arco's `preproc/` code
- **Scope:** Existing `.ugen` files only (~11); hand-written wrappers stay in `arco.py`
- **Generation style:** Template strings (f-strings)

## Input: `.ugen` File Parsing

The generator takes a path to an Arco `ugens/` directory and finds all
`*.ugen` files. For each file, it extracts signature lines (before the
`FAUST` keyword) and relevant `declare` directives.

### Signature syntax

```
classname(param1: <rate>, param2: <rate>, ...): <output_rate>
```

Rate specifiers: `a` = audio only, `b` = block only, `ab` = either
(generates both variants), `c` = constant (float). A digit prefix means
fixed channel count (e.g. `2a` = stereo audio-rate).

### FAUST declare directives

- `declare interpolated "param1 param2"` — params with linear interpolation
- `declare terminate "input"` — auto-terminate when input ends

### Data model

```python
@dataclass
class Param:
    name: str
    rate: str        # "a", "b", "ab", "c"
    chans: int = 0   # 0 = dynamic, >0 = fixed

@dataclass
class Signature:
    name: str
    params: list[Param]
    output_rate: str  # "a" or "b"
    output_chans: int = 0
    interpolated: list[str] = field(default_factory=list)
    terminate: list[str] = field(default_factory=list)
```

Multiple signatures per `.ugen` file are supported (e.g. `sine` + `sineb`).

## Output: Generated Python Classes

For each `Signature`, the generator emits a class with four concerns:

### 1. Rate validation

Only params with a **single fixed rate** get validation. Params with `ab`
(accepts either) get no rate check.

Block-rate classes check that inputs with rate `"b"` are block-rate:

```python
if not isinstance(freq, (int, float)) and freq.rate != B_RATE:
    print("ERROR: 'freq' input to Ugen 'sineb' must be block rate")
    return
```

Audio-rate classes check inputs with rate `"a"` (not `"ab"`) against `A_RATE`.

### 2. Channel computation

Dynamic channels: nested `max_chans()` calls across all `U`-type inputs.
Fixed channels (digit prefix in rate spec): use the fixed value directly.

### 3. Types string

Signal params (`a`, `b`, `ab`) map to `"U"`. Constant params (`c`) map to
`"f"`.

### 4. super().__init__() call

```python
super().__init__("ClassName", chans, RATE, "types_string", None, None,
                 'param1', param1, 'param2', param2, ...)
```

### Full example

From `lowpass(input: a, cutoff: ab): a`:

```python
class Lowpass(Ugen):
    def __init__(self, input, cutoff, chans=None):
        if not isinstance(input, (int, float)) and input.rate != A_RATE:
            print("ERROR: 'input' input to Ugen 'lowpass' must be audio rate")
            return
        if chans is None:
            chans = max_chans(max_chans(1, input), cutoff)
        super().__init__("Lowpass", chans, A_RATE, "UU", None, None,
                         'input', input, 'cutoff', cutoff)
```

## File Output & Integration

### Generated file structure

`python25/arco_generated.py` contains:

1. Header comment (auto-generated marker, timestamp, source `.ugen` paths)
2. Import: `from arco import Ugen, Const, max_chans, A_RATE, B_RATE, C_RATE, o2lite`
3. All generated classes, sorted alphabetically

### Integration with arco.py

At the bottom of `arco.py`:

```python
try:
    from arco_generated import *
except ImportError:
    pass  # generated wrappers not yet built
```

Generated classes with the same name as hand-written ones intentionally
overwrite them. Over time, validated hand-written wrappers with matching
`.ugen` files can be removed from `arco.py`.

### CLI

```
python tools/ugen2py.py /path/to/arco/ugens/ -o python25/arco_generated.py
```

## Edge Cases

- **Fixed channels** (`overdrive(snd: 2a, ...): 2a`): skip `max_chans()`,
  use the fixed value
- **Constant params** (`c` rate): map to `"f"` in types string, no rate
  validation
- **Multiple signatures per file**: each becomes its own class
- **Name casing**: class name title-cased (`sine` -> `Sine`), O2 address
  uses original lowercase

## Out of Scope

The generator does NOT handle:

- Custom methods (e.g. `Blend.set_gain()`, `Granstream.set_polyphony()`)
- Dynamic input management (Mix, Route, Sum)
- Envelope point-array logic
- Math/Unary factory patterns

These remain hand-written in `arco.py`.

## Validation

For `.ugen` files with matching hand-written wrappers in `arco.py` (Sine,
Sineb, Lowpass, Reson, Resonb, etc.), diff generated output against the
hand-written version to verify functional equivalence: same types string,
same rate checks, same channel computation.

## Available `.ugen` Files (~11)

| File | Signatures |
|------|-----------|
| `sine.ugen` | `sine(freq:ab, amp:ab):a` / `sineb` |
| `mult.ugen` | `mult(x1:ab, x2:ab):a` / `multb` |
| `lowpass.ugen` | `lowpass(input:a, cutoff:ab):a` / `lowpassb` |
| `highpass.ugen` | `highpass(input:a, cutoff:ab):a` / `highpassb` |
| `reson.ugen` | `reson(input:a, center:ab, q:ab):a` / `resonb` |
| `notch.ugen` | `notch(...)` |
| `noisegate.ugen` | `noisegate(input:a, threshold:b, attack:b, hold:b, release:b):a` |
| `overdrive.ugen` | `overdrive(snd:2a, gain:b, tone:b, volume:b):2a` |
| `sttest.ugen` | `sttest(input:2a, hz1:c, hz2:c):2a` |
| `stnoisegate.ugen` | `stnoisegate(...)` |
| `zitarev.ugen` | `zitarev(input:2a, wet:b, gain:b, rt60:b):2a` |
