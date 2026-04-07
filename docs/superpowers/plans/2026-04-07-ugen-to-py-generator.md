# `.ugen` → `.py` Code Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python script (`tools/ugen2py.py`) that reads Arco `.ugen` DSL files and generates Python wrapper classes into `python25/arco_generated.py`.

**Architecture:** A three-stage pipeline: (1) find and read `.ugen` files, (2) parse signatures and declares into dataclasses, (3) render each signature to a Python class string via f-string templates and write the output file. No external dependencies.

**Tech Stack:** Python 3.10+ (dataclasses, argparse, re, pathlib). pytest for tests.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `tools/ugen2py.py` | CLI entry point, file discovery, output assembly |
| `tools/ugen_parser.py` | Parse `.ugen` files into `Signature`/`Param` dataclasses |
| `tools/ugen_codegen.py` | Render `Signature` objects to Python class source strings |
| `tests/test_ugen_parser.py` | Unit tests for the parser |
| `tests/test_ugen_codegen.py` | Unit tests for code generation |
| `tests/test_ugen2py_integration.py` | End-to-end: `.ugen` file → generated `.py` |
| `tests/fixtures/sine.ugen` | Test fixture: simple audio/block pair |
| `tests/fixtures/lowpass.ugen` | Test fixture: audio-rate-only input |
| `tests/fixtures/overdrive.ugen` | Test fixture: fixed stereo channels |
| `tests/fixtures/sttest.ugen` | Test fixture: constant params |
| `tests/fixtures/noisegate.ugen` | Test fixture: all block-rate controls |
| `python25/arco_generated.py` | Generated output (not committed, added to `.gitignore`) |

---

### Task 1: Data Model

**Files:**
- Create: `tools/ugen_parser.py`
- Create: `tests/test_ugen_parser.py`

- [ ] **Step 1: Write test for Param and Signature dataclasses**

```python
# tests/test_ugen_parser.py
from tools.ugen_parser import Param, Signature


def test_param_defaults():
    p = Param(name="freq", rate="ab")
    assert p.name == "freq"
    assert p.rate == "ab"
    assert p.chans == 0


def test_param_fixed_chans():
    p = Param(name="input", rate="a", chans=2)
    assert p.chans == 2


def test_signature_defaults():
    s = Signature(
        name="sine",
        params=[Param("freq", "ab"), Param("amp", "ab")],
        output_rate="a",
    )
    assert s.name == "sine"
    assert s.output_chans == 0
    assert s.interpolated == []
    assert s.terminate == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools'`

- [ ] **Step 3: Implement data model**

```python
# tools/ugen_parser.py
from dataclasses import dataclass, field


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

Also create empty `tools/__init__.py` and `tests/__init__.py` so imports work.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen_parser.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add tools/__init__.py tools/ugen_parser.py tests/__init__.py tests/test_ugen_parser.py
git commit -m "feat: add Param and Signature data model for ugen parser"
```

---

### Task 2: Signature Line Parser

**Files:**
- Modify: `tools/ugen_parser.py`
- Modify: `tests/test_ugen_parser.py`

- [ ] **Step 1: Write tests for parse_signature_line**

