from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def as_path(s: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(s))
    return Path(expanded).resolve()


def safe_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_ratio(v: Any) -> Optional[float]:
    # ffprobe often reports "24000/1001"
    if isinstance(v, str) and "/" in v:
        num_s, den_s = v.split("/", 1)
        num = safe_float(num_s)
        den = safe_float(den_s)
        if not num or not den or den == 0:
            return None
        return num / den
    return safe_float(v)
