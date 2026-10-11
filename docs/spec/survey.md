# Survey (SRV)

A read-only report of what is actually in the library. It gathers evidence; it does not decide whether a file is good or bad.

### SRV-FR-1: Survey is read-only

`sift survey` reads the inventory and writes only its own report files. It does not copy, move, rename or create anything under `outgoing_root`, and it does not call Plex.

**Acceptance:** after a survey, `outgoing_root` is unchanged and `incoming` is unchanged.
**Tests:** `test_survey_does_not_touch_outgoing_or_incoming`.
**Guard:** `tests/test_guards.py::test_destructive_ops_only_in_allowlist` (GRD-FR-1).
**Depends on:** PRB-FR-4.

### SRV-FR-2: One row per file

The survey writes one JSON line per file. A row has a stable `id` (a hash of the relative path, never the name), the container, the file size and duration, the video stream facts from PRB-FR-1, and every audio and subtitle stream from PRB-FR-1. File names and paths are not in a row unless the owner passes `--include-names`.

**Acceptance:** rows contain every stream of the file and no title or path by default.
**Tests:** `test_survey_row_has_all_streams`, `test_survey_row_omits_names_by_default`, `test_survey_include_names_flag`.
**Depends on:** SRV-FR-1.

### SRV-FR-3: Corpus summary

The survey writes a Markdown summary with counts by container, video codec, resolution bucket, `hdr_format`, Dolby Vision profile, audio codec (across all tracks, and for the default track), number of audio tracks per file, and subtitle kind (bitmap or text). Probe failures are listed separately.

**Acceptance:** the counts in the summary equal the counts computed independently from the rows.
**Tests:** `test_survey_summary_counts_match_rows` (expected values computed from the fixture list, not by the summariser).
**Depends on:** SRV-FR-2.

### SRV-FR-4: Audio selection candidates

For every file with two or more audio streams, the survey reports which stream is the default stream (the one marked `default`, else the first), and whether another stream exists whose codec is in `survey.candidate_audio_codecs` (default `["ac3", "eac3", "aac"]`) while the default stream's codec is not. Such a file is reported as `audio_candidate_mismatch`. This is a pointer for investigation, not a verdict; phase 3 replaces it with the compatibility rule.

**Acceptance:** a file with an English DTS default track and an AC3 non-default track is flagged. A file whose default track is already AC3 is not.
**Tests:** `test_audio_candidate_mismatch_flagged`, `test_audio_candidate_not_flagged_when_default_ok`, `test_default_is_first_when_none_marked`.
**Depends on:** SRV-FR-2.

### SRV-FR-5: Where the report goes

Reports go to `survey.report_dir` (default: a `survey` folder under `paths.metadata_cache`). The directory is created if missing. The command prints the paths it wrote and a one-line total.

**Acceptance:** a run prints where the JSONL and Markdown went; the files exist.
**Tests:** `test_survey_writes_reports_to_configured_dir`, `test_survey_prints_paths`.
**Depends on:** SRV-FR-2.