```python
# append to tests/test_ugen_parser.py
from tools.ugen_parser import parse_signature_line


def test_parse_simple_signature():
    sig = parse_signature_line("sine(freq: ab, amp: ab): a")
    assert sig.name == "sine"
    assert sig.output_rate == "a"
    assert sig.output_chans == 0
    assert len(sig.params) == 2
    assert sig.params[0] == Param("freq", "ab")
    assert sig.params[1] == Param("amp", "ab")


def test_parse_block_rate_signature():
    sig = parse_signature_line("sineb(freq: b, amp: b): b")
    assert sig.name == "sineb"
    assert sig.output_rate == "b"
    assert sig.params[0] == Param("freq", "b")


def test_parse_fixed_channels():
    sig = parse_signature_line("overdrive(snd: 2a, gain: b, tone: b, volume: b): 2a")
    assert sig.name == "overdrive"
    assert sig.output_chans == 2
    assert sig.output_rate == "a"
    assert sig.params[0] == Param("snd", "a", chans=2)
    assert sig.params[1] == Param("gain", "b")


def test_parse_constant_params():
    sig = parse_signature_line("sttest(input: 2a, hz1: c, hz2: c): 2a")
    assert sig.name == "sttest"
    assert sig.params[1] == Param("hz1", "c")
    assert sig.params[2] == Param("hz2", "c")


def test_parse_many_block_params():
    sig = parse_signature_line(
        "noisegate(input: a, threshold: b, attack: b, hold: b, release: b): a"
    )
    assert sig.name == "noisegate"
    assert sig.output_rate == "a"
    assert len(sig.params) == 5
    assert sig.params[0] == Param("input", "a")
    assert sig.params[4] == Param("release", "b")


def test_parse_no_spaces():
    sig = parse_signature_line("sine(freq:ab,amp:ab):a")
    assert sig.name == "sine"
    assert sig.params[0] == Param("freq", "ab")
    assert sig.output_rate == "a"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen_parser.py -v -k "parse_signature"`
Expected: FAIL — `ImportError: cannot import name 'parse_signature_line'`

- [ ] **Step 3: Implement parse_signature_line**

Add to `tools/ugen_parser.py`:

```python
import re


def _parse_rate_spec(spec: str) -> tuple[str, int]:
    """Parse a rate specifier like '2a', 'ab', 'b', 'c' into (rate, chans).
    
    Returns (rate_str, fixed_chans) where fixed_chans=0 means dynamic.
    """
    spec = spec.strip()
    match = re.match(r'^(\d+)?([abc]+)$', spec)
    if not match:
        raise ValueError(f"Invalid rate specifier: {spec!r}")
    chans = int(match.group(1)) if match.group(1) else 0
    rate = match.group(2)
    return rate, chans


def parse_signature_line(line: str) -> Signature:
    """Parse a .ugen signature line into a Signature object.
    
    Example: 'sine(freq: ab, amp: ab): a' -> Signature(...)
    """
    line = line.strip()
    # Match: name(params): output
    m = re.match(r'^(\w+)\(([^)]*)\)\s*:\s*(.+)$', line)
    if not m:
        raise ValueError(f"Cannot parse signature: {line!r}")

    name = m.group(1)
    params_str = m.group(2)
    output_str = m.group(3).strip()

    # Parse output rate
    output_rate, output_chans = _parse_rate_spec(output_str)

    # Parse params
    params = []
    for param_str in params_str.split(','):
        param_str = param_str.strip()
        if not param_str:
            continue
        # Match: name: rate_spec  or  name:rate_spec
        pm = re.match(r'^(\w+)\s*:\s*(.+)$', param_str)
        if not pm:
            raise ValueError(f"Cannot parse param: {param_str!r}")
        pname = pm.group(1)
        rate, chans = _parse_rate_spec(pm.group(2))
        params.append(Param(pname, rate, chans))

    return Signature(name=name, params=params, output_rate=output_rate,
                     output_chans=output_chans)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen_parser.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add tools/ugen_parser.py tests/test_ugen_parser.py
git commit -m "feat: implement signature line parser for .ugen files"
```

---

### Task 3: `.ugen` File Parser

**Files:**
- Modify: `tools/ugen_parser.py`
- Modify: `tests/test_ugen_parser.py`
- Create: `tests/fixtures/sine.ugen`
- Create: `tests/fixtures/lowpass.ugen`
- Create: `tests/fixtures/overdrive.ugen`
- Create: `tests/fixtures/sttest.ugen`
- Create: `tests/fixtures/noisegate.ugen`

- [ ] **Step 1: Create test fixture files**

```
// tests/fixtures/sine.ugen
sine(freq: ab, amp: ab): a
sineb(freq: b, amp: b): b
FAUST
declare interpolated "freq amp";
process(freq, amp) = os.osc(freq) * amp;
```

