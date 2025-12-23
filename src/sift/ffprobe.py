from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .model import FFProbeConfig
from .utils import parse_ratio, safe_float, safe_int


def run_ffprobe(
    cfg: FFProbeConfig, media_path: Path
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return (json, error_str). Never raises for per-file failures."""
    cmd = [cfg.bin, *cfg.args, str(media_path)]
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        return None, f"ffprobe not found: {cfg.bin}"
    except OSError as e:
        return None, f"ffprobe exec error: {e}"

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        return None, stderr or f"ffprobe exited {proc.returncode}"

    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as e:
        return None, f"ffprobe output was not valid JSON: {e}"


def summarize(ff: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a compact subset of technical metrics (stable cache footprint)."""
    out: Dict[str, Any] = {"ok": True}

    fmt = ff.get("format") or {}
    out["container"] = fmt.get("format_name")
    out["duration_s"] = safe_float(fmt.get("duration"))
    out["overall_bitrate_bps"] = safe_int(fmt.get("bit_rate"))
    out["size_bytes_probe"] = safe_int(fmt.get("size"))

    streams = ff.get("streams") or []
    if not isinstance(streams, list):
        streams = []

    vstreams = [
        s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"
    ]
    astreams = [
        s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"
    ]

    vbest = None
    if vstreams:

        def vkey(s: Dict[str, Any]) -> tuple[int, int]:
            w = safe_int(s.get("width")) or 0
            h = safe_int(s.get("height")) or 0
            return (w * h, h)

        vbest = sorted(vstreams, key=vkey, reverse=True)[0]

    abest = None
    if astreams:

        def akey(s: Dict[str, Any]) -> tuple[int, int]:
            ch = safe_int(s.get("channels")) or 0
            br = safe_int(s.get("bit_rate")) or 0
            return (ch, br)

        abest = sorted(astreams, key=akey, reverse=True)[0]

    if vbest:
        vf: Dict[str, Any] = {
            "codec": vbest.get("codec_name"),
            "profile": vbest.get("profile"),
            "width": safe_int(vbest.get("width")),
            "height": safe_int(vbest.get("height")),
            "pix_fmt": vbest.get("pix_fmt"),
            "bit_rate_bps": safe_int(vbest.get("bit_rate")),
            "fps": parse_ratio(vbest.get("avg_frame_rate"))
            or parse_ratio(vbest.get("r_frame_rate")),
            "color_space": vbest.get("color_space"),
            "color_transfer": vbest.get("color_transfer"),
            "color_primaries": vbest.get("color_primaries"),
            "color_range": vbest.get("color_range"),
        }
        tags = vbest.get("tags") if isinstance(vbest.get("tags"), dict) else {}
        vf["tags"] = {k: str(v) for k, v in tags.items()} if tags else {}
        side_data = vbest.get("side_data_list")
        if isinstance(side_data, list):
            types = []
            for sd in side_data:
                if isinstance(sd, dict) and sd.get("side_data_type"):
                    types.append(str(sd.get("side_data_type")))
            vf["side_data_types"] = sorted(set(types))
        out["video"] = vf

    if abest:
        af: Dict[str, Any] = {
            "codec": abest.get("codec_name"),
            "profile": abest.get("profile"),
            "channels": safe_int(abest.get("channels")),
            "channel_layout": abest.get("channel_layout"),
            "sample_rate_hz": safe_int(abest.get("sample_rate")),
            "bit_rate_bps": safe_int(abest.get("bit_rate")),
        }
        out["audio"] = af

    out["stream_counts"] = {"video": len(vstreams), "audio": len(astreams)}
    return out
