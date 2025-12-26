from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .model import ClassificationConfig, SiftConfig, TierDef


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


def _res_label_from_dimensions(
    cfg: ClassificationConfig, width: Optional[int], height: Optional[int]
) -> str:
    """
    Map dimensions -> res buckets: 2160p / 1080p / 720p / SD
    For ultra-wide theatrical formats, check horizontal threshold first.
    """
    # Check horizontal resolution for 4K theatrical formats (e.g., 4096x1716)
    # Debug: uncomment to troubleshoot resolution classification
    # import sys
    # print(f"DEBUG: width={width}, height={height}, threshold={cfg.horizontal_4k_threshold}", file=sys.stderr)

    if width and width >= cfg.horizontal_4k_threshold:
        return "2160p"

    # Otherwise use vertical resolution
    if height is None:
        return "SD"
    if height >= cfg.vertical_thresholds.get("2160p", 2000):
        return "2160p"
    if height >= cfg.vertical_thresholds.get("1080p", 1000):
        return "1080p"
    if height >= cfg.vertical_thresholds.get("720p", 700):
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

    width = _as_int(_get(ff, "video.width"))
    height = _as_int(_get(ff, "video.height"))
    facts = {
        "res": _res_label_from_dimensions(cfg.classification, width, height),
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


def _parse_sxe_from_name(name: str):
    """Return (show, season2, episode2) or (None, None, None) if not found."""
    import re

    m = re.search(r"(?i)\bs\s*(\d{1,2})\s*[._ -]?\s*e\s*(\d{1,3})\b", name)
    if not m:
        return None, None, None
    s = int(m.group(1))
    e = int(m.group(2))
    # show is the part before the match
    show = name[: m.start()].strip()
    # cleanup separators
    show = re.sub(r"[._\-]+", " ", show).strip()
    return show or None, f"{s:02d}", f"{e:02d}"


def _sanitize_filename(name: str) -> str:
    # Minimal sanitization: remove path separators and control chars
    import re

    # Replace path separators
    name = name.replace("/", "_").replace("\\", "_")
    # Collapse multiple whitespace
    name = re.sub(r"\s+", " ", name).strip()
    # Remove characters not generally safe in filenames
    name = re.sub(r"[\0<>:\"/\\|?*]", "", name)
    return name


def render_name(cfg: SiftConfig, item: Dict[str, Any]) -> str:
    """Render a target filename using naming templates and available tokens.

    Minimal implementation (no online lookups): derive tokens from the
    incoming filename (stem/ext), simple SXE parsing for TV, and ffprobe-derived
    facts (res, hdr, vcodec, acodec, audio channels). Honors
    `fallback_to_stem` and `sanitize` config.
    """
    from pathlib import Path

    rel = item.get("relpath")
    if not isinstance(rel, str) or not rel:
        raise ValueError("inventory item missing relpath")

    stem = Path(rel).stem
    ext = Path(rel).suffix.lstrip(".")

    # derive basic facts
    facts = derive_facts(cfg, item)

    # tokens
    title = None
    year = None
    show = None
    season2 = None
    episode2 = None

    # Try TV SXE detection
    show, season2, episode2 = _parse_sxe_from_name(stem)

    if show:
        # TV template selected
        template = cfg.naming.tv_template
    else:
        template = cfg.naming.movie_template
        # Try naive year extraction (4-digit year)
        import re

        ym = re.search(r"\b(19|20)\d{2}\b", stem)
        if ym:
            year = ym.group(0)
            # title is part before year
            title = stem[: ym.start()].strip()
            title = re.sub(r"[._\-]+", " ", title).strip() or None

    # Fallback to stem for title/show when configured
    if cfg.naming.fallback_to_stem:
        if not show:
            title = title or stem
        else:
            show = show or stem

    # derive vcodec/acodec tags
    vcode = facts.get("vcodec")
    acode = facts.get("acodec")
    vcodec_tag = ""
    acodec_tag = ""
    if isinstance(vcode, str):
        vcodec_tag = cfg.naming.vcodec_map.get(vcode.lower(), (vcode or "").upper())
    if isinstance(acode, str):
        acodec_tag = cfg.naming.acodec_map.get(acode.lower(), (acode or "").upper())

    # expose audio codec as an explicit token so templates can include it
    # directly (e.g., '{audio_codec}'). The numeric channel-count token
    # `{audio_channels}` is populated after we compute `ch`.
    audio_codec = acodec_tag or ""

    # audio tag: human-friendly channel label. Use explicit mappings for
    # common multichannel layouts (7.1 / 5.1) and decimal form for stereo/mono
    # appended with 'ch' to make intent clear (e.g. '2.0ch', '5.1ch'). Also
    # expose numeric channel count separately via `audio_channels`.
    ch = facts.get("min_audio_channels") or 0
    audio_tag = ""
    if ch >= 8:
        audio_tag = "7.1ch"
    elif ch >= 6:
        audio_tag = "5.1ch"
    elif ch >= 2:
        audio_tag = f"{int(ch)}.0ch"
    elif ch == 1:
        audio_tag = "1.0ch"

    # numeric channel count token
    audio_channels = str(ch) if ch else ""

    # hdr string
    hdr = "HDR" if facts.get("hdr") else ""

    # flags: include tier flags if available in item, but filter out judgement flags
    flags_val = ""
    t = None
    try:
        # attempt to find tier from routing
        media_type, tier, _, _ = route_destination(cfg, item)
        t = tier
    except Exception:
        t = None

    # Filter out "judgement" flags that shouldn't appear in filenames; this is
    # configurable in your TOML via flags.judgement_flags
    jflags = set(getattr(cfg.flags, "judgement_flags", []))
    flag_list: list[str] = []
    if t and getattr(t, "flags", None):
        for f in t.flags:
            if f not in jflags:
                flag_list.append(f)

    # Runtime/content-derived flags
    # HFR
    try:
        if cfg.flags.enable_hfr_flag:
            fps = None
            v = item.get("ffprobe", {}).get("video")
            if isinstance(v, dict):
                fps = v.get("fps")
            if isinstance(fps, (int, float)) and fps > cfg.flags.hfr_fps_threshold:
                flag_list.append("HFR")
    except Exception:
        pass

    # Low bitrate
    try:
        if cfg.flags.enable_low_bitrate_flag:
            res_label = facts.get("res")
            thr = None
            if isinstance(res_label, str):
                thr = cfg.flags.low_bitrate_thresholds.get(res_label)
            bps = item.get("ffprobe", {}).get("overall_bitrate_bps")
            if thr and isinstance(bps, (int, float)) and bps < thr:
                flag_list.append(cfg.flags.low_bitrate_flag_name)
    except Exception:
        pass

    flags_val = " ".join(flag_list)

    # Build replacements dict
    repl = {
        "title": title or "",
        "year": year or "",
        "show": show or "",
        "season2": season2 or "",
        "episode2": episode2 or "",
        "stem": stem,
        "res": facts.get("res") or "",
        "hdr_sep": cfg.naming.hdr_sep or "",
        "hdr": hdr,
        "vcodec_tag": vcodec_tag or "",
        "acodec_tag": acodec_tag or "",
        "audio_tag": audio_tag or "",
        "audio_codec": audio_codec or "",
        "audio_channels": audio_channels or "",
        "flags_sep": cfg.naming.flags_sep or "",
        "flags": flags_val or "",
        "ext": ext or "",
    }

    name = template
    for k, v in repl.items():
        name = name.replace("{" + k + "}", str(v))

    # Clean up: collapse whitespace and remove empty bracket pairs
    import re

    name = re.sub(r"\s+", " ", name).strip()
    # Remove empty brackets like [ ] or ()
    name = re.sub(r"\[\s*\]", "", name)
    name = re.sub(r"\(\s*\)", "", name)
    name = name.strip()

    if cfg.naming.sanitize:
        name = _sanitize_filename(name)

    # Enforce max length
    if cfg.naming.max_filename_len and len(name) > cfg.naming.max_filename_len:
        # Keep extension length
        ext_part = f".{repl['ext']}" if repl["ext"] else ""
        base_len = cfg.naming.max_filename_len - len(ext_part)
        name = name[:base_len].rstrip() + ext_part

    return name


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