```
// tests/fixtures/lowpass.ugen
lowpass(input: a, cutoff: ab): a
lowpassb(input: b, cutoff: b): b
FAUST
declare terminate "input";
process(input, cutoff) = fi.lowpass(1, cutoff, input);
```

```
// tests/fixtures/overdrive.ugen
overdrive(snd: 2a, gain: b, tone: b, volume: b): 2a
FAUST
declare interpolated "gain tone volume";
process(snd, gain, tone, volume) = snd * gain;
```

```
// tests/fixtures/sttest.ugen
sttest(input: 2a, hz1: c, hz2: c): 2a
FAUST
process(input, hz1, hz2) = input;
```

```
// tests/fixtures/noisegate.ugen
noisegate(input: a, threshold: b, attack: b, hold: b, release: b): a
FAUST
declare interpolated "threshold attack hold release";
process(input, threshold, attack, hold, release) = input;
```

- [ ] **Step 2: Write tests for parse_ugen_file**

```python
# append to tests/test_ugen_parser.py
from pathlib import Path
from tools.ugen_parser import parse_ugen_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_sine_ugen():
    sigs = parse_ugen_file(FIXTURES / "sine.ugen")
    assert len(sigs) == 2
    assert sigs[0].name == "sine"
    assert sigs[0].output_rate == "a"
    assert sigs[0].interpolated == ["freq", "amp"]
    assert sigs[1].name == "sineb"
    assert sigs[1].output_rate == "b"
    assert sigs[1].interpolated == ["freq", "amp"]


def test_parse_lowpass_ugen():
    sigs = parse_ugen_file(FIXTURES / "lowpass.ugen")
    assert len(sigs) == 2
    assert sigs[0].name == "lowpass"
    assert sigs[0].terminate == ["input"]
    assert sigs[1].name == "lowpassb"
    assert sigs[1].terminate == ["input"]


def test_parse_overdrive_ugen():
    sigs = parse_ugen_file(FIXTURES / "overdrive.ugen")
    assert len(sigs) == 1
    assert sigs[0].name == "overdrive"
    assert sigs[0].output_chans == 2
    assert sigs[0].params[0] == Param("snd", "a", chans=2)
    assert sigs[0].interpolated == ["gain", "tone", "volume"]


def test_parse_sttest_ugen():
    sigs = parse_ugen_file(FIXTURES / "sttest.ugen")
    assert len(sigs) == 1
    assert sigs[0].params[1] == Param("hz1", "c")
    assert sigs[0].interpolated == []


def test_parse_noisegate_ugen():
    sigs = parse_ugen_file(FIXTURES / "noisegate.ugen")
    assert len(sigs) == 1
    assert sigs[0].name == "noisegate"
    assert len(sigs[0].params) == 5
    assert sigs[0].interpolated == ["threshold", "attack", "hold", "release"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen_parser.py -v -k "parse_.*_ugen"`
Expected: FAIL — `ImportError: cannot import name 'parse_ugen_file'`

- [ ] **Step 4: Implement parse_ugen_file**

Add to `tools/ugen_parser.py`:

```python
from pathlib import Path


def parse_ugen_file(path: Path) -> list[Signature]:
    """Parse a .ugen file and return a list of Signature objects.
    
    Extracts all signature lines (before FAUST keyword) and
    declare directives (after FAUST keyword).
    """
    text = path.read_text()
    lines = text.splitlines()

    # Split at FAUST keyword
    sig_lines = []
    declare_lines = []
    in_faust = False
    for line in lines:
        stripped = line.strip()
        if stripped == "FAUST":
            in_faust = True
            continue
        if in_faust:
            declare_lines.append(stripped)
        else:
            if stripped and not stripped.startswith("//"):
                sig_lines.append(stripped)

    # Parse declare directives
    interpolated = []
    terminate = []
    for line in declare_lines:
        m = re.match(r'^declare\s+interpolated\s+"([^"]+)"', line)
        if m:
            interpolated = m.group(1).split()
        m = re.match(r'^declare\s+terminate\s+"([^"]+)"', line)
        if m:
            terminate = m.group(1).split()

    # Parse each signature line
    signatures = []
    for line in sig_lines:
        sig = parse_signature_line(line)
        sig.interpolated = list(interpolated)
        sig.terminate = list(terminate)
        signatures.append(sig)

    return signatures
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen_parser.py -v`
Expected: All passed

