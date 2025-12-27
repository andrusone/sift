from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import cache as cache_mod
from .ffprobe import run_ffprobe, summarize
from .model import SiftConfig
from .scan import scan_files


def _normalize_stem(stem: str) -> str:
    """Normalize filename stem for variant grouping.

    Strips common noise tokens like 'sample', 'trailer', 'extra',
    release group tags in brackets, resolution, and collapses whitespace.
    """
    # Remove bracketed/parenthesized content (release groups, tags)
    stem = re.sub(r"\[.*?\]", " ", stem)
    stem = re.sub(r"\(.*?\)", " ", stem)
    # Collapse whitespace and punctuation first
    stem = re.sub(r"[._\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem)
    # Remove common sample/extra keywords
    stem = re.sub(
        r"\b(sample|trailer|extra|bonus|featurette)\b", " ", stem, flags=re.IGNORECASE
    )
    # Remove resolution patterns (720p, 1080p, 2160p, 4k, etc.)
    stem = re.sub(r"\b\d{3,4}[pi]\b", " ", stem, flags=re.IGNORECASE)
    stem = re.sub(r"\b[248]k\b", " ", stem, flags=re.IGNORECASE)
    # Final whitespace cleanup
    stem = re.sub(r"\s+", " ", stem)
    return stem.strip().lower()


def _mark_samples(cfg: SiftConfig, items: List[Dict[str, Any]]) -> None:
    """Mark items as samples based on duration and variant logic."""
    if not cfg.sample_detection.enabled:
        return

    min_dur = cfg.sample_detection.min_duration_s
    min_video = cfg.sample_detection.min_video_streams
    prefer_longest = cfg.sample_detection.prefer_longest_variant

    # First pass: mark items with insufficient video streams or too short duration
    for item in items:
        ff = item.get("ffprobe")
        if not isinstance(ff, dict) or ff.get("ok") is not True:
            continue

        # Check minimum video streams
        stream_counts = ff.get("stream_counts", {})
        video_count = (
            stream_counts.get("video", 0) if isinstance(stream_counts, dict) else 0
        )
        if video_count < min_video:
            item["skip_reason"] = "no_video_stream"
            continue

        # Check minimum duration
        duration = ff.get("duration_s")
        if isinstance(duration, (int, float)) and duration < min_dur:
            item["skip_reason"] = "sample_too_short"
            continue

    # Second pass: if prefer_longest_variant is enabled, group by normalized stem
    # and mark shorter variants as samples
    if not prefer_longest:
        return

    # Group items by normalized stem
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        if "skip_reason" in item:
            continue
        rel = item.get("relpath")
        if not isinstance(rel, str):
            continue
        # Strip extension before normalizing
        stem = Path(rel).stem
        norm_key = _normalize_stem(stem)
        if not norm_key:
            continue
        groups.setdefault(norm_key, []).append(item)

    # For each group with multiple items, keep only the longest
    for norm_key, group_items in groups.items():
        if len(group_items) <= 1:
            continue

        # Find the longest duration
        max_duration = 0.0
        for item in group_items:
            ff = item.get("ffprobe")
            if isinstance(ff, dict):
                dur = ff.get("duration_s")
                if isinstance(dur, (int, float)) and dur > max_duration:
                    max_duration = dur

        # Mark all but the longest as samples
        for item in group_items:
            ff = item.get("ffprobe")
            if isinstance(ff, dict):
                dur = ff.get("duration_s")
                if isinstance(dur, (int, float)) and dur < max_duration:
                    item["skip_reason"] = "sample_shorter_variant"


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

    # Mark samples before caching
    _mark_samples(cfg, items)

    items.sort(key=lambda x: x.get("relpath", ""))
    cache_mod.write_cache(cfg, items=items, errors=errors)

    # Re-read to ensure we return exactly what was cached (contract).
    return cache_mod.read_cache(cfg)
