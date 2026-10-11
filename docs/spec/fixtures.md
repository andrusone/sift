# Fixtures (FIX)

Real probe data is the best test input and the repository is public. These requirements let the owner turn real files into safe, committed test data.

### FIX-FR-1: Export sanitised fixtures

`sift fixture export --id <id> ...` writes sanitised copies of the chosen inventory rows. Names, paths, titles, free-text tags (title, comment, encoder, handler) and anything not on the allowlist (FIX-FR-2) are removed. Stream technical fields are kept. The `id` is replaced by `fixture-NNNN`.

**Acceptance:** an exported fixture for a row with a real-looking path and title contains neither, and keeps every stream's codec, profile, channels, language and dispositions.
**Tests:** `test_fixture_export_removes_names_and_paths`, `test_fixture_export_keeps_stream_fields`, `test_fixture_export_renumbers_ids`.
**Depends on:** PRB-FR-1, SRV-FR-2.

### FIX-FR-2: Committed fixtures use an allowlist

Every JSON fixture under `tests/fixtures/` may contain only keys on a single allowlist kept in `tests/fixture_schema.py`. Adding a key requires editing the allowlist.

**Acceptance:** a fixture containing a `path` key or an unlisted key fails the build.
**Tests:** `test_fixtures_use_allowlisted_keys`.
**Guard:** `tests/test_guards.py::test_fixtures_use_allowlisted_keys`.
**Depends on:** none.
