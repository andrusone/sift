from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .model import SiftConfig, TierDef


# ----------------------------
# Helpers
# ----------------------------


def _as_str(v: Any) -> Optional[str]:
    return v if isinstance(v, str) else None


def _as_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except Exception:
        return None


def _get(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


# ----------------------------
# Media type routing
# ----------------------------


def infer_media_type(cfg: SiftConfig, item: Dict[str, Any]) -> str:
    """
    Return "movies" or "tv" based on cfg.classification.media_type_strategy.
    """
    strat = (cfg.classification.media_type_strategy or "").lower()
    rel = item.get("relpath")
    if not isinstance(rel, str) or not rel:
        return "movies"

    if strat == "folder":
        parts = Path(rel).parts
        if parts:
            head = parts[0].lower()
            if head in {"tv", "shows", "series"}:
                return "tv"
            if head in {"movie", "movies", "film", "films"}:
                return "movies"
        return "movies"

    if strat == "sxe":
        name = Path(rel).name
        if re.search(cfg.classification.tv_sxe_regex, name):
            return "tv"

        if cfg.classification.enable_season_episode_words:
            if re.search(cfg.classification.tv_season_episode_regex, name):
                return "tv"

        return "movies"

    # "guess" reserved — default to movies
    return "movies"


# ----------------------------
# Derived facts (match your config.toml)
# ----------------------------


def _res_label_from_height(h: Optional[int]) -> str:
    """
    Map height -> your res buckets: 2160p / 1080p / 720p / SD
    """
    if h is None:
        return "SD"
    if h >= 2000:
        return "2160p"
    if h >= 1000:
        return "1080p"
    if h >= 700:
        return "720p"
    return "SD"


def _is_hdr(cfg: SiftConfig, item: Dict[str, Any]) -> bool:
    """
    Best-effort HDR detection using:
    - video.color_transfer in hdr_color_transfer
    - side_data_types + tags/profile matched against hdr_side_data_regex
    """
    ff = item.get("ffprobe")
    if not isinstance(ff, dict) or ff.get("ok") is not True:
        return False

    transfer = _as_str(_get(ff, "video.color_transfer"))
    if transfer and transfer.lower() in {
        x.lower() for x in cfg.classification.hdr_color_transfer
    }:
        return True

    # Build a searchable blob from likely HDR/DV hints
    parts: list[str] = []

    vprof = _as_str(_get(ff, "video.profile"))
    if vprof:
        parts.append(vprof)

    # side_data_types from summarize()
    sdt = _get(ff, "video.side_data_types")
    if isinstance(sdt, list):
        parts.extend([str(x) for x in sdt])

    # tags from summarize()
    tags = _get(ff, "video.tags")
    if isinstance(tags, dict):
        parts.extend([f"{k}={v}" for k, v in tags.items()])

    blob = " | ".join(parts).lower()

    for pat in cfg.classification.hdr_side_data_regex:
        try:
            if re.search(pat, blob, flags=0):
                return True
        except re.error:
            # Bad regex in config should not crash routing; treat as non-match
            continue

    return False


def _is_problem_audio(cfg: SiftConfig, item: Dict[str, Any]) -> bool:
    """
    Your config intent:
    - problem_audio_codecs includes truehd, etc.
    - problem_audio_profile_regex matches DTS-HD MA, etc.
    We check codec + profile strings.
    """
    ff = item.get("ffprobe")
    if not isinstance(ff, dict) or ff.get("ok") is not True:
        return False

    acodec = _as_str(_get(ff, "audio.codec"))
    aprof = _as_str(_get(ff, "audio.profile"))

    if acodec and acodec.lower() in {
        x.lower() for x in cfg.classification.problem_audio_codecs
    }:
        return True

    blob = " ".join([x for x in [acodec, aprof] if isinstance(x, str)]).lower()

    for pat in cfg.classification.problem_audio_profile_regex:
        try:
            if re.search(pat, blob, flags=0):
                return True
        except re.error:
            continue

    return False


def derive_facts(cfg: SiftConfig, item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Produce the exact fact keys your tier rules reference:
      res, hdr, vcodec, acodec, min_audio_channels, problem_audio
    """
    ff = item.get("ffprobe")
    if not isinstance(ff, dict) or ff.get("ok") is not True:
        # If we can't probe, keep facts minimal; tiers should fall through.
        return {
            "res": "SD",
            "hdr": False,
            "vcodec": None,
            "acodec": None,
            "min_audio_channels": 0,
            "problem_audio": False,
        }

    height = _as_int(_get(ff, "video.height"))
    facts = {
        "res": _res_label_from_height(height),
        "hdr": _is_hdr(cfg, item),
        "vcodec": _as_str(_get(ff, "video.codec")),
        "acodec": _as_str(_get(ff, "audio.codec")),
        "min_audio_channels": _as_int(_get(ff, "audio.channels")) or 0,
        "problem_audio": _is_problem_audio(cfg, item),
    }
    return facts


# ----------------------------
# Tier matching (matches your requires tables)
# ----------------------------


def _match_value(actual: Any, rule: Any) -> bool:
    """
    Minimal matching for your current config:

    - str/bool/int: equality (case-insensitive for strings)
    - list: membership (case-insensitive for strings)
    - dict (optional): supports {"min": N} / {"max": N}, {"regex": "..."}, {"eq": X}
    """
    if isinstance(rule, dict):
        if "eq" in rule:
            return _match_value(actual, rule["eq"])
        if "min" in rule or "max" in rule:
            a = _as_int(actual)
            if a is None:
                return False
            if "min" in rule and a < int(rule["min"]):
                return False
            if "max" in rule and a > int(rule["max"]):
                return False
            return True
        if "regex" in rule:
            pat = rule.get("regex")
            s = _as_str(actual)
            if not isinstance(pat, str) or s is None:
                return False
            try:
                return re.search(pat, s) is not None
            except re.error:
                return False
        return False

    if isinstance(rule, list):
        if actual is None:
            return False
        if isinstance(actual, str):
            a = actual.lower()
            return any(isinstance(x, str) and x.lower() == a for x in rule)
        return actual in rule

    if isinstance(rule, str):
        return isinstance(actual, str) and actual.lower() == rule.lower()

    return actual == rule


def tier_for_item(cfg: SiftConfig, item: Dict[str, Any]) -> TierDef:
    """
    Select the first matching tier in config order, using derived facts that match config.toml.

    Rules:
    - Match is evaluated against derive_facts(cfg, item)
    - T5 is NOT a fallback bucket. It only matches when its requires evaluate true.
    - If nothing matches, fall back to T4 if present, else the last tier.
    """
    facts = derive_facts(cfg, item)

    # Evaluate tiers in order
    for t in cfg.tier_model.tier:
        req = t.requires
        if req is None:
            req = {}
        if not isinstance(req, dict):
            # bad config shouldn't silently route to T5; treat as non-match
            continue

        # Empty requires => unconditional match (if you ever add a catch-all tier)
        if len(req) == 0:
            return t

        ok = True
        for key, rule in req.items():
            actual = facts.get(key)
            if not _match_value(actual, rule):
                ok = False
                break

        if ok:
            return t

    # Fallback: prefer T4 if present, otherwise last tier
    for t in cfg.tier_model.tier:
        if (t.id or "").upper() == "T4":
            return t

    return cfg.tier_model.tier[-1]


# ----------------------------
# Final route
# ----------------------------


def route_destination(
    cfg: SiftConfig, item: Dict[str, Any]
) -> Tuple[str, TierDef, Path, Dict[str, Any]]:
    """
    Returns (media_type, tier, rel_dest_path, facts)
    rel_dest_path preserves incoming-relative path (deterministic, fewer collisions).
    """
    rel = item.get("relpath")
    if not isinstance(rel, str) or not rel:
        raise ValueError("inventory item missing relpath")

    media_type = infer_media_type(cfg, item)
    tier = tier_for_item(cfg, item)
    facts = derive_facts(cfg, item)

    return media_type, tier, Path(rel), facts
