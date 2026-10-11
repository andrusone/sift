# Plex (PLX)

Read-only access to the owner's Plex server, to see what Plex believes about each file and what it does at play time. Writing to Plex is out of scope for phase 1 and needs owner approval (`docs/SAFETY.md`, rule 3).

Assumptions (unverified until the owner runs it against the real server; each is a card assumption to confirm):

- The library listing exposes, per media part, the file path and the list of streams with a language and `default` and `selected` flags.
- `selected` in the library listing may be absent or reflect only a saved choice, not what Plex would auto-select at play time. PLX-FR-6 exists to observe the play-time choice.
- A playing session reports the client, the decision for video and audio (direct play, copy or transcode) and the selected streams.

### PLX-FR-1: Credentials come from the environment

The Plex address and token are read from `PLEX_URL` and `PLEX_TOKEN`. If either is missing the command exits with a clear error and no network call. The token is never printed, logged, included in an exception message, written to a report or accepted as a command-line argument.

**Acceptance:** with a fake token set, the token string appears nowhere in stdout, stderr, logs or report files, including on an error path.
**Tests:** `test_plex_requires_env_vars`, `test_plex_token_not_in_output_on_success`, `test_plex_token_not_in_output_on_error`.
**Guard:** `tests/test_guards.py::test_plex_token_never_in_output` (GRD-FR-3).
**Depends on:** none.

### PLX-FR-2: The Plex client only reads

The Plex client issues HTTP GET requests only.

**Acceptance:** against a fake server that records request methods, a full snapshot and an observe run issue only GET.
**Tests:** `test_plex_client_only_sends_get`.
**Guard:** `tests/test_guards.py::test_plex_client_get_only` (GRD-FR-2).
**Depends on:** PLX-FR-1.

### PLX-FR-3: Snapshot of libraries, parts and streams

`sift plex-snapshot` lists the configured libraries (by name) and writes one JSON line per media part: the Plex item id, the part's file path, container, and every stream as Plex reports it (id, type, codec, language code, `default`, `selected`, display title). Fields Plex does not return are `null`.

**Acceptance:** against a fake server serving a recorded response, the snapshot has one row per part and every stream appears with its flags.
**Tests:** `test_plex_snapshot_rows_per_part`, `test_plex_snapshot_streams_and_flags`, `test_plex_snapshot_missing_fields_null`.
**Depends on:** PLX-FR-2.

### PLX-FR-4: Join Plex to the inventory

A snapshot row is matched to an inventory row by file path after applying `plex.path_map` (a list of `plex_prefix` to `local_prefix` pairs, for the difference between the path Plex sees and the path sift sees). Rows that match neither way are reported as `plex_only` or `sift_only`.

**Acceptance:** with a path map, a Plex row for `/data/movies/a.mkv` matches the inventory row for `/nas/plex/movies/a.mkv`. Unmatched rows appear in a separate list.
**Tests:** `test_join_with_path_map`, `test_join_reports_unmatched_both_ways`, `test_join_without_map_matches_identical_paths`.
**Depends on:** PLX-FR-3, PRB-FR-4.

### PLX-FR-5: Where Plex disagrees with the file

For each joined file, the report states the default audio stream according to the file (PRB-FR-1) and the audio stream Plex marks `selected` and `default`, and flags `plex_selection_differs` when they are not the same stream. This is an observation, not a verdict.

**Acceptance:** a file whose Plex-selected audio stream is not the file's default audio stream is flagged; one where they agree is not.
**Tests:** `test_selection_differs_flagged`, `test_selection_agrees_not_flagged`, `test_selection_missing_in_plex_reported_unknown`.
**Depends on:** PLX-FR-4.

### PLX-FR-6: Observe what Plex does at play time

`sift plex-observe` polls the server's active sessions at an interval (default 5 seconds) until stopped, and appends one JSON line each time a session's state changes. A line records the time, the session's client name and platform, the item's Plex id, the video decision, the audio decision, the transcode reasons Plex gives, and the streams in use (type, codec, language, id).

**Acceptance:** with a fake server that reports a session which starts as direct play and changes to an audio transcode, two lines are written, and an unchanged poll writes nothing.
**Tests:** `test_observe_writes_line_on_change_only`, `test_observe_records_decisions_and_streams`, `test_observe_stops_cleanly`.
**Depends on:** PLX-FR-2.

### PLX-FR-7: Observations are keyed to the library

Each observed session line carries the matching inventory `id` (SRV-FR-2) when the Plex item can be joined (PLX-FR-4), and no title or path.

**Acceptance:** an observed session for a joined file carries the same `id` as that file's survey row.
**Tests:** `test_observe_line_has_inventory_id`, `test_observe_line_has_no_name_or_path`.
**Depends on:** PLX-FR-6, PLX-FR-4.