- [ ] **Step 6: Commit**

```bash
git add tools/ugen_parser.py tests/test_ugen_parser.py tests/fixtures/
git commit -m "feat: implement .ugen file parser with declare extraction"
```

---

### Task 4: Code Generation — Simple Audio-Rate Classes

**Files:**
- Create: `tools/ugen_codegen.py`
- Create: `tests/test_ugen_codegen.py`

- [ ] **Step 1: Write test for generating a simple audio-rate class**

```python
# tests/test_ugen_codegen.py
from tools.ugen_parser import Param, Signature
from tools.ugen_codegen import generate_class


def test_generate_sine():
    sig = Signature(
        name="sine",
        params=[Param("freq", "ab"), Param("amp", "ab")],
        output_rate="a",
    )
    code = generate_class(sig)
    assert "class Sine(Ugen):" in code
    assert "def __init__(self, freq, amp, chans=None):" in code
    assert 'chans = max_chans(max_chans(1, freq), amp)' in code
    assert 'super().__init__("Sine", chans, A_RATE, "UU", None, None,' in code
    assert "'freq', freq," in code
    assert "'amp', amp)" in code
    # No rate validation for ab params
    assert "ERROR" not in code
    assert "isinstance" not in code
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen_codegen.py::test_generate_sine -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement generate_class for simple case**

```python
# tools/ugen_codegen.py
from tools.ugen_parser import Param, Signature


def _type_char(param: Param) -> str:
    """Map a param's rate to its O2 type string character."""
    if param.rate == "c":
        return "f"
    return "U"  # a, b, ab all become U


def _rate_constant(output_rate: str) -> str:
    """Map output rate to Python constant name."""
    return "A_RATE" if output_rate == "a" else "B_RATE"


def _class_name(sig_name: str) -> str:
    """Convert ugen name to Python class name: 'sine' -> 'Sine', 'sineb' -> 'Sineb'."""
    return sig_name[0].upper() + sig_name[1:]


def _needs_rate_check(param: Param, output_rate: str) -> bool:
    """Return True if this param needs a rate validation check.
    
    Only single fixed rates (a or b) get checks, not ab or c.
    """
    return param.rate in ("a", "b") and len(param.rate) == 1 and param.rate != "c"


def _build_rate_checks(sig: Signature) -> list[str]:
    """Build rate validation lines for params that need them."""
    lines = []
    for p in sig.params:
        if _type_char(p) != "U":
            continue
        if not _needs_rate_check(p, sig.output_rate):
            continue
        rate_const = "A_RATE" if p.rate == "a" else "B_RATE"
        rate_word = "audio" if p.rate == "a" else "block"
        lines.append(
            f"        if not isinstance({p.name}, (int, float)) and {p.name}.rate != {rate_const}:\n"
            f"            print(\"ERROR: '{p.name}' input to Ugen '{sig.name}' must be {rate_word} rate\")\n"
            f"            return"
        )
    return lines


def _build_chans_computation(sig: Signature) -> list[str]:
    """Build channel auto-detection lines."""
    if sig.output_chans > 0:
        # Fixed output channels — no chans parameter, no computation
        return []

    # Collect U-type params with dynamic channels
    u_params = [p for p in sig.params if _type_char(p) == "U" and p.chans == 0]

    if not u_params:
        return ["        if chans is None:\n            chans = 1"]

    # Build nested max_chans: max_chans(max_chans(1, p1), p2)
    expr = "1"
    for p in u_params:
        expr = f"max_chans({expr}, {p.name})"
    return [f"        if chans is None:\n            chans = {expr}"]


