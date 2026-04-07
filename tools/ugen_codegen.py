"""Code generator: Signature -> Python class source code."""

from .ugen_parser import Param, Signature


def _type_char(param: Param) -> str:
    """Map a param's rate to its O2 type character."""
    if param.rate == "c":
        return "f"
    return "U"


def _rate_constant(output_rate: str) -> str:
    """Map output_rate to the Python rate constant name."""
    if output_rate == "a":
        return "A_RATE"
    if output_rate == "b":
        return "B_RATE"
    raise ValueError(f"Unknown output_rate: {output_rate!r}")


def _class_name(sig_name: str) -> str:
    """Convert a ugen name like 'sine' or 'sineb' to a class name like 'Sine'."""
    return sig_name.capitalize()


def _needs_rate_check(param: Param, output_rate: str) -> bool:
    """Return True if this param requires a runtime rate validation check.

    Only single-fixed rates ('a' or 'b') get a check; 'ab' (flexible) and
    'c' (constant / literal float) do not.
    """
    return param.rate in ("a", "b")


def _build_rate_checks(sig: Signature) -> list[str]:
    """Generate rate-check lines for params that require it."""
    lines = []
    rate_const = _rate_constant(sig.output_rate)
    for param in sig.params:
        if _needs_rate_check(param, sig.output_rate):
            # Determine which rate this param must be
            if param.rate == "a":
                check_const = "A_RATE"
            else:
                check_const = "B_RATE"
            lines.append(
                f"        if not isinstance({param.name}, (int, float)) "
                f"and {param.name}.rate != {check_const}:"
            )
            lines.append(
                f"            print(\"ERROR: '{param.name}' input to Ugen "
                f"'{sig.name}' must be "
                f"{'audio' if param.rate == 'a' else 'block'} rate\")"
            )
            lines.append("            return")
    return lines


def _build_chans_computation(sig: Signature) -> list[str]:
    """Build the 'if chans is None: chans = max_chans(...)' block.

    Only applies when output_chans == 0 (dynamic channels).
    Returns empty list if output_chans is fixed.
    """
    if sig.output_chans > 0:
        return []

    # Only U-type (dynamic) params contribute to channel count
    dynamic_params = [p for p in sig.params if _type_char(p) == "U"]

    # Build nested max_chans starting from 1
    expr = "1"
    for param in dynamic_params:
        expr = f"max_chans({expr}, {param.name})"

    return [
        "        if chans is None:",
        f"            chans = {expr}",
    ]


def _build_super_call(sig: Signature) -> list[str]:
    """Assemble the super().__init__() call lines."""
    class_name = _class_name(sig.name)
    rate_const = _rate_constant(sig.output_rate)

    # Fixed or dynamic channels
    if sig.output_chans > 0:
        chans_arg = str(sig.output_chans)
    else:
        chans_arg = "chans"

    # Types string
    types_str = "".join(_type_char(p) for p in sig.params)

    # Build param pairs: 'name', value
    pairs = []
    for param in sig.params:
        pairs.append(f"'{param.name}', {param.name}")

    # Compose the call
    first_line = (
        f"        super().__init__(\"{class_name}\", {chans_arg}, "
        f"{rate_const}, \"{types_str}\", None, None,"
    )

    # Add param pairs — each pair on its own continuation line
    pair_lines = []
    for i, pair in enumerate(pairs):
        is_last = (i == len(pairs) - 1)
        suffix = ")" if is_last else ","
        pair_lines.append(f"            {pair}{suffix}")

    return [first_line] + pair_lines


def generate_class(sig: Signature) -> str:
    """Generate a Python class definition string for the given Signature."""
    class_name = _class_name(sig.name)

    # --- Build __init__ signature ---
    param_names = [p.name for p in sig.params]
    if sig.output_chans > 0:
        # Fixed channels: no chans parameter
        init_params = ", ".join(["self"] + param_names)
    else:
        init_params = ", ".join(["self"] + param_names + ["chans=None"])

    lines = [
        f"class {class_name}(Ugen):",
        "",
        f"    def __init__({init_params}):",
    ]

    # Rate checks
    rate_check_lines = _build_rate_checks(sig)
    if rate_check_lines:
        lines.extend(rate_check_lines)
        lines.append("")  # blank line after checks

    # Channel computation
    chans_lines = _build_chans_computation(sig)
    lines.extend(chans_lines)

    # super().__init__() call
    super_lines = _build_super_call(sig)
    lines.extend(super_lines)

    lines.append("")  # trailing newline
    return "\n".join(lines)
