# PyArco — Claude Code Instructions

## Project

Python control-side bindings for [Arco](https://github.com/rbdannenberg/arco),
a real-time audio synthesis and analysis engine by Roger Dannenberg (CMU).

Read `PyArcoCONTEXT.md` for full project context: architecture, existing code,
what's been built, and what's next.

## Key Files

- `python25/arco_engine.py` — ArcoEngine (O2 connection, weak-ref ugen
  registry, UgenID pool, action system), constants, conversion utilities
- `python25/arco_ugens.py` — Ugen base class and ~55 ugen wrapper classes
- `python25/arco.py` — thin re-export of arco_engine + arco_ugens
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
The existing hand-crafted wrappers in `arco_ugens.py` are the reference
templates.
The `.ugen` files are the authoritative source, not the Serpent wrappers.

## Conventions

- Ugen `__init__` uses a `types_` string convention: `"U"` = ugen input
  (auto-wraps numbers in Const), `"i"/"f"/"s"/"d"/"B"` = literal values.
  Inputs passed as alternating `(name, value)` pairs after the type string.
- UgenID pool: 1000 slots, user IDs start at 100. System IDs 0–3 are reserved
  (Zero, Zerob, Input, Output) and owned by the *server*.
- `ArcoEngine.connect()` attaches non-destructively: no `/arco/reset`, and
  the server's output ugen (ID 3) is never freed/replaced. The play/mute
  `Sum` lives at a pool id, spliced in via `/arco/thru/repl_input` (one
  atomic message → no server warnings). Server audio must be started
  before connecting; `engine.output.id` is a pool id, not `OUTPUT_ID`.
- O2 messages: `/arco/<classname_lowercase>/<method>` with typed params.
- `__del__` sends `/arco/free` and returns the ID to the pool — but only
  for pool-allocated ids (`owns_id`), and only when the server hasn't
  already freed it (`_server_freed`). The engine registry is weak; keep a
  Python reference (or `play()` the ugen) to keep it alive.
- Tests: `.venv/bin/python -m pytest python25/tests tests -v` (offline, no
  Arco server needed — FakeO2Lite records messages; the root `tests/` suite
  covers the ugen2py code generator).
- Demo site: `.venv/bin/python python25/init.py`, then open
  http://localhost:8080 (`ARCO_DEMO_PORT` overrides the port). Starts
  without an Arco server. o2litepy location: `$O2LITEPY_PATH` or a sibling
  `../o2` checkout (see README.md). The demo polls O2 via a NiceGUI
  `app.timer` — o2lite clients that stop polling get dropped by the server.
  The page layout MUST stay behind `@ui.page('/')`: NiceGUI 3 "script
  mode" (no page decorator) re-executes the whole module per browser
  client — each tab then gets its own engine and they corrupt each
  other's server ugens.
- Live audio: run `arcobasic` from its own directory and press `S` in its
  terminal UI to start audio before connecting (see README.md "Validating
  against a live Arco server", including known harmless warnings).
- Many ugens have audio/block rate pairs (e.g. `Sine`/`Sineb`, `Math`/`Mathb`).
  Block-rate variants enforce rate checks at construction.

## Style

- Concise, direct. Lead with the answer.
- Prose over bullet points unless structure helps.
- Clear recommendations with reasoning when giving options.
