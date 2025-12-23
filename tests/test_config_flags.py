import tomllib

from sift.config import parse_config


def test_judgement_flags_parsed(tmp_path):
    cfg_text = """
[paths]
incoming = "./incoming"
outgoing_root = "./out"
metadata_cache = "./cache"

[io]
mode = "copy"
mkdirs = true
dedupe_on_collision = true

[ffprobe]
bin = "ffprobe"
args = ["-v","error"]

[classification]
media_type_strategy = "sxe"
video_stream_strategy = "best"
audio_stream_strategy = "best"
audio_codec_preference = []
problem_audio_codecs = []
problem_audio_profile_regex = []
hdr_color_transfer = []
hdr_side_data_regex = []

[naming]
movie_template = "x"
tv_template = "y"
hdr_sep = " "
flags_sep = " "
fallback_to_stem = true
vcodec_map = {}
acodec_map = {}
sanitize = true
max_filename_len = 200

[tier_model]
tiers = 3
[[tier_model.tier]]
id = "T1"
folder = "T1"
description = ""
requires = {}
flags = ["REF"]

[[tier_model.tier]]
id = "T2"
folder = "T2"
description = ""
requires = { res = ["2160p"] }
flags = ["KEEP"]

[[tier_model.tier]]
id = "T3"
folder = "T3"
description = ""
requires = { res = ["1080p"] }
flags = ["OK"]

[flags]
enable_hfr_flag = false
hfr_fps_threshold = 60.0
enable_low_bitrate_flag = false
low_bitrate_thresholds = {"default" = 1}
low_bitrate_flag_name = "LOW"
judgement_flags = ["FOO","BAR"]

[reporting]
write_jsonl_report = false
report_path = "./report.jsonl"
"""

    root = tomllib.loads(cfg_text)
    cfg = parse_config(root)
    assert cfg.flags.judgement_flags == ["FOO", "BAR"]
