## Plugin PR checklist

- [ ] New plugin lives in `plugins/<name>/src/` (or this PR bumps an existing plugin's version)
- [ ] `manifest.json` is present and its `name`/`version`/`permissions` match `M.name`/`M.version`/`M.permissions` in `src/init.lua`
- [ ] Declared `permissions` are the minimum required — no `"shell"` unless the plugin actually calls `terminalis.shell`
- [ ] Plugin only uses `require()` for files inside its own `src/` directory
- [ ] Manually tested by loading the plugin locally (Settings → Plugins → Recargar)

### What does this plugin do?

<!-- One or two sentences. -->

### Permissions requested

<!-- List each permission and why it's needed, or "none". -->

### Testing performed

<!-- How did you verify this works? -->
