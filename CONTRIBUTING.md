# Contributing a plugin

This repo is a **curated** registry — every plugin is reviewed by a human before it's
listed in `index.json`. There is no auto-merge and no way to publish without a PR.

## Adding a new plugin

1. Fork the repo, create `plugins/<name>/src/` and add `init.lua` (plus any modules
   loaded via `require()`), following [`plugin-development.md`](./plugin-development.md).
2. Add `plugins/<name>/manifest.json`:
   ```json
   {
     "name": "<name>",
     "version": "1.0",
     "author": "you",
     "description": "One sentence.",
     "permissions": []
   }
   ```
   `name`, `version` and `permissions` here must exactly match `M.name`, `M.version`
   and `M.permissions` in `init.lua` — CI fails the PR otherwise.
3. Open a PR. Fill in the checklist in the PR template.
4. A reviewer reads `src/` (not any zip — none exists yet on your branch) and either
   requests changes or approves.
5. On merge to `main`, CI regenerates `build/plugin.zip`, `build/checksum.sha256` and
   `index.json` automatically and commits them directly to `main`. You don't need to
   build or upload a zip yourself, ever.

## Updating an existing plugin

Same flow: bump `version` in both `manifest.json` and `M.version` in `init.lua`, open
a PR. CI validates the bump is consistent; the registry entry updates once merged.

## Naming and versioning

- Plugin directory name = `M.name`, lowercase, hyphen-separated, must be unique across
  the registry. Once published, don't rename it — see the note on directory-name
  stability in `plugin-development.md`.
- Versions are free-form strings compared for display only (no semver enforcement
  yet) — keep them monotonically increasing so "update available" makes sense to users.

## Why zips aren't built on the PR itself

Building and auto-committing the zip requires a `contents: write` token. Granting
that to a workflow triggered by an arbitrary fork's `pull_request` would let an
unreviewed PR push commits to the repo. Instead, zips are only rebuilt by the `push`
job that runs on `main`, after your PR has already been reviewed and merged. PR
checks only run `scripts/build_index.py --check`, which validates `manifest.json`
against `init.lua` with a read-only token — safe to run against untrusted forks.

Reviewers should read `src/`, not any binary artifact.
