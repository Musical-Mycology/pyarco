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
