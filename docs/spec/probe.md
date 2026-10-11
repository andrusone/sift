# Probe and cache (PRB)

Everything later depends on seeing every stream in a file and on re-reading the library cheaply and safely on a schedule.

### PRB-FR-1: Record every stream

For each file, the probe summary lists every video, audio and subtitle stream, in file order, with its index and type.

Per stream: `codec`, `profile`, `language`, `title`, and the disposition flags `default`, `forced`, `comment`, `hearing_impaired`.
Video also: `width`, `height`, `pix_fmt`, `bit_depth`, `fps`, `field_order`, `sample_aspect_ratio`, `display_aspect_ratio`, `color_space`, `color_transfer`, `color_primaries`, `bit_rate_bps`, `hdr_format` (one of `sdr`, `hdr10`, `hlg`, `dolby_vision`, `unknown`), and `dv_profile`, `dv_level`, `dv_bl_compat_id` when Dolby Vision data is present.
Audio also: `channels`, `channel_layout`, `sample_rate_hz`, `bit_rate_bps`.
Subtitle also: `codec` is enough to tell bitmap (`hdmv_pgs_subtitle`, `dvd_subtitle`) from text.

A field `ffprobe` does not report is `null`, never omitted.

**Acceptance:** the summary for a file with two audio tracks and three subtitle tracks lists both audio tracks and all three subtitle tracks with their languages and default flags. A Dolby Vision file reports its profile.
**Tests:** `test_probe_lists_all_streams`, `test_probe_dispositions_and_language`, `test_probe_dolby_vision_profile`, `test_probe_missing_fields_are_null`.
**Depends on:** none.

### PRB-FR-2: Keep the v1 summary fields

The existing `video`, `audio` and `stream_counts` fields keep their current names, meaning and values, so the v1 classification and naming produce identical output.

**Acceptance:** the v1 test suite passes unchanged, and a golden test shows the v1 fields for a multi-audio file are byte-identical to before this change.
**Tests:** `test_v1_summary_fields_unchanged`.
**Depends on:** PRB-FR-1.

### PRB-FR-3: Cache per file

Each file's probe result is cached under a key of its relative path, size and modification time (ns), together with a cache schema version. A file whose key is unchanged is not probed again. A file whose key or the schema version changed is probed again. A file that no longer exists is dropped from the next inventory.

**Acceptance:** run twice with no changes and `ffprobe` is invoked zero times the second run. Touch one file and `ffprobe` is invoked once, for that file.
**Tests:** `test_cache_hit_skips_probe`, `test_cache_miss_on_size_or_mtime_change`, `test_cache_miss_on_schema_version`, `test_removed_file_dropped`.
**Depends on:** PRB-FR-1.

### PRB-FR-4: New files are found without a rescan

A normal run (no `--rescan`) lists the current contents of `incoming`, uses the cache for files it knows and probes only the new ones. `--rescan` still forces a full re-probe.

**Acceptance:** a file added to `incoming` after the last run appears in the next normal run's inventory.
**Tests:** `test_new_file_seen_without_rescan`, `test_rescan_flag_reprobes_all`.
**Depends on:** PRB-FR-3.

### PRB-FR-5: Probe timeout

Each `ffprobe` call has a timeout. The default is 60 seconds and it is set by `ffprobe.timeout_s` in the config. A timeout is recorded for that file as `ffprobe.ok = false` with error `timeout`, and the run continues with the next file.

**Acceptance:** a probe that never returns does not stop the run; the file is reported as a probe failure.
**Tests:** `test_probe_timeout_recorded_and_run_continues`, `test_probe_timeout_config_validated`.
**Depends on:** none.
