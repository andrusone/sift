# Control set (CTL)

The control set is the owner's list of titles that misbehave, plus a few that behave, with what was seen on the owner's player. It turns "this looks wrong" into evidence every later rule can be tested against.

Real control-set data lives outside git (`var/control/`, git-ignored). Only the schema, the validator and sanitised fixtures are committed.

### CTL-FR-1: Manifest format and validator

The control manifest is a TOML file with one `[[control]]` table per title, with these keys: `id` (an inventory `id` from SRV-FR-2), `kind` (`fail` or `pass`), `client` (`plex-appletv`, `plex-roku`, `infuse-appletv`, `plex-web`, `other`), `symptom` (one of `none`, `no_audio`, `wrong_audio`, `audio_transcode`, `video_transcode`, `subtitle_burn_in`, `buffering`, `other`), `expected_audio_language`, and free-text `notes`. `sift control validate <file>` checks the file and lists every problem, naming the entry by its id.

**Acceptance:** a valid manifest passes; a manifest with an unknown symptom, a duplicate id, a `pass` entry with a symptom other than `none`, or an id not in the inventory is rejected with the entry named.
**Tests:** `test_manifest_valid`, `test_manifest_rejects_unknown_symptom`, `test_manifest_rejects_duplicate_id`, `test_manifest_pass_must_have_symptom_none`, `test_manifest_id_must_exist_in_inventory`.
**Depends on:** SRV-FR-2.

### CTL-FR-2: One report per control title

`sift control report` writes, for each manifest entry, a single record joining the survey row, the Plex snapshot row (when available), the observed sessions (when available) and the owner's symptom. Missing sources are stated as missing, not omitted.

**Acceptance:** each entry produces one record containing all four sources, or an explicit `missing` for each one that is absent.
**Tests:** `test_control_report_joins_all_sources`, `test_control_report_marks_missing_sources`.
**Depends on:** CTL-FR-1, PLX-FR-5, PLX-FR-7.

### CTL-FR-3: Control data stays out of git

The default location for the manifest and control reports is `var/control/`. `var/` is listed in `.gitignore`.

**Acceptance:** a file created under `var/` is not tracked by git.
**Tests:** `test_var_dir_is_gitignored`.
**Guard:** `tests/test_guards.py::test_var_dir_is_gitignored` (GRD-FR-4).
**Depends on:** none.
