# PyArco — Claude Code Instructions

## Project

Python control-side bindings for [Arco](https://github.com/rbdannenberg/arco),
a real-time audio synthesis and analysis engine by Roger Dannenberg (CMU).

Read `PyArcoCONTEXT.md` for full project context: architecture, existing code,
what's been built, and what's next.

## Key Files

- `python25/arco.py` — Core library: o2litepy connection, UgenID pool, Ugen
  base class, ~55 ugen wrapper classes, utilities
- `python25/arco_instr.py` — Instrument framework: Param system, Instrument,
  Synth, Note/Score, Reverb, Supersaw
- `python25/init.py` — NiceGUI demo app for interactive testing
- `PyArcoCONTEXT.md` — Detailed project context and reference

## Architecture Decisions

**Transport: o2litepy** — pure-Python O2lite implementation. No C++ compilation
or shared library loading. Connects to Arco as an O2 host. Do not use ctypes
or libo2 unless there's a measured performance need.

**Code generation from .ugen files** — the next major milestone. Arco's
`arco/preproc/u2f.py` already generates Serpent (.srp) wrappers from `.ugen`
descriptions. The plan is to write a sibling generator to emit `.py` files.
The existing hand-crafted wrappers in `arco.py` are the reference templates.
The `.ugen` files are the authoritative source, not the Serpent wrappers.

## Conventions

- Ugen `__init__` uses a `types_` string convention: `"U"` = ugen input
  (auto-wraps numbers in Const), `"i"/"f"/"s"/"d"/"B"` = literal values.
  Inputs passed as alternating `(name, value)` pairs after the type string.
- UgenID pool: 1000 slots, user IDs start at 100. System IDs 0–3 are reserved
  (Zero, Zerob, Input, Output).
- O2 messages: `/arco/<classname_lowercase>/<method>` with typed params.
- `__del__` sends `/arco/free` and returns ID to pool.
- Many ugens have audio/block rate pairs (e.g. `Sine`/`Sineb`, `Math`/`Mathb`).
  Block-rate variants enforce rate checks at construction.

## Style

- Concise, direct. Lead with the answer.
- Prose over bullet points unless structure helps.
- Clear recommendations with reasoning when giving options.
