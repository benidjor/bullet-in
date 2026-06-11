from __future__ import annotations
import re
from pathlib import Path
import yaml

_HANDLE_RE = re.compile(r"@(\w+)")  # used by resolve_tier in Task 2

class Registry:
    def __init__(self, journalists: dict[str, float], outlets: dict[str, float]):
        self.journalists = journalists  # alias(lower) -> tier
        self.outlets = outlets

def _build(entries: list[dict], dest: dict[str, float]) -> None:
    for e in entries or []:
        tier = float(e["tier"])
        for alias in e["aliases"]:
            key = alias.lower()  # registry keys are always lowercased for case-insensitive lookup
            if key in dest:
                raise ValueError(f"duplicate alias: {alias}")
            dest[key] = tier

def load_registry(path) -> Registry:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    jour: dict[str, float] = {}
    out: dict[str, float] = {}
    _build(data.get("journalists", []), jour)
    _build(data.get("outlets", []), out)
    return Registry(jour, out)
