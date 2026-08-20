# Terminalis Releases

Marketplace catalog for [Terminalis](https://github.com/) Lua plugins. This repo
holds **generated build artifacts only** — no plugin source code lives here.

- **`marketplace/index.json`** — the catalog Terminalis's Settings → Plugins →
  Marketplace fetches over HTTPS to list installable plugins.
- **`marketplace/plugins/<name>.zip`** — each plugin's distributable, built and
  checksummed automatically. Never hand-built or hand-edited.

## Where plugins actually come from

Plugin source code, contribution, and human review happen in
[`terminalis-plugins`](https://github.com/JuanEoss/terminalis-plugins) (private).
Once a plugin PR is reviewed and merged there, a workflow rebuilds
`marketplace/plugins/<name>.zip` and `marketplace/index.json` from the full set of
published plugins and pushes them here, authenticated as the
`terminalis-release-publisher` GitHub App.

This repo's own branch protections (PR + review required, direct pushes blocked)
still apply to everything except that App's automated sync — so nothing reaches
`main` here without either a reviewed PR or that same trusted, auditable pipeline.
