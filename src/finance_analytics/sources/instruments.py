"""Asset class of an instrument: rules on the export's category and name, plus user overrides (D-040).

`data/config/instruments.yaml` (optional, private) overrides the class of single symbols:

    instruments:
      GOLD.DE: {asset_class: precious_metals}
      COIN.DE: {asset_class: other}

Pure functions of their inputs; `sync` stores the result in `instruments.asset_class`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from finance_analytics.sources.xtb.parser import CATEGORY_TO_ASSET_CLASS

# Funds and notes whose value follows a precious metal (physically backed ETC/ETN, gold ETFs).
METAL_CATEGORIES = {"ETC", "ETN", "ETF"}
METAL_RE = re.compile(
    r"\b(gold|silver|platinum|palladium|precious|bullion|xau|xag|z[łl]ot[oa]|srebr[oa]|platyn[ay]|palladu?)\b",
    re.IGNORECASE,
)
# Mining companies follow equity markets as much as the metal: they stay ETFs/stocks.
MINERS_RE = re.compile(r"\b(miner|mining|producer|explorer|górnic|wydobyw)", re.IGNORECASE)

HEADER = """\
# Asset class overrides for single instruments. This file is private: data/ is git-ignored.
# finance-analytics guesses the class from the XTB category and the instrument name (D-040);
# list a symbol here when the guess is wrong. Classes: stock, etf, precious_metals, other.
"""


class InstrumentOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_class: Literal["stock", "etf", "precious_metals", "other"]


class InstrumentsFileError(ValueError):
    pass


def instruments_file(config_dir: Path) -> Path:
    return config_dir / "instruments.yaml"


def load_overrides(path: Path) -> dict[str, str]:
    """Symbol -> asset class from the overrides file; empty when the file does not exist."""
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = data.get("instruments") or {}
        if not isinstance(entries, dict):
            raise TypeError("`instruments` must map symbols to {asset_class: ...}")
        return {str(symbol): InstrumentOverride(**(spec or {})).asset_class for symbol, spec in entries.items()}
    except (yaml.YAMLError, ValidationError, TypeError, AttributeError) as exc:
        raise InstrumentsFileError(f"{path}: {exc}") from exc


def is_precious_metal(name: str | None, category: str | None) -> bool:
    """A fund or note named after a precious metal, and not a fund of mining companies."""
    if category not in METAL_CATEGORIES or not name:
        return False
    return bool(METAL_RE.search(name)) and not MINERS_RE.search(name)


def classify(symbol: str, name: str | None, category: str | None, overrides: dict[str, str] | None = None) -> str:
    """The asset class stored for an instrument: an override wins, then the name rule, then the category."""
    if overrides and symbol in overrides:
        return overrides[symbol]
    if is_precious_metal(name, category):
        return "precious_metals"
    return CATEGORY_TO_ASSET_CLASS.get(category or "", "other")