def _build_super_call(sig: Signature) -> str:
    """Build the super().__init__() call."""
    cls = _class_name(sig.name)
    rate = _rate_constant(sig.output_rate)
    types = "".join(_type_char(p) for p in sig.params)

    if sig.output_chans > 0:
        chans_val = str(sig.output_chans)
    else:
        chans_val = "chans"

    param_pairs = []
    for p in sig.params:
        param_pairs.append(f"'{p.name}', {p.name}")

    pairs_str = ",\n                         ".join(param_pairs)

    return (
        f'        super().__init__("{cls}", {chans_val}, {rate}, "{types}", None, None,\n'
        f"                         {pairs_str})"
    )


def generate_class(sig: Signature) -> str:
    """Generate a complete Python class definition for a Signature."""
    cls = _class_name(sig.name)

    # Build __init__ parameter list
    param_names = [p.name for p in sig.params]
    if sig.output_chans == 0:
        param_names.append("chans=None")
    init_params = ", ".join(param_names)

    # Build body parts
    rate_checks = _build_rate_checks(sig)
    chans_comp = _build_chans_computation(sig)
    super_call = _build_super_call(sig)

    # Assemble
    body_parts = []
    if rate_checks:
        body_parts.extend(rate_checks)
    if chans_comp:
        body_parts.extend(chans_comp)
    body_parts.append(super_call)

    body = "\n".join(body_parts)

    return (
        f"class {cls}(Ugen):\n"
        f"\n"
        f"    def __init__(self, {init_params}):\n"
        f"{body}\n"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen_codegen.py::test_generate_sine -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/ugen_codegen.py tests/test_ugen_codegen.py
git commit -m "feat: implement code generator for simple audio-rate ugen classes"
```

---

### Task 5: Code Generation — Block-Rate with Validation

**Files:**
- Modify: `tests/test_ugen_codegen.py`

- [ ] **Step 1: Write test for block-rate class with rate validation**

```python
# append to tests/test_ugen_codegen.py

def test_generate_sineb():
    sig = Signature(
        name="sineb",
        params=[Param("freq", "b"), Param("amp", "b")],
        output_rate="b",
    )
    code = generate_class(sig)
    assert "class Sineb(Ugen):" in code
    assert "B_RATE" in code
    assert "if not isinstance(freq, (int, float)) and freq.rate != B_RATE:" in code
    assert "if not isinstance(amp, (int, float)) and amp.rate != B_RATE:" in code
    assert "ERROR: 'freq' input to Ugen 'sineb' must be block rate" in code


def test_generate_lowpass_audio_rate_check():
    sig = Signature(
        name="lowpass",
        params=[Param("input", "a"), Param("cutoff", "ab")],
        output_rate="a",
    )
    code = generate_class(sig)
    assert "class Lowpass(Ugen):" in code
    # input: a gets checked
    assert "if not isinstance(input, (int, float)) and input.rate != A_RATE:" in code
    # cutoff: ab does NOT get checked
    assert "cutoff.rate" not in code
```

- [ ] **Step 2: Run tests to verify they pass**

These should already pass with the Task 4 implementation since `_build_rate_checks` handles both cases.

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen_codegen.py -v`
Expected: All passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_ugen_codegen.py
git commit -m "test: add block-rate and mixed-rate validation tests"
```

---

### Task 6: Code Generation — Fixed Channels and Constant Params

**Files:**
- Modify: `tests/test_ugen_codegen.py`

- [ ] **Step 1: Write tests for fixed channels and constant params**

```python
# append to tests/test_ugen_codegen.py

def test_generate_fixed_channels():
    sig = Signature(
        name="overdrive",
        params=[
            Param("snd", "a", chans=2),
            Param("gain", "b"),
            Param("tone", "b"),
            Param("volume", "b"),
        ],
        output_rate="a",
        output_chans=2,
    )
    code = generate_class(sig)
    assert "class Overdrive(Ugen):" in code
    # No chans parameter in __init__
    assert "chans=None" not in code
    assert "def __init__(self, snd, gain, tone, volume):" in code
    # Fixed chans in super call
    assert '"Overdrive", 2, A_RATE' in code
    # No max_chans computation
    assert "max_chans" not in code


def test_generate_constant_params():
    sig = Signature(
        name="sttest",
        params=[
            Param("input", "a", chans=2),
            Param("hz1", "c"),
            Param("hz2", "c"),
        ],
        output_rate="a",
        output_chans=2,
    )
    code = generate_class(sig)
    assert "class Sttest(Ugen):" in code
    # Constant params map to "f" in types string
    assert '"Uff"' in code
    # No rate check on constant params
    assert "hz1.rate" not in code
    assert "hz2.rate" not in code


def test_generate_noisegate_all_block_controls():
    sig = Signature(
        name="noisegate",
        params=[
            Param("input", "a"),
            Param("threshold", "b"),
            Param("attack", "b"),
            Param("hold", "b"),
            Param("release", "b"),
        ],
        output_rate="a",
    )
    code = generate_class(sig)
    assert "class Noisegate(Ugen):" in code
    assert '"UUUUU"' in code
    # input: a gets audio rate check
    assert "input.rate != A_RATE" in code
    # block-rate params get block rate checks
    assert "threshold.rate != B_RATE" in code
    assert "attack.rate != B_RATE" in code
    assert "hold.rate != B_RATE" in code
    assert "release.rate != B_RATE" in code
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen_codegen.py -v`
Expected: All passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_ugen_codegen.py
git commit -m "test: add fixed-channel and constant-param code generation tests"
```

---

### Task 7: Output File Assembly

**Files:**
- Modify: `tools/ugen_codegen.py`
- Modify: `tests/test_ugen_codegen.py`

- [ ] **Step 1: Write test for generate_file**

```python
# append to tests/test_ugen_codegen.py
from tools.ugen_codegen import generate_file


def test_generate_file():
    sigs = [
        Signature(
            name="sineb",
            params=[Param("freq", "b"), Param("amp", "b")],
            output_rate="b",
        ),
        Signature(
            name="sine",
            params=[Param("freq", "ab"), Param("amp", "ab")],
            output_rate="a",
        ),
    ]
    code = generate_file(sigs, ["sine.ugen"])
    lines = code.splitlines()
    # Header comment
    assert lines[0] == "# AUTO-GENERATED by ugen2py.py — do not edit"
    # Import line
    assert "from arco import" in code
    # Classes sorted alphabetically
    sine_pos = code.index("class Sine(")
    sineb_pos = code.index("class Sineb(")
    assert sine_pos < sineb_pos
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen_codegen.py::test_generate_file -v`
Expected: FAIL — `ImportError: cannot import name 'generate_file'`

- [ ] **Step 3: Implement generate_file**

Add to `tools/ugen_codegen.py`:

```python
from datetime import datetime


def generate_file(signatures: list[Signature], source_files: list[str]) -> str:
    """Generate the complete arco_generated.py file content."""
    # Sort signatures alphabetically by class name
    sorted_sigs = sorted(signatures, key=lambda s: _class_name(s.name))

    # Generate each class
    classes = [generate_class(sig) for sig in sorted_sigs]

    # Build header
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    sources = ", ".join(source_files)
    header = (
        f"# AUTO-GENERATED by ugen2py.py — do not edit\n"
        f"# Generated: {timestamp}\n"
        f"# Sources: {sources}\n"
        f"\n"
        f"from arco import Ugen, Const, max_chans, A_RATE, B_RATE, C_RATE, o2lite\n"
    )

    return header + "\n\n" + "\n\n".join(classes)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen_codegen.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add tools/ugen_codegen.py tests/test_ugen_codegen.py
git commit -m "feat: implement output file assembly with sorted classes"
```

---

### Task 8: CLI Entry Point

**Files:**
- Create: `tools/ugen2py.py`
- Modify: `tests/test_ugen_codegen.py` (integration test)

- [ ] **Step 1: Write integration test**

```python
# tests/test_ugen2py_integration.py
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
PROJECT_ROOT = Path(__file__).parent.parent


def test_cli_generates_output(tmp_path):
    output = tmp_path / "arco_generated.py"
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "ugen2py.py"),
         str(FIXTURES), "-o", str(output)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert output.exists()

    content = output.read_text()
    assert "# AUTO-GENERATED" in content
    assert "class Sine(Ugen):" in content
    assert "class Sineb(Ugen):" in content
    assert "class Lowpass(Ugen):" in content
    assert "class Overdrive(Ugen):" in content
    assert "class Sttest(Ugen):" in content
    assert "class Noisegate(Ugen):" in content


def test_cli_prints_summary(tmp_path):
    output = tmp_path / "arco_generated.py"
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "ugen2py.py"),
         str(FIXTURES), "-o", str(output)],
        capture_output=True, text=True,
    )
    assert "Generated" in result.stdout
    assert "classes" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen2py_integration.py -v`
Expected: FAIL — file not found or non-zero exit

- [ ] **Step 3: Implement CLI entry point**

```python
#!/usr/bin/env python3
# tools/ugen2py.py
"""Generate Python ugen wrapper classes from Arco .ugen DSL files."""

import argparse
import sys
from pathlib import Path

# Add project root to path so tools package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.ugen_parser import parse_ugen_file
from tools.ugen_codegen import generate_file


def main():
    parser = argparse.ArgumentParser(
        description="Generate Python ugen wrappers from .ugen files")
    parser.add_argument("ugens_dir",
                        help="Path to directory containing .ugen files")
    parser.add_argument("-o", "--output",
                        default="python25/arco_generated.py",
                        help="Output file path (default: python25/arco_generated.py)")
    args = parser.parse_args()

    ugens_dir = Path(args.ugens_dir)
    if not ugens_dir.is_dir():
        print(f"Error: {ugens_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Find all .ugen files (search subdirectories too)
    ugen_files = sorted(ugens_dir.rglob("*.ugen"))
    if not ugen_files:
        print(f"No .ugen files found in {ugens_dir}", file=sys.stderr)
        sys.exit(1)

    # Parse all files
    all_signatures = []
    source_names = []
    for ugen_file in ugen_files:
        try:
            sigs = parse_ugen_file(ugen_file)
            all_signatures.extend(sigs)
            source_names.append(ugen_file.name)
        except Exception as e:
            print(f"Warning: skipping {ugen_file.name}: {e}", file=sys.stderr)

    if not all_signatures:
        print("No valid signatures found", file=sys.stderr)
        sys.exit(1)

    # Generate output
    output_content = generate_file(all_signatures, source_names)

    # Write
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_content)

    print(f"Generated {len(all_signatures)} classes from {len(source_names)} "
          f"files -> {output_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen2py_integration.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add tools/ugen2py.py tests/test_ugen2py_integration.py
git commit -m "feat: implement CLI entry point for ugen2py generator"
```

---

### Task 9: Integration with arco.py

**Files:**
- Modify: `python25/arco.py` (add import at bottom, line ~1858)

- [ ] **Step 1: Write test verifying the import hook works**

```python
# append to tests/test_ugen2py_integration.py

def test_arco_import_hook_exists():
    """Verify arco.py has the generated import at the bottom."""
    arco_path = PROJECT_ROOT / "python25" / "arco.py"
    content = arco_path.read_text()
    assert "from arco_generated import *" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen2py_integration.py::test_arco_import_hook_exists -v`
Expected: FAIL — the import line doesn't exist yet

- [ ] **Step 3: Add import hook to arco.py**

Append to the end of `python25/arco.py` (after the `Zerob` class at line ~1858):

```python

# Import auto-generated ugen wrappers (overrides hand-written versions if present)
try:
    from arco_generated import *
except ImportError:
    pass  # generated wrappers not yet built
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_ugen2py_integration.py::test_arco_import_hook_exists -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python25/arco.py
git commit -m "feat: add arco_generated import hook to arco.py"
```

---

### Task 10: Validation Against Hand-Written Wrappers

**Files:**
- Create: `tests/test_validation.py`

- [ ] **Step 1: Write validation tests comparing generated vs hand-written output**

These tests verify the generator produces output functionally equivalent to the hand-written wrappers already in `arco.py`.

```python
# tests/test_validation.py
"""Validate generated classes match hand-written equivalents in arco.py."""
from tools.ugen_parser import Param, Signature
from tools.ugen_codegen import generate_class


def _normalize(code: str) -> str:
    """Strip whitespace for comparison."""
    return " ".join(code.split())


def test_sine_matches_handwritten():
    sig = Signature(
        name="sine",
        params=[Param("freq", "ab"), Param("amp", "ab")],
        output_rate="a",
    )
    code = generate_class(sig)
    # Must contain the same types string and param order
    assert '"UU"' in code
    assert "'freq', freq" in code
    assert "'amp', amp" in code
    assert "A_RATE" in code
    # No rate checks for ab params
    assert "isinstance" not in code


def test_sineb_matches_handwritten():
    sig = Signature(
        name="sineb",
        params=[Param("freq", "b"), Param("amp", "b")],
        output_rate="b",
    )
    code = generate_class(sig)
    assert '"UU"' in code
    assert "B_RATE" in code
    # Both params get rate checks
    assert "freq.rate != B_RATE" in code
    assert "amp.rate != B_RATE" in code


def test_lowpass_matches_handwritten():
    """lowpass(input: a, cutoff: ab): a — input gets A_RATE check, cutoff doesn't."""
    sig = Signature(
        name="lowpass",
        params=[Param("input", "a"), Param("cutoff", "ab")],
        output_rate="a",
    )
    code = generate_class(sig)
    assert '"UU"' in code
    assert "input.rate != A_RATE" in code
    assert "cutoff.rate" not in code


def test_reson_matches_handwritten():
    """reson(input: a, center: ab, q: ab): a"""
    sig = Signature(
        name="reson",
        params=[Param("input", "a"), Param("center", "ab"), Param("q", "ab")],
        output_rate="a",
    )
    code = generate_class(sig)
    assert '"UUU"' in code
    assert "input.rate != A_RATE" in code
    assert "center.rate" not in code
    assert "q.rate" not in code
    assert "max_chans(max_chans(max_chans(1, input), center), q)" in code


def test_resonb_matches_handwritten():
    """resonb(input: b, center: b, q: b): b — all three get B_RATE checks."""
    sig = Signature(
        name="resonb",
        params=[Param("input", "b"), Param("center", "b"), Param("q", "b")],
        output_rate="b",
    )
    code = generate_class(sig)
    assert '"UUU"' in code
    assert "input.rate != B_RATE" in code
    assert "center.rate != B_RATE" in code
    assert "q.rate != B_RATE" in code
```

- [ ] **Step 2: Run tests**

Run: `cd D:/projects/PyArco && python -m pytest tests/test_validation.py -v`
Expected: All passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_validation.py
git commit -m "test: add validation tests comparing generated vs hand-written wrappers"
```

---

### Task 11: Final Cleanup

**Files:**
- Modify: `.gitignore` (if it exists, add `python25/arco_generated.py`)

- [ ] **Step 1: Run full test suite**

Run: `cd D:/projects/PyArco && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Run the generator on test fixtures and inspect output**

Run: `cd D:/projects/PyArco && python tools/ugen2py.py tests/fixtures/ -o python25/arco_generated.py`
Expected: "Generated N classes from 5 files -> python25/arco_generated.py"

Inspect: `cat python25/arco_generated.py` — verify output looks correct, classes are sorted, imports are present.

- [ ] **Step 3: Add arco_generated.py to .gitignore**

```
# Generated files
python25/arco_generated.py
```

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: add arco_generated.py to .gitignore"
```
