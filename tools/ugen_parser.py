import re
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


def _parse_rate_spec(spec: str) -> tuple[str, int]:
    """Parse a rate specifier like '2a', 'ab', 'b', 'c' into (rate, chans)."""
    spec = spec.strip()
    match = re.match(r'^(\d+)?([abc]+)$', spec)
    if not match:
        raise ValueError(f"Invalid rate specifier: {spec!r}")
    chans = int(match.group(1)) if match.group(1) else 0
    rate = match.group(2)
    return rate, chans


def parse_signature_line(line: str) -> Signature:
    """Parse a .ugen signature line into a Signature object."""
    line = line.strip()
    m = re.match(r'^(\w+)\(([^)]*)\)\s*:\s*(.+)$', line)
    if not m:
        raise ValueError(f"Cannot parse signature: {line!r}")

    name = m.group(1)
    params_str = m.group(2)
    output_str = m.group(3).strip()

    output_rate, output_chans = _parse_rate_spec(output_str)

    params = []
    for param_str in params_str.split(','):
        param_str = param_str.strip()
        if not param_str:
            continue
        pm = re.match(r'^(\w+)\s*:\s*(.+)$', param_str)
        if not pm:
            raise ValueError(f"Cannot parse param: {param_str!r}")
        pname = pm.group(1)
        rate, chans = _parse_rate_spec(pm.group(2))
        params.append(Param(pname, rate, chans))

    return Signature(name=name, params=params, output_rate=output_rate,
                     output_chans=output_chans)
