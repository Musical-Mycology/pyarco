# PyArco

Python control-side bindings for [Arco](https://github.com/rbdannenberg/arco),
a real-time audio synthesis and analysis engine by Roger Dannenberg (CMU).
PyArco connects to a running Arco server over [O2](https://github.com/rbdannenberg/o2)
using `o2litepy`, a pure-Python O2lite implementation — no C/C++ compilation
required on the Python side.

## Repository layout

| Path | Purpose |
|---|---|
| `python25/arco_engine.py` | `ArcoEngine`: O2 connection, ugen registry, ID pool, actions |
| `python25/arco_ugens.py` | `Ugen` base class and ~55 hand-written ugen wrappers |
| `python25/arco.py` | Re-export layer (`from arco import Sine`, …) |
| `python25/arco_instr.py` | Instrument framework (Param, Instrument, Synth, Score) |
| `python25/init.py` | **Demo site** — NiceGUI web app for interactive testing |
| `tools/` | `ugen2py` code generator (`.ugen` files → Python wrappers) |
| `python25/tests/` | Offline test suite for the bindings (fake O2 transport) |
| `tests/` | Test suite for the `ugen2py` code generator |

## Prerequisites

- **Python 3.9+** (developed and tested on 3.9; no compiled extensions).
- **o2litepy** — not on PyPI. It lives inside a checkout of the
  [o2 repository](https://github.com/rbdannenberg/o2). Only needed for
  *live* use against an Arco server; the test suites and demo UI start
  without it. `arco_engine` looks for it in this order:
  1. anywhere already importable (`PYTHONPATH`, site-packages),
  2. the directory named by the `O2LITEPY_PATH` environment variable
     (point it at `<o2 checkout>/o2litepy/src`),
  3. a sibling checkout: `../o2/o2litepy/src` relative to this repo.
- **A running Arco server** — only for actually making sound. Build/run it
  from the [arco repository](https://github.com/rbdannenberg/arco).

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

## Running the tests

Both suites are fully offline — no Arco server or o2litepy needed:

```sh
.venv/bin/python -m pytest python25/tests tests -v
```

`python25/tests` exercises the bindings against a fake O2 transport;
`tests` covers the `ugen2py` code generator.

## Launching the demo site

```sh
.venv/bin/python python25/init.py
```

Then open http://localhost:8080 (override the port with `ARCO_DEMO_PORT`).
The UI starts without an Arco server; use its connect control to attach to
a running server for audio. To place o2litepy somewhere non-standard:

```sh
O2LITEPY_PATH=/path/to/o2/o2litepy/src .venv/bin/python python25/init.py
```

## Generating ugen wrappers

`tools/ugen2py.py` generates Python wrapper classes from Arco's `.ugen`
DSL files (the authoritative source):

```sh
.venv/bin/python tools/ugen2py.py /path/to/arco/ugens -o python25/arco_generated.py
```

The output file is gitignored; `python25/arco.py` picks it up automatically
when present.

## Further reading

`PyArcoCONTEXT.md` holds the detailed architecture and design context;
`CLAUDE.md` holds contributor conventions.
