# Terminalis Plugins

[![Build plugin zips](https://github.com/JuanEoss/terminalis-releases/actions/workflows/build-plugin-zips.yml/badge.svg)](https://github.com/JuanEoss/terminalis-releases/actions/workflows/build-plugin-zips.yml)

Curated registry and marketplace catalog for [Terminalis](https://github.com/) Lua plugins.

- **`index.json`** — the catalog Terminalis's Settings → Plugins → Marketplace fetches over HTTPS to list installable plugins.
- **`plugins/<name>/`** — each plugin's reviewed source (`src/`), metadata (`manifest.json`), and CI-built distributable (`build/plugin.zip` + `checksum.sha256`).

Every plugin here has gone through a human-reviewed pull request — there is no auto-merge and no third-party repo mixing. See [`CONTRIBUTING.md`](./CONTRIBUTING.md) to publish or update a plugin, and [`plugin-development.md`](./plugin-development.md) for the full plugin API, sandbox, and permission model plugins run under inside Terminalis.
