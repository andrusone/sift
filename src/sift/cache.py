from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .errors import CacheError
from .model import SiftConfig
from .utils import utc_now_iso

CACHE_VERSION = 2
DEFAULT_SCAN_CACHE_NAME = "scan.json"


def cache_path(cfg: SiftConfig) -> Path:
    return cfg.paths.metadata_cache / DEFAULT_SCAN_CACHE_NAME


def write_cache(cfg: SiftConfig, *, items: List[Dict[str, Any]], errors: int) -> Path:
    cp = cache_path(cfg)
    payload = {
        "schema_version": CACHE_VERSION,
        "generated_at_utc": utc_now_iso(),
        "incoming_root": str(cfg.paths.incoming),
        "count": len(items),
        "errors": int(errors),
        "items": items,
    }
    tmp = cp.with_suffix(cp.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp.replace(cp)
    return cp


def read_cache(cfg: SiftConfig) -> Dict[str, Any]:
    cp = cache_path(cfg)
    try:
        raw = cp.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise FileNotFoundError(str(cp)) from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CacheError(f"Cache file is not valid JSON: {cp}: {e}") from e

    if not isinstance(data, dict):
        raise CacheError(f"Cache file must be a JSON object: {cp}")

    if int(data.get("schema_version", -1)) != CACHE_VERSION:
        raise CacheError(
            f"Cache schema mismatch in {cp}: found {data.get('schema_version')}, expected {CACHE_VERSION}"
        )

    inc = data.get("incoming_root")
    if inc and str(inc) != str(cfg.paths.incoming):
        raise CacheError(
            "Cache was generated for a different incoming_root. Use --rescan to rebuild.\n"
            f"  cache incoming_root : {inc}\n"
            f"  config incoming_root: {cfg.paths.incoming}"
        )

    return data
