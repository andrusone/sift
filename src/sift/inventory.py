from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import cache as cache_mod
from .ffprobe import run_ffprobe, summarize
from .model import SiftConfig
from .scan import scan_files


def build_inventory(
    cfg: SiftConfig,
    *,
    rescan: bool,
    only_ext: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    if not rescan:
        try:
            return cache_mod.read_cache(cfg)
        except FileNotFoundError:
            pass

    media_paths = scan_files(cfg.paths.incoming, only_ext=only_ext, limit=limit)

    items: List[Dict[str, Any]] = []
    errors = 0

    for p in media_paths:
        rel = str(p.relative_to(cfg.paths.incoming))
        try:
            st = p.stat()
        except OSError:
            continue

        item: Dict[str, Any] = {
            "relpath": rel,
            "path": str(p),
            "size": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
        }

        ffj, err = run_ffprobe(cfg.ffprobe, p)
        if err or ffj is None:
            errors += 1
            item["ffprobe"] = {"ok": False, "error": err}
        else:
            item["ffprobe"] = summarize(ffj)

        # Compute the proposed name (rendered using naming templates) if possible.
        try:
            from .router import render_name

            item["proposed_name"] = render_name(cfg, item)
        except Exception:
            # Don't fail the scan if rendering/routing fails; proposed_name will simply be absent.
            pass

        items.append(item)

    items.sort(key=lambda x: x.get("relpath", ""))
    cache_mod.write_cache(cfg, items=items, errors=errors)

    # Re-read to ensure we return exactly what was cached (contract).
    return cache_mod.read_cache(cfg)
