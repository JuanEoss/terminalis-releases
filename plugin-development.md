# Plugin Development Guide

Terminalis supports Lua-based plugins that extend the app without modifying its source code. Plugins run **embedded inside the app** using a Lua 5.4 VM compiled directly into the binary — no subprocess spawn, no IPC overhead. All Lua execution runs on a dedicated background queue, keeping the UI fully responsive.

Plugins can be installed two ways:

- **Manually** — drag a plugin's `src/` folder (or an extracted `plugin.zip`) into `~/Library/Application Support/Terminalis/plugins/`, or use **Settings → Plugins → Install from file…** (`NSOpenPanel`).
- **From the marketplace** — Settings → Plugins → Marketplace lists every plugin published in this repo's `index.json` and installs it with one click. See [Publishing to the marketplace](#publishing-to-the-marketplace) below if you're building a plugin to distribute this way.

Either path ends up running the exact same `init.lua` through the exact same sandbox and permission system described in this document — the marketplace is only a distribution and integrity-verification layer on top of manual install, not a different security model.

---

## Scope — what plugins can and cannot do

### Surfaces available to plugins

| Surface | How to declare | What you get |
|---|---|---|
| **Side panel** | `M.panel = { ... }` | Resizable column panel (left or right) with UI components or a full webview |
| **Bottom toolbar** | `M.toolbar = { ... }` | Fixed-height horizontal strip (38px) at the bottom of the window — native components or a full webview |
| **File tab view** | `M.tab_view = { file_types = {...} }` | Custom renderer for specific file types — replaces the built-in editor in the same tab |
| **Content tab** | `terminalis.tab.open(html, opts)` | Full-screen tab with arbitrary HTML content |
| **Native content tab** | `terminalis.tab.open({ mode="native" })` | Full-screen tab rendered with native SwiftUI components via `M.render_tab(ctx)` |
| **Context menu items** | `M.tab_menu_items` / `M.on_tab_context_menu` | Items injected into the right-click menu of tabs and groups |
| **Tab sidebar buttons** | `M.tab_buttons` / `M.on_tab_render` | Icon buttons shown inline on each tab row in the sidebar |
| **Status bar item** | `terminalis.status.set(...)` | One slot in the bottom status bar per plugin |
| **Lifecycle hooks** | `M.on_load`, `M.on_command`, etc. | React to terminal events (commands, cwd changes, tab open/close) |

### Capabilities available to plugins

| Capability | API | Requires permission |
|---|---|---|
| Run shell commands | `terminalis.shell(cmd)` | ✅ `"shell"` |
| React to terminal output | `M.on_output(ctx)` | ✅ `"output"` |
| Make HTTPS requests | `terminalis.http(...)` | No |
| Inject text into the terminal | `terminalis.send(text)` | No |
| Show a notification banner | `terminalis.notify(text)` | No |
| Open a URL in the browser | `terminalis.open_url(url)` | No |
| Open a local file as a Terminalis tab | `terminalis.open_file(path)` | No |
| Store secrets (Keychain) | `terminalis.store` / `terminalis.load` | No |
| Store preferences (UserDefaults) | `terminalis.storage.set` / `.get` | No |
| Read the active tab's context | `terminalis.active_tab()` | No |
| Handle OAuth redirects | `terminalis.on_url_callback(fn)` | No |
| Control the plugin's own panel | `terminalis.panel.*` | No |

### What plugins cannot do

- **Modify core layout** — the sidebar, tab bar, status bar structure, and window chrome are not accessible. Plugins add to them but cannot reorganize or remove existing elements.
- **Access other plugins' state** — each plugin's storage is namespaced by `M.name`. There is no inter-plugin communication channel.
- **Run persistent background processes** — `terminalis.shell` is synchronous and bounded by a timeout. There is no way to keep a process alive across calls.
- **Load arbitrary native code** — `package.loadlib` is nil and `package.cpath` is empty. Plugins can use `require("module")` to load other `.lua` files within their own directory, but cannot load `.dylib` files or native extensions.
- **Read or write arbitrary files from Lua** — the `io` library is not available. File access goes through `terminalis.shell` (requires `"shell"` permission) or `terminalis.open_file` (opens in the editor, doesn't read content).
- **Make HTTP requests to private networks** — `terminalis.http` blocks loopback, RFC-1918, link-local, and single-label hostnames. Only public HTTPS endpoints are reachable.
- **Navigate the webview away from plugin content** — link clicks in tab view and panel webviews are intercepted: HTTPS links open in the system browser, relative file links open in the file explorer. The webview never navigates to an external page.
- **Render arbitrary native SwiftUI** — panels and tab views are rendered inside a `WKWebView` (UI DSL components in panels are translated to native views, but the layout is fixed).

---

## Security model

Terminalis uses a **layered** model combining Lua-level sandboxing with an explicit permission system for sensitive capabilities.

### Lua sandbox

| Lua library | Status | Reason |
|---|---|---|
| `string`, `table`, `math`, `utf8`, `coroutine` | ✅ Available | Safe, no system access |
| `os.time`, `os.date`, `os.clock` | ✅ Available | Read-only time functions |
| `os.execute`, `os.exit`, `os.getenv`, `os.remove` | ❌ Removed | Arbitrary shell / filesystem — calling any of these throws a Lua error and silently aborts the hook |
| `io` | ❌ Not opened | Arbitrary file read/write |
| `package` / `package.loadlib` | ❌ Not opened | Native `.dylib` injection |
| `debug` | ❌ Not opened | Cross-plugin data leakage |
| `dofile`, `loadfile` | ❌ Removed | Arbitrary file loading |
| `require` | ✅ Sandboxed | Only resolves `.lua` files inside the plugin's own directory — see [Modules](#modules) |
| `package.loadlib` | ❌ Removed | Native `.dylib` injection |

WKWebViews used by plugins block `file://` and `http://` navigation. Only `https://` resources are allowed.

### Permission system

Sensitive capabilities require **two layers of approval** before a plugin can use them:

1. The plugin **declares** the permission in its manifest (`M.permissions`).
2. The **user grants** it in **Settings → Plugins** — protected by Touch ID / Apple Watch / system password.

If either condition is not met, the API returns `nil` + an error string instead of executing.

| Permission | API | What it does |
|---|---|---|
| `"shell"` | `terminalis.shell()` | Run arbitrary shell commands as the current user |

```lua
-- Declare in manifest:
M.permissions = { "shell" }

-- Use defensively:
local out, err = terminalis.shell("git log --oneline -5")
if err then
    return { ui.label("Permission required: " .. err) }
end
```

Permissions can be revoked at any time from **Settings → Plugins** without uninstalling the plugin.

### `terminalis.send(text)` — no permission required

`terminalis.send` injects text into the terminal as if the user typed it. A malicious plugin could silently run destructive commands this way. Only install plugins you trust.

> **Install plugins only from sources you trust**, just as you would with any shell script or CLI tool.

---

## API surface overview

| API | Permission | Backend | Accepts | Use for |
|---|---|---|---|---|
| `terminalis.store(key, val)` | none | Keychain (UserDefaults in dev) | string only | Secrets, tokens, credentials |
| `terminalis.load(key)` | none | Keychain | — | Reading secrets |
| `terminalis.storage.set(key, val)` | none | UserDefaults | string, number, bool, table | Preferences, config, cached state |
| `terminalis.storage.get(key)` | none | UserDefaults | — | Reading preferences |
| `terminalis.shell(cmd, opts?)` | `"shell"` | configured shell | string | Running shell commands |
| `terminalis.send(text)` | none | Terminal | string | Injecting text into the terminal |
| `terminalis.http(method, url, ...)` | none | URLSession | — | HTTPS API calls |
| `terminalis.notify(text, opts?)` | none | In-app | — | Showing notifications |
| `terminalis.open_url(url)` | none | NSWorkspace | https:// only | Opening URLs in browser |
| `terminalis.open_file(path)` | none | AppState | string | Opening a local file as a Terminalis file tab |
| `terminalis.clipboard(text)` | none | NSPasteboard | string | Writing text to the system clipboard |
| `terminalis.log(msg)` | none | stderr | string | Debug logging (visible in Console.app) |
| `terminalis.selection()` | none | Terminal | — | Reading the currently selected text |
| `terminalis.set_env(key, val\|nil)` | none | Process env | string | Injecting env vars into new terminal tabs |
| `terminalis.tab.new(opts?)` | none | AppState | — | Opening a new terminal tab |
| `terminalis.tab.close()` | none | AppState | — | Closing the active terminal tab |
| `terminalis.tab.rename(name, tab_id?)` | none | AppState | string | Renaming a specific tab (or the active one if no tab_id) |
| `terminalis.tab.rename_group(name, tab_id?)` | none | AppState | string | Renaming the group that contains a tab |
| `terminalis.active_tab()` | none | — | — | Reading current tab state |
| `terminalis.panel.*` | none | — | — | Controlling the panel |
| `terminalis.status.*` | none | — | — | Status bar item |
| `terminalis.tab.open(html, opts)` | none | WKWebView | — | Opening webview content tabs |
| `terminalis.tab.open({ mode="native" })` | none | SwiftUI | — | Opening native component tabs |
| `terminalis.tab.refresh()` | none | SwiftUI | — | Re-rendering the active native tab |
| `terminalis.theme()` | none | — | — | Colors of the active theme |
| `terminalis.background.*` | none | WKWebView | — | Full-window overlay |

---

## Quick start

1. Create a directory in the plugins folder:
   ```
   ~/Library/Application Support/Terminalis/plugins/my-plugin/
   ```
2. Create `init.lua`:
   ```lua
   local M = {}
   M.name    = "my-plugin"
   M.version = "1.0"
   return M
   ```
3. Open **Settings → Plugins → Recargar** — your plugin appears in the list.

---

## Manifest

Every plugin is a Lua module that returns a table `M`. Required fields: `name` and `version`.

```lua
local M = {}

M.name        = "my-plugin"          -- required, must be unique
M.version     = "1.0"                -- required
M.author      = "yourname"           -- shown in Settings → Plugins
M.description = "What this does."   -- shown in Settings → Plugins
M.permissions = { "shell" }         -- optional — declare capabilities that need user approval

return M
```

> **Note:** The plugin's **directory name** (not `M.name`) is used as the key for the enabled/disabled state in UserDefaults. Keep the directory name stable — renaming it resets the enabled state and granted permissions.

---

## Publishing to the marketplace

This repo doubles as the plugin **registry**: `index.json` at the repo root is the
catalog the app's marketplace fetches over HTTPS, and each `plugins/<name>/` folder
holds the plugin's source plus a CI-built `build/plugin.zip`.

```
plugins/<name>/
  src/init.lua        ← your plugin, reviewed as source in the PR
  manifest.json        ← metadata mirror of M.name / M.version / M.permissions
  build/plugin.zip      ← generated by CI after merge — never hand-built
  build/checksum.sha256 ← generated by CI after merge
```

To publish:

1. Add `plugins/<name>/src/init.lua` and `plugins/<name>/manifest.json` (fields must
   exactly match `M.name`, `M.version`, `M.permissions` in `init.lua` — CI rejects the
   PR otherwise).
2. Open a PR against this repo. A human reviewer reads `src/`, not a binary.
3. On merge, CI rebuilds `build/plugin.zip` + `checksum.sha256` and regenerates
   `index.json` — this is the only step that produces the artifact end users download.

Full contribution flow, versioning rules, and why zip-building happens post-merge
rather than on the PR itself are in [`CONTRIBUTING.md`](./CONTRIBUTING.md).

**What the marketplace does and doesn't change:**

- The app verifies the downloaded zip's SHA-256 against `index.json` before touching
  the real plugins folder — a checksum mismatch aborts the install with no side effects.
- Declared `permissions` are shown to the user **before** they install, same badges as
  in Settings → Plugins.
- Installing from the marketplace never auto-grants a permission. The user still
  approves each one individually via Touch ID, exactly as with a manually installed
  plugin — see [Permission system](#permission-system).

---

## Extension points

A plugin contributes to any of these four slots:

```
┌──────────────────────────────────────────────────────────────────────┐
│  [≡] [left toolbar toggles]  [Global search…]  [toolbar][status] [ℹ][⚙]│ ← top bar
│         ↑                                          ↑          ↑      │
│  bar_position="left"                     M.toolbar toggle  terminalis.status│
├──────────┬─────────────┬──────────────────────────────┬──────────────┤
│          │             │  [tab.md ×]  [file.go ×]     │              │
│          │             │  ────────────────────────    │              │
│  Session │    File     │                              │    Plugin    │
│  list    │  Explorer   │   Terminal / File editor /   │    panel     │
│ (sidebar)│ (optional)  │   Plugin tab view            │   (right)    │
│          │             │                              │   M.panel    │
│          │             │  [🔍] [plugin toggle] [☀]   │              │
│          │             │           ↑                  │              │
│          │             │    M.tab_view toggle          │              │
└──────────┴─────────────┴──────────────────────────────┴──────────────┘
```

**Non-plugin surfaces** (not accessible to plugins): the session list (sidebar), the file explorer, and the window chrome.

| Slot | Declare | Implement | Where it appears |
|---|---|---|---|
| **Top bar item** | _(none)_ | `terminalis.status.set()` from any hook | Top bar, right side |
| **Panel toggle** | `M.panel = {...}` | — | Settings → Plugins (per-plugin row) |
| **Left panel** | `M.panel = { side = "left", ... }` | `M.panel_content()` | Left column (between explorer and terminal), resizable |
| **Right panel** | `M.panel = { side = "right", ... }` | `M.panel_content()` | Right column, resizable |
| **File tab view** | `M.tab_view = {...}` | `M.tab_view_content(ctx)` | Inside the file tab, replaces the editor |
| **Webview content tab** | — | `terminalis.tab.open(html, opts)` | Horizontal tab bar (same row as file tabs) |
| **Native content tab** | — | `terminalis.tab.open({ mode="native" })` + `M.render_tab(ctx)` | Horizontal tab bar, rendered with native SwiftUI components |
| **Tab context menu** | `M.tab_menu_items` | `M.on_tab_context_menu(ctx)` | Right-click menu on sidebar tab rows |
| **Group context menu** | `M.group_menu_items` | `M.on_group_context_menu(ctx)` | Right-click menu on sidebar group headers |
| **Tab sidebar buttons** | `M.tab_buttons` | `M.on_tab_render(ctx)` | Icon buttons in the trailing area of sidebar tab rows |
| **Terminal background** | `M.terminal_background = true` | `M.background_content()` | Full-window WKWebView behind the terminal |
| **Settings modal** | _(none)_ | `M.settings_content()` | Config button in Plugins settings |
| **Lifecycle hooks** | _(none)_ | `M.on_load`, `M.on_command`, etc. | Background — no visible surface |

---

## Lifecycle hooks

Hooks run on a **background queue** — they never block the UI thread.

```lua
function M.on_load()            end   -- plugin enabled or app started
function M.on_unload()          end   -- plugin disabled or app quit
function M.on_command(ctx)      end   -- every command the user runs (zsh preexec)
function M.on_cwd_change(ctx)   end   -- directory change (zsh precmd / OSC 7)
function M.on_keypress(ctx)     end   -- every keystroke in the active terminal
function M.on_tab_open(ctx)     end   -- new terminal tab opened
function M.on_tab_close(ctx)    end   -- terminal tab closed
function M.on_file_save(ctx)    end   -- user saved a file (ctx.command = absolute path)
function M.on_output(ctx)       end   -- terminal printed text (ctx.command = stripped text, requires "output" permission)
function M.render_tab(ctx)           end   -- return component tree for a native tab
function M.on_tab_context_menu(ctx)  end   -- return dynamic items for tab right-click menu
function M.on_group_context_menu(ctx) end  -- return dynamic items for group right-click menu
function M.on_tab_render(ctx)        end   -- return buttons/badge for sidebar tab row
```

### Context table

Every hook receives a `ctx` table. Not all fields are meaningful in every hook — see the notes column.

| Field | Type | Description | Hooks |
|---|---|---|---|
| `ctx.tab_id` | string | UUID of the terminal tab | all |
| `ctx.cwd` | string | Absolute working directory | all |
| `ctx.branch` | string | Git branch (`""` if not in a repo) | all |
| `ctx.tab_name` | string | Display name of the tab | all |
| `ctx.remote_url` | string | Git remote origin URL (`""` if no remote) | all |
| `ctx.command` | string | Command the user ran | `on_command` |
| `ctx.command` | string | Absolute path of the saved file | `on_file_save` |
| `ctx.command` | string | Terminal output (ANSI stripped) | `on_output` |
| `ctx.command` | string | Character typed | `on_keypress` |
| `ctx.process` | string | Basename of the last command run | all |
| `ctx.cursor_col` | number | Cursor column | `on_keypress` |
| `ctx.cursor_row` | number | Cursor row | `on_keypress` |
| `ctx.cursor_x` | number | Cursor X in window CSS pixels | `on_keypress` |
| `ctx.cursor_y` | number | Cursor Y in window CSS pixels | `on_keypress` |

> **`on_file_save`** fires only when the user saves via ⌘S from Terminalis's built-in editor.
>
> **`on_keypress` fires on every keystroke** — filter: `if #ctx.command ~= 1 or string.byte(ctx.command,1) < 32 then return end`.
> `cursor_x`/`cursor_y` include sidebar, explorer, and header — feed them directly into a full-window canvas.

---

## API reference

### `terminalis.shell(cmd, opts?)`

Run a shell command and return its stdout as a string. Defaults to the **active tab's working directory** — no need to `cd` first.

**Requires the `"shell"` permission** — declare it in `M.permissions` and have the user grant it in Settings. Returns `nil, error_message` if the permission is missing or not granted.

```lua
-- Always check for the error return:
local out, err = terminalis.shell("git log --oneline -10")
if err then
    return { ui.label("⛔ " .. err, { color = "#FF453A" }) }
end

-- With options:
local result, err = terminalis.shell("ls", { cwd = "/tmp", timeout = 3 })
```

| Option | Default | Description |
|---|---|---|
| `cwd` | Active tab's cwd | Working directory for the command |
| `timeout` | `5` | Seconds before the process is killed |

> **Performance:** `terminalis.shell` **blocks the Lua queue** for the duration of the command (up to `timeout` seconds). During that time no other plugin can execute hooks. Keep commands fast, use short timeouts, and avoid calling shell from `panel_content()` on every render if possible — cache results in a module-level variable and refresh via hooks instead.

> **Tip:** Avoid calling `terminalis.shell` on every keystroke. Once per `on_command` or `on_cwd_change` is fine — those fire at most once per user action.

---

### `terminalis.send(text, tab_id?)`

Inject text into the active terminal as if the user typed it.

```lua
terminalis.send("git status\n")          -- submit command (note the \n)
terminalis.send("git commit -m \"\"")   -- position cursor, don't submit
```

---

### `terminalis.notify(text, opts?)`

Show a notification banner at the top of the terminal.

```lua
terminalis.notify("Deploy done", { level = "info", duration = 3 })
terminalis.notify("Build failed", { level = "error" })
```

| `level` | Appearance |
|---|---|
| `"info"` (default) | Subtle banner |
| `"warning"` | Orange banner |
| `"error"` | Red banner |

---

### `terminalis.active_tab()`

Return the active tab's context without spawning any process.

```lua
local tab = terminalis.active_tab()
-- tab.cwd, tab.branch, tab.tab_id, tab.tab_name, tab.remote_url
```

---

### `terminalis.store(key, value | nil)` / `terminalis.load(key)` — **Secure storage**

Stores **sensitive data** (tokens, secrets, credentials) in the system **Keychain**, sandboxed per plugin. Only accepts strings. No shell or special permission required.

```lua
terminalis.store("gh_token", "ghp_abc123")   -- save secret
local t = terminalis.load("gh_token")         -- read (nil if missing)
terminalis.store("gh_token", nil)             -- delete
```

> Use this for OAuth tokens, API keys, passwords — anything that should be encrypted at rest.
> **Dev builds:** the current implementation is backed by UserDefaults (no encryption). Replace with `SecItem*` calls before distributing a signed build.

| Constraint | Value |
|---|---|
| Value type | String only |
| Backend | macOS Keychain (UserDefaults in unsigned dev builds — not encrypted) |
| Namespace | `terminalis.plugin.<M.name>.<key>` |

---

### `terminalis.storage.set(key, value)` / `terminalis.storage.get(key)` — **General storage**

Stores **plugin configuration and state** in UserDefaults. Supports strings, numbers, booleans, and tables (serialized as JSON internally). No permission required.

```lua
-- Any scalar type
terminalis.storage.set("merge_method", "squash")
terminalis.storage.set("page_size", 10)
terminalis.storage.set("show_drafts", true)

-- Tables are supported — serialized to JSON automatically
terminalis.storage.set("filters", { state = "open", author = "" })

-- Reading back
local method = terminalis.storage.get("merge_method")   -- "squash"
local size   = terminalis.storage.get("page_size")      -- 10
local filters = terminalis.storage.get("filters")       -- { state="open", author="" }

-- Delete
terminalis.storage.set("page_size", nil)
```

> Use this for user preferences, UI state, cached data — anything non-sensitive.

| Constraint | Value |
|---|---|
| Value types | string, number, boolean, table |
| Backend | UserDefaults |
| Namespace | `terminalis.plugin.<M.name>.storage.<key>` |

**When to use which:**

| Use case | API |
|---|---|
| OAuth token, API key, password | `terminalis.store` / `terminalis.load` |
| User preference (merge method, page size) | `terminalis.storage.set` / `terminalis.storage.get` |
| Cached state (last selected repo, filters) | `terminalis.storage.set` / `terminalis.storage.get` |
| Structured config (multiple settings at once) | `terminalis.storage.set("config", { ... })` |
| Simple string flag from a settings UI control | `terminalis.config.set` / `terminalis.config.get` |

---

### `terminalis.config.set(key, value)` / `terminalis.config.get(key)` — **Settings string store**

Lightweight string-only store designed for values coming from the settings UI (`ui.toggle`, `ui.picker`, `ui.slider`). Backed by UserDefaults under `plugin.<M.name>.<key>`.

**Limitation:** only accepts strings. For numbers, booleans, or tables use `terminalis.storage` instead.

```lua
-- Saving a picker selection
terminalis.config.set("effect", "rain")

-- Reading it back
local effect = terminalis.config.get("effect")  -- "rain" | nil
```

| Constraint | Value |
|---|---|
| Value types | **string only** |
| Backend | UserDefaults |
| Namespace | `plugin.<M.name>.<key>` |

---

### `terminalis.http(method, url, headers?, body?) → status, body | nil, error`

Native HTTPS client. Bypasses browser CORS restrictions — ideal for OAuth token exchange and API calls that WebViews can't make. No permission required.

```lua
local status, body = terminalis.http("GET", "https://api.github.com/repos/owner/repo", {
    ["Authorization"] = "token " .. token,
    ["Accept"]        = "application/vnd.github.v3+json",
})

local status, body = terminalis.http("POST", "https://api.example.com/token", {
    ["Content-Type"] = "application/json",
}, '{"code":"abc"}')

if not status then
    -- body contains the error message
end
```

Security constraints enforced by the host (not bypassable from Lua):
- **HTTPS only** — `http://`, `file://` and all other schemes are blocked.
- **Private network blocking** — loopback (127.x, ::1), RFC-1918 (10.x, 172.16-31.x, 192.168.x), link-local (169.254.x) and single-label hostnames are blocked.
- **Response cap:** 2 MB.
- **Timeout:** 5 s.
- **DNS rebinding:** only the hostname string is checked, not the resolved IP. Avoid pointing to domains you do not control.

> **Note:** `terminalis.http` **blocks the Lua queue** for the duration of the request (up to the timeout). During that time no other plugin can execute hooks. Keep requests fast and avoid calling `http` on every `panel_content()` render — cache results at the module level.

---

### `terminalis.open_url(url)`

Opens an HTTPS URL in the user's default browser via the OS. No shell, no permission required.

```lua
terminalis.open_url("https://github.com/login/oauth/authorize?client_id=…")
```

Only HTTPS URLs are accepted — other schemes are silently ignored.

---

### `terminalis.clipboard(text)`

Writes text to the system clipboard (equivalent to ⌘C on the content).

```lua
local branch = terminalis.active_tab().branch
terminalis.clipboard(branch)
terminalis.notify("Branch copiado: " .. branch)
```

---

### `terminalis.log(msg)`

Writes a debug message to `stderr`. Useful during plugin development — output appears in **Console.app** filtered by process name `Terminalis`, or in the terminal that ran `launch.sh`.

```lua
function M.on_load()
    terminalis.log("plugin loaded, version " .. M.version)
end

function M.on_command(ctx)
    terminalis.log("command: " .. ctx.command .. " in " .. ctx.cwd)
end
```

Messages are prefixed as `[terminalis:<plugin-name>] msg`.

---

### `terminalis.open_file(path)`

Opens a local file as a native Terminalis file tab — identical to opening the file from the explorer. The file appears in the horizontal tab bar of the current session.

```lua
function M.on_command(ctx)
    -- Open the closest README when entering a directory
    local readme = ctx.cwd .. "/README.md"
    terminalis.open_file(readme)
end
```

If the file doesn't exist or the path is invalid, the call is silently ignored.

---

### `terminalis.on_url_callback(fn)`

Registers a Lua function called when `terminalis://callback/<plugin-dir>?params` is opened by the OS (e.g. an OAuth redirect). The host routes the URL to the plugin whose **directory name** matches — plugins cannot intercept each other's callbacks.

```lua
terminalis.on_url_callback(function(params)
    local code = params.code   -- OAuth authorization code
    local state = params.state
    -- exchange code for token, store with terminalis.store, reload panel
end)
```

The callback is automatically unregistered on `M.on_unload()`. Only the last registered function is kept — calling `on_url_callback` again replaces the previous one.

> **URL scheme setup:** The `terminalis://` scheme must be registered with macOS Launch Services for the OS to route the redirect to the app. `launch.sh` handles this automatically for dev builds.

---

### `terminalis.status`

Write to the plugin's slot in the status bar. Each plugin owns one slot, keyed by `M.name`.

```lua
terminalis.status.set("main", { icon = "arrow.triangle.branch", color = "#30D158" })
terminalis.status.set("● recording")
terminalis.status.clear()
```

| Option | Type | Description |
|---|---|---|
| `icon` | string | SF Symbol name |
| `color` | string | Hex `"#RRGGBB"` |

---

### `terminalis.theme()`

Returns the active theme's colors, so a plugin can match the app instead of hardcoding.

```lua
local t = terminalis.theme()
-- t.bg          → "#282A36"   application background
-- t.fg          → "#F8F8F2"   application text
-- t.terminal_bg → "#1E1E1E"   terminal background
-- t.terminal_fg → "#CCCCCC"   terminal text
-- t.accent      → "#BD93F9"   application accent
-- t.is_dark     → true
-- t.ansi        → { 16 terminal colors, 1-indexed: [1]=black … [16]=bright white }
```

Reading it inside `panel_content()` / `background_content()` means the plugin re-themes
itself automatically whenever the user switches theme.

---

### `terminalis.background`

Control the plugin's terminal background overlay (only when `M.terminal_background = true`).

```lua
terminalis.background.show()
terminalis.background.hide()
terminalis.background.toggle()
terminalis.background.reload()      -- re-run background_content() and reload the WebView
terminalis.background.eval(js)      -- run JS inside the overlay's WebView
```

`eval` is the fast path for per-event animation: build the canvas once in
`background_content()`, then push events with `eval` — no Lua re-render, no reload.

```lua
function M.on_keypress(ctx)
    terminalis.background.eval(
        string.format("spawn(%.1f,%.1f)", ctx.cursor_x, ctx.cursor_y))
end
```

---

### `terminalis.panel`

Control the plugin's own side panel (only meaningful when `M.panel` is declared).

```lua
terminalis.panel.reload()   -- re-run panel_content() and redraw
terminalis.panel.show()
terminalis.panel.hide()
terminalis.panel.toggle()
```

---

## Terminal tab management

### `terminalis.tab.new(opts?)`

Opens a new terminal tab in the current session.

```lua
terminalis.tab.new()                                    -- new tab at home
terminalis.tab.new({ cwd = ctx.cwd })                   -- new tab at current dir
terminalis.tab.new({ cwd = "/path/to/dir", name = "api" })
```

| Option | Description |
|---|---|
| `opts.cwd` | Working directory for the new tab. Defaults to the active tab's cwd. |
| `opts.name` | Initial custom name for the tab. |

---

### `terminalis.tab.rename(name, tab_id?)`

Renames a terminal tab. If `tab_id` is omitted, renames the active tab.

Always pass `ctx.tab_id` from hooks to rename the specific tab where the event originated — the active tab may differ if the user switched focus.

```lua
function M.on_cwd_change(ctx)
    terminalis.tab.rename(ctx.cwd:match("[^/]+$") or "~", ctx.tab_id)
end
```

---

### `terminalis.tab.rename_group(name, tab_id?)`

Renames the **group** that contains the given tab (or the active tab's group). Use sparingly — groups are user-defined organizational units, not automatic context. Useful for workflows where the group represents a project and the plugin manages that project's lifecycle.

```lua
-- Only do this if the plugin owns the group lifecycle
terminalis.tab.rename_group("my-project", ctx.tab_id)
```

If the tab is not inside a group (loose tab), this call is silently ignored.

---

### `terminalis.tab.close()`

Closes the active terminal tab.

---

## Opening tabs from plugins

Terminalis supports two kinds of plugin tabs: **webview tabs** (HTML rendered in WKWebView) and **native tabs** (SwiftUI component tree via `M.render_tab`).

### Webview tab

| Parameter | Type | Description |
|---|---|---|
| `html` | `string` | Full HTML document to display in the tab |
| `opts.title` | `string` | Tab label shown in the horizontal tab bar (default: `"Tab"`) |
| `opts.icon` | `string` | SF Symbol name for the tab (default: `"doc.text.magnifyingglass"`) |
| `opts.base_path` | `string` | Absolute directory path for resolving relative assets via `terminalis-file://`. |

### Native tab

Opens a tab that renders `M.render_tab(ctx)` as a native SwiftUI component tree — no HTML, no WebView.

```lua
-- Open the native tab
terminalis.tab.open({ title = "Git Panel", icon = "arrow.triangle.branch", mode = "native" })

-- Force a re-render (call from any hook when data changes)
terminalis.tab.refresh()
```

Implement `M.render_tab(ctx)` returning the same component tree as `M.panel_content()`:

```lua
function M.render_tab(ctx)
  return {
    ui.group({
      ui.label(ctx.branch, { icon = "arrow.triangle.branch", bold = true }),
      ui.row(
        ui.button("Pull", { action = "git_pull", icon = "arrow.down.circle", style = "primary" }),
        ui.button("Push", { action = "git_push", icon = "arrow.up.circle" })
      ),
    }, { title = "Git", icon = "arrow.triangle.branch" }),
  }
end
```

`render_tab` is called on tab open and after `terminalis.tab.refresh()`. The panel and the native tab share the same component vocabulary — you can reuse the same builder function for both.

```lua
-- Open a rich-content tab from a hook or button action
terminalis.tab.open([[
  <!DOCTYPE html>
  <html>
  <body style="background:#1c1c1e; color:#e5e5ea; font-family:system-ui; padding:24px">
    <h2>Git Diff</h2>
    <pre id="content">Loading…</pre>
  </body>
  </html>
]], { title = "Diff", icon = "doc.text.magnifyingglass" })
```

**Key behaviours:**

- Tabs appear in the **horizontal tab bar** attached to the current session tab (same as file tabs).
- Plugin content tabs do **not** trigger `on_cwd_change` hooks — they carry no working directory context.
- They are **transient**: they are not persisted across app restarts.

**Webview bridge — fill-mode panels**

When a panel is declared with `fill = true` (or its first component is a `ui.webview`), the panel's webview can open a new tab by posting a message to the host:

```javascript
window.webkit.messageHandlers.terminalis.postMessage({
  action: "openTab",
  title:  "My Tab",
  html:   "<html>…</html>",
  icon:   "doc.richtext"
});
```

Fill-mode panels also support opening external URLs:

```javascript
window.webkit.messageHandlers.terminalis.postMessage({
  action: "openURL",
  url:    "https://example.com"
});
```

**Webview bridge — file tab views (`PluginTabView`)**

File tab views also have a `terminalis` message handler. It supports one action:

```javascript
window.webkit.messageHandlers.terminalis.postMessage({
  action: "openLocalFile",
  path:   "/absolute/path/to/file.md"
});
```

This opens the file as a native Terminalis file tab (same as opening from the file explorer). The app resolves the path and creates the tab in the current session.

---

## Side panels

Declare `M.panel` to register a resizable column panel on the left or right side of the terminal.

```lua
M.panel = {
    title     = "My Panel",    -- header label
    icon      = "puzzlepiece", -- SF Symbol, used for the toggle button in Settings → Plugins
    width     = 280,           -- default width in points (user can resize)
    min_width = 180,           -- minimum width the user can drag to (default: 180)
    max_width = 600,           -- maximum width the user can drag to (default: 600)
    side      = "right",       -- "right" | "left" -- which side the docked panel column opens on
    -- Optional buttons in the panel header (before the close button):
    header_buttons = {
        { icon = "arrow.clockwise", action = "refresh", tooltip = "Refresh" },
    },
}

function M.panel_content()
    return {
        ui.label("Hello", { bold = true }),
        ui.separator(),
        ui.button("Do something", { action = "do_it", icon = "play" }),
    }
end

function M.do_it()
    terminalis.send("echo hello\n")
    terminalis.panel.reload()
end
```

`panel_content()` is called:
- When the panel is first shown
- After `terminalis.panel.reload()`
- Automatically when the user switches to a different terminal tab

The **open/close toggle** for each panel plugin lives in **Settings → Plugins**, next to that plugin's row (not in the top bar).

---

## Bottom toolbar

Declare `M.toolbar` to add a fixed-height horizontal strip (38px, matching the global header) at the very bottom of the window. By default, a toggle appears in the top bar; set `show_toggle = false` when the plugin controls toolbar visibility from its own UI.

```lua
M.toolbar = {
    title = "My Toolbar",   -- tooltip on the toggle button in the top bar
    icon  = "wrench",       -- SF Symbol for the toggle button
    show_toggle = true,      -- optional; false hides the top-bar toolbar toggle
    bar_position = "right",  -- "right" (default) | "left" -- where the toggle icon sits in the top bar
}

function M.toolbar_content()
    return {
        ui.button("Deploy", { action = "deploy", icon = "paperplane.fill", style = "primary" }),
        ui.label("Branch: main", { color = "#888888" }),
        ui.button("Logs", { action = "show_logs", icon = "doc.text.magnifyingglass" }),
    }
end

function M.deploy()
    terminalis.shell("make deploy")
end
```

### Toolbar layout

Top-level components are arranged in a **horizontal** scroll view (left to right). Use `ui.row` to group related items or add spacing between them.

A single `ui.webview` as the only component fills the entire 38px area — useful for a fully custom HTML toolbar:

```lua
function M.toolbar_content()
    return {
        ui.webview([[
            <div style="display:flex;align-items:center;height:38px;padding:0 12px;gap:8px;font:12px system-ui">
                <button onclick="post('deploy')">Deploy</button>
                <span id="status">Ready</span>
            </div>
        ]]),
    }
end
```

### Toolbar vs panel

| | Bottom toolbar | Side panel |
|---|---|---|
| Layout | Horizontal, fixed 38px height | Vertical, resizable width |
| Resize | Not resizable | User can drag to resize |
| Best for | Quick actions, status summary | Deep content, trees, forms |

### `terminalis.toolbar` API

```lua
terminalis.toolbar.reload()   -- re-render toolbar_content()
terminalis.toolbar.show()     -- show the toolbar
terminalis.toolbar.hide()     -- hide the toolbar
terminalis.toolbar.toggle()   -- toggle visibility
```

---

## File tab views

Register a **custom renderer** for specific file types. When a matching file is open in a tab, a toggle button appears in the tab bar. Clicking it switches between the built-in text editor and the plugin's rendered view — in the same tab.

```lua
M.tab_view = {
    file_types     = { "md", "mdx" },      -- file extensions, lowercase
    toggle_icon    = "doc.richtext.fill",  -- SF Symbol shown in the tab bar
    toggle_tooltip = "Rendered view",      -- tooltip on hover
}

function M.tab_view_content(ctx)
    -- ctx.content    — full text of the file
    -- ctx.file_path  — absolute path to the file
    -- ctx.cwd        — working directory
    -- ctx.branch     — git branch
    -- ctx.dark_mode  — boolean, from the app's active color scheme

    local html = build_html(ctx.content, ctx.dark_mode, ctx.file_path)
    return ui.webview(html)
end
```

### How updates work

```
First toggle (or dark mode change):
  Lua builds full HTML → WKWebView loads CDN scripts → renders

Subsequent text edits (while view is open):
  App injects content via JavaScript — zero Lua, zero network, < 1 ms
```

The app uses two JS contracts with every file tab view webview:

**Plugin-defined (your plugin implements these):**

| Function | Called by host when… | Must return |
|---|---|---|
| `window._updateMD(base64)` | The file content changes while the view is open (fast path — no Lua, no CDN). `base64` is the UTF-8 content encoded as Base64. | — |
| `window._findInPage(query, caseSensitive)` | The user types in the search bar. Highlight all matches in the rendered content. | `{ count: number }` |
| `window._findInPageNav(direction)` | The user presses ↑ (`direction = -1`) or ↓ (`direction = 1`) in the search bar. | `{ index: number, count: number }` |

If your plugin doesn't define `_updateMD`, file edits won't reflect in the view until the next full re-render (dark mode toggle or tab re-open). If it doesn't define `_findInPage` / `_findInPageNav`, the search bar simply shows 0 results while the plugin view is active.

**Host-provided (the host injects these — no action needed):**

| Function | What it does |
|---|---|
| `window.webkit.messageHandlers.terminalis.postMessage({action, ...})` | Bridge to the native layer. See the **Webview bridge** section. |

### Local assets (images and other files)

The file tab view's base URL is set to the **directory of the file being rendered**. Relative paths like `./assets/logo.png` in markdown images resolve against that directory.

For direct `<img src="...">` tags, the app also provides the `terminalis-file://` scheme, which serves local files by absolute path and bypasses WKWebView's `file://` security restrictions:

```javascript
// The host handles this automatically — no plugin code needed.
// If you build your own renderer, use:
img.src = "terminalis-file:///absolute/path/to/image.png";
```

Markdown-style images (`![alt](relative/path.png)`) and raw HTML `<img>` tags with relative `src` attributes both work automatically. Absolute `https://` image URLs also work.

### Links in tab views

| Link type | Behavior |
|---|---|
| `https://` links | Open in the system browser via `NSWorkspace` |
| Relative file links (`[text](other.md)`) | Open as a Terminalis file tab via the `openLocalFile` bridge |
| Anchor links (`#section`) | Scroll within the rendered view |
| Bare URLs in text (autolinks) | **Not** auto-linked — avoids false positives in technical docs |

### Search bar integration

The file search bar (⌘F) integrates with the plugin's rendered view when the plugin is active. The host calls `window._findInPage` and `window._findInPageNav` on the plugin's webview — you don't need to implement anything. If your plugin uses a custom renderer (not `marked.parse`), expose these functions yourself to get search support:

```javascript
window._findInPage = function(query, caseSensitive) {
    // highlight matches in your rendered content
    // return { count: numberOfMatches }
};

window._findInPageNav = function(direction) {  // direction: 1 (next) or -1 (prev)
    // navigate to next/prev match
    // return { index: currentIndex, count: totalMatches }
};
```

### Dark mode

`ctx.dark_mode` is a boolean set by the app's color scheme — no shell calls needed. A **sun/moon toggle** appears in the tab bar whenever the plugin view is active.

```lua
local bg = ctx.dark_mode and "#1c1c1e" or "#ffffff"
local fg = ctx.dark_mode and "#e5e5ea" or "#1c1c1e"
```

---

## Terminal background

Declare `M.terminal_background = true` to register a **full-window transparent overlay**.
It is a `WKWebView` layered above the whole app — effects can draw over the header and
sidebar, not just inside the terminal.

```lua
M.terminal_background = true

function M.background_content()
    return ui.webview([[
        <canvas id="c" style="position:fixed;inset:0;pointer-events:none"></canvas>
        <script>
        let TX=0,TY=0,TW=0,TH=0;
        // Called by the app with the terminal's rect in window CSS pixels
        function setTerminalRect(x,y,w,h){ TX=x; TY=y; TW=w; TH=h; }
        function spawn(x,y){ /* … */ }   // called from Lua via background.eval
        </script>
    ]])
end
```

### `setTerminalRect(x, y, w, h)`

If your script defines this function, the app calls it with the terminal's drawing area
in window CSS pixels — on load and on every layout change (window resize, sidebar drag,
explorer toggle, tab switch). Use it to confine an effect to the terminal:

```js
const bottom = TH > 0 ? TY + TH : cv.height;
if (charY > bottom) return;   // don't draw past the terminal
```

Effects that should fly freely (particles rising over the header) simply ignore it.

> Only **one** background can be visible at a time — activating a second one hides the first.
> The overlay is `allowsHitTesting(false)`, so it never intercepts clicks or keyboard input.

---

## Settings screen

Define `M.settings_content()` and a **sliders button** appears on the plugin's row in
**Settings → Plugins**, opening a modal with your controls. The host owns the modal, the
layout and the rendering — the plugin only returns declarative `ui.*` tables.

```lua
function M.settings_content()
    return {
        ui.picker("Efecto", { options = { "A", "B" }, value = current(), on_change = "set_fx" }),
        ui.separator(),
        ui.slider("Intensidad", { value = 1, min = 0, max = 2, step = 0.1, on_change = "set_n" }),
    }
end

function M.set_fx(ctx)
    terminalis.storage.set("effect", ctx.value)
    terminalis.background.reload()      -- apply immediately
end
```

`settings_content()` is re-evaluated after every action, so the UI reflects the new state
without any manual refresh. Plugins without this function show no config button.

---

## UI DSL

Components are plain Lua tables created with `ui.*` helpers.

### `ui.label(text, opts?)`

```lua
ui.label("Status: OK", { color = "#30D158", bold = true, icon = "checkmark.circle" })
ui.label("Errors", { icon = "xmark.circle", badge = "3" })   -- pill over the icon
```

| Option | Type | Default | Description |
|---|---|---|---|
| `color` | string? | nil | Hex `"#RRGGBB"` text color |
| `bold` | bool | false | Bold weight |
| `icon` | string? | nil | SF Symbol shown before the text |
| `badge` | string? | nil | Pill overlay on the icon |

### `ui.button(text, opts)`

```lua
ui.button("Deploy", { action = "deploy", icon = "paperplane.fill", style = "primary" })
ui.button("Delete", { action = "delete", icon = "trash",           style = "destructive" })
ui.button("Cancel", { action = "cancel", icon = "xmark",           style = "plain" })
ui.button("Pull",   { action = "pull",   icon = "arrow.down.circle" })  -- "default" style
```

`action` is the name of a function on `M`. It is called with a `ctx` table when clicked.

| Option | Type | Default | Description |
|---|---|---|---|
| `action` | string | — | Function on M to call |
| `icon` | string? | nil | SF Symbol |
| `style` | string | `"default"` | `"default"` \| `"primary"` \| `"destructive"` \| `"plain"` |
| `disabled` | bool | false | Visible but not clickable |
| `color` | string? | nil | Hex tint for icon/text (only `style="default"`) |
| `badge` | string? | nil | Pill overlay on the icon |
| `weight` | number | 1 | Relative width inside `ui.row` |

### `ui.list(items, opts?)`

```lua
ui.list({
    { label = "main",    detail = "current", icon = "arrow.triangle.branch" },
    { label = "develop",                     icon = "arrow.triangle.branch" },
}, { on_select = "checkout" })
-- M.checkout(ctx) → ctx.label, ctx.detail
```

**List options:**

| Option | Type | Description |
|---|---|---|
| `on_select` | string? | Function on M called on row tap — `ctx.label` and `ctx.detail` |

**Item fields:**

| Field | Type | Description |
|---|---|---|
| `label` | string | Row title |
| `detail` | string? | Secondary text on the right |
| `icon` | string? | SF Symbol before the label |

### `ui.input(placeholder, opts?)`

```lua
ui.input("Search…", { on_submit = "on_search" })
ui.input("API token", { value = M.token, on_submit = "save_token", secure = true })
-- M.on_search(ctx) → ctx.value
```

| Option | Type | Default | Description |
|---|---|---|---|
| `value` | string? | `""` | Pre-filled text |
| `on_submit` | string? | nil | Function on M called when the user confirms (Return key) |
| `secure` | bool | false | Masks input (password field) |

### `ui.toggle(label, opts?)`

```lua
ui.toggle("Estelas", { value = true, icon = "wind", on_change = "set_trails" })
ui.toggle("markdown-viewer", { value = true, on_change = "toggle_plugin", detail = "v1.2" })
-- M.set_trails(ctx) → ctx.value is "true" | "false"
```

| Option | Type | Default | Description |
|---|---|---|---|
| `value` | bool | false | Initial toggle state |
| `on_change` | string? | nil | Function on M called on change — `ctx.value` is `"true"` or `"false"` |
| `icon` | string? | nil | SF Symbol before the label |
| `detail` | string? | nil | Secondary text on the right (version numbers, status) |

### `ui.slider(label, opts?)`

```lua
ui.slider("Intensidad", { value = 1.0, min = 0.4, max = 2.5, step = 0.1,
                          on_change = "set_intensity" })
-- M.set_intensity(ctx) → ctx.value is the number as a string
```

| Option | Type | Default | Description |
|---|---|---|---|
| `value` | number | 0 | Current position |
| `min` | number | 0 | Left bound |
| `max` | number | 1 | Right bound |
| `step` | number | 0 | Snap increment — `0` means continuous |
| `on_change` | string? | nil | Function on M — `ctx.value` is the number as a string |

### `ui.picker(label, opts?)`

```lua
ui.picker("Efecto", { options = { "Partículas", "Explosión" },
                      value   = "Partículas",
                      on_change = "set_effect" })
-- M.set_effect(ctx) → ctx.value is the chosen option string
```

| Option | Type | Default | Description |
|---|---|---|---|
| `options` | string[] | `{}` | List of choices shown in the dropdown |
| `value` | string? | nil | Currently selected option |
| `on_change` | string? | nil | Function on M — `ctx.value` is the selected string |

Compact dropdown — prefer it over `ui.list` for settings with a single choice.

> **Controls are stateless.** The value you pass is what gets rendered; the `on_change`
> handler is where you persist it (usually with `terminalis.storage.set`). If you don't
> persist, the control reverts on the next render.

### `ui.row(...elements)` — horizontal layout

Groups elements side by side. Each child receives width proportional to its `weight` (default `1`).

```lua
ui.row(
  ui.button("Deploy", { action = "deploy", style = "primary", weight = 2 }),
  ui.button("Logs",   { action = "logs",                      weight = 1 })
)
```

### `ui.group(children, opts?)` — titled section

Groups components visually with an optional header and background.

```lua
ui.group({
  ui.row(
    ui.button("Pull", { action = "pull", style = "primary" }),
    ui.button("Push", { action = "push" })
  ),
  ui.toggle("Watch", { on_change = "toggle_watch", value = M.watching }),
}, {
  title       = "Git",
  icon        = "arrow.triangle.branch",
  collapsible = true,
  collapsed   = false,
})
```

| Option | Default | Description |
|---|---|---|
| `title` | nil | Header label |
| `icon` | nil | SF Symbol next to title |
| `collapsible` | false | Tap header to collapse/expand |
| `collapsed` | false | Initial state when `collapsible = true` |

### `ui.stat(label, value, opts?)` — metric tile

Compact tile for displaying a number or key value.

```lua
ui.row(
  ui.stat("Plugins",    "6", { icon = "puzzlepiece.extension" }),
  ui.stat("Active",     "2", { icon = "checkmark.circle", color = "#30D158" })
)
```

| Option | Type | Default | Description |
|---|---|---|---|
| `icon` | string? | nil | SF Symbol above the value |
| `color` | string? | nil | Hex `"#RRGGBB"` accent color for icon and value |

### `ui.progress(value, opts?)` — progress bar

```lua
ui.progress(0.6, { label = "Indexing…", color = "#0A84FF" })
```

`value` is a number from `0.0` to `1.0`.

| Option | Type | Default | Description |
|---|---|---|---|
| `label` | string? | nil | Text shown above or below the bar |
| `color` | string? | accent | Hex `"#RRGGBB"` fill color |

### `ui.divider(label?)` — labeled separator

```lua
ui.divider("Available plugins")   -- ──── Available plugins ────
ui.divider()                       -- plain divider (same as ui.separator)
```

### `ui.separator()`

Thin horizontal divider.

### `ui.spacer()`

Flexible space — pushes subsequent components to the bottom of the panel.

### `ui.badge(text, opts?)`

```lua
ui.badge("3 errors", { color = "#FF453A" })
```

| Option | Type | Default | Description |
|---|---|---|---|
| `color` | string? | accent | Hex `"#RRGGBB"` background color |

### `ui.webview(html)`

Full HTML rendered in a sandboxed `WKWebView` with JavaScript enabled. CDN resources load via HTTPS. Best for rich content: charts, rendered markup, diagrams.

```lua
return ui.webview([[
    <!DOCTYPE html><html><body style="background:#1c1c1e;color:#e5e5ea;padding:16px">
        <h1>Hello from a plugin</h1>
    </body></html>
]])
```

- When placed as the **sole top-level component**, it fills the entire panel or toolbar area (full height, no scroll wrapper).
- Relative image paths (`src="icon.png"`) resolve against the plugin directory via the `terminalis-file://` scheme.
- External navigation is blocked — HTTPS links open in the system browser.
- Use `terminalis.background.eval(js)` to communicate from Lua into the webview at runtime.

---

## Context menu items

Plugins can inject items into the right-click menu of tabs and groups.

### Static items (always present)

```lua
M.tab_menu_items = {
  { label = "Open in Finder",  icon = "folder",           action = "open_finder" },
  { label = "Copy remote URL", icon = "doc.on.clipboard", action = "copy_remote" },
}

M.group_menu_items = {
  { label = "Deploy group", icon = "arrow.up.circle", action = "deploy_group" },
}
```

### Dynamic items (conditional on tab state)

`M.on_tab_context_menu(ctx)` overrides static items when defined. Return `nil` or `{}` to show no items for that tab.

```lua
function M.on_tab_context_menu(ctx)
  local items = { { label = "Open in Finder", icon = "folder", action = "open_finder" } }
  if ctx.remote_url ~= "" then
    table.insert(items, { label = "Open remote", icon = "safari", action = "open_remote" })
  end
  return items
end

function M.on_group_context_menu(ctx)
  return {
    { label = "Deploy all", icon = "arrow.up.circle.fill", action = "deploy_all" },
  }
end
```

Item fields:

| Field | Type | Description |
|---|---|---|
| `label` | string | Button text |
| `icon` | string? | SF Symbol |
| `action` | string | Function on M to call |
| `separator` | bool? | Insert a `Divider()` instead of a button |
| `destructive` | bool? | Renders in red |
| `disabled` | bool? | Visible but not clickable |

Items are inserted between the built-in actions and the destructive "Close" button.

---

## Tab sidebar buttons

Plugins can render small icon buttons in the trailing area of each tab row in the sidebar. They appear on hover, alongside the `×` close button.

### Static buttons (always shown on hover)

```lua
M.tab_buttons = {
  { icon = "arrow.up.circle.fill", action = "deploy", tooltip = "Deploy", color = "#30D158" },
}
```

### Dynamic buttons (reactive to tab state)

`M.on_tab_render(ctx)` is called on every `on_cwd_change`. Return `nil` to hide buttons for that tab.

```lua
function M.on_tab_render(ctx)
  if ctx.branch == "" then return nil end
  return {
    buttons = {
      {
        icon     = "arrow.up.circle.fill",
        action   = "deploy",
        tooltip  = "Deploy " .. ctx.branch,
        color    = "#30D158",
        disabled = false,
      },
    },
    badge = n_pending > 0 and tostring(n_pending) or nil,
  }
end
```

| Field | Type | Description |
|---|---|---|
| `buttons` | array | Up to 2 buttons per plugin |
| `badge` | string? | Pill overlay on the tab's leading icon |

Button fields: `icon`, `action`, `tooltip`, `color` (hex), `disabled`.

---

## Settings → Plugins

Each installed and active plugin appears with its name, version, author, description, and capability badges.

### Enable / disable

The **toggle** next to each plugin:

- **Off** → calls `M.on_unload()`, hides the panel, clears the status item, removes the plugin from memory. The plugin moves to the **Desactivados** section at the bottom of the list.
- **On** (from Desactivados) → loads the plugin fresh, calls `M.on_load()`, moves it back to the active list.

Disabled plugins are **not loaded on startup** — they consume no memory and run no code until re-enabled.

### Permissions

If a plugin declares `M.permissions`, a permission row appears below its badges for each requested capability. Granting a permission requires **Touch ID / Apple Watch / system password** (via macOS LocalAuthentication). Permissions can be revoked at any time by toggling them off — no authentication required to revoke.

### Recargar

Syncs the active plugin list with the filesystem:

- **New directories** → loaded and enabled (unless previously disabled)
- **Deleted directories** → unloaded and removed
- **Modified `init.lua`** → hot-reloaded automatically (calls `on_unload`, re-executes the file, calls `on_load`). No need to disable/enable the plugin after editing.

Disabled plugins are **not** re-activated by Recargar — their disabled state is preserved.

---

## Performance notes

| Operation | Thread | Typical cost |
|---|---|---|
| Hooks (`on_command`, `on_cwd_change`) | Background Lua queue | Microseconds for simple logic |
| `panel_content()` | Background Lua queue | Depends on `terminalis.shell` calls |
| `tab_view_content()` initial load | Background Lua queue | Depends on file size |
| Tab view text update | JavaScript injection (no Lua) | < 1 ms |
| `terminalis.shell(cmd)` | Spawns configured shell with `-c` | I/O bound |

---

## Limits

Plugins **cannot**:
- Modify the app's core layout (sidebar, tab bar, status bar structure)
- Access other plugins' state
- Run persistent background processes (`terminalis.shell` is synchronous + timeout)
- Render arbitrary native SwiftUI outside their registered slots

---

## Modules

Plugins can split their code across multiple `.lua` files in their own directory using `require`:

```
my-plugin/
  init.lua      ← manifest and hooks
  git.lua       ← git helpers
  ui.lua        ← panel components
  lib/http.lua  ← subdirectory also works
```

```lua
-- init.lua
local git = require("git")
local ui  = require("ui")

M.name = "my-plugin"

function M.panel_content()
  return ui.build(git.status())
end
```

Each module is a regular Lua file that returns a table:

```lua
-- git.lua
local M = {}

function M.status()
  return terminalis.shell("git status --short")
end

function M.branch()
  return terminalis.shell("git branch --show-current"):gsub("\n", "")
end

return M
```

### Sandbox rules

| Rule | Detail |
|---|---|
| Only `.lua` files | `.so` and `.dylib` are rejected |
| Only within the plugin directory | `require("../../other")` fails with an explicit error |
| No external packages | `require("socket")` fails — no LuaRocks available |
| Standard cache | Second `require("git")` returns the cached table, no re-execution |
| `package.loadlib` | `nil` — native libraries cannot be loaded |

---

## Example 1 — Docker monitor (side panel)

```lua
local M = {}
M.name        = "docker-monitor"
M.version     = "1.0"
M.description = "Show running Docker containers in a side panel."

M.panel = { title = "Docker", icon = "shippingbox", width = 260, side = "right" }

function M.on_command(ctx)
    if ctx.command:match("^docker ") then terminalis.panel.reload() end
end

function M.panel_content()
    local raw = terminalis.shell("docker ps --format '{{.Names}}|{{.Status}}' 2>/dev/null")
    if raw == "" then return { ui.label("Docker not running", { color = "#636366" }) } end
    local rows = {}
    for line in raw:gmatch("[^\n]+") do
        local name, status = line:match("([^|]+)|([^|]+)")
        if name then
            table.insert(rows, {
                label  = name,
                detail = status,
                icon   = status:match("^Up") and "checkmark.circle.fill" or "xmark.circle.fill",
            })
        end
    end
    return {
        ui.label("Containers (" .. #rows .. ")", { bold = true }),
        ui.separator(),
        ui.list(rows, { on_select = "tail_logs" }),
        ui.spacer(),
        ui.button("Refresh", { action = "refresh", icon = "arrow.clockwise" }),
    }
end

function M.tail_logs(ctx) terminalis.send("docker logs -f " .. ctx.label .. "\n") end
function M.refresh()      terminalis.panel.reload() end

return M
```

---

## Example 2 — Markdown viewer with Mermaid (file tab view)

```lua
local M = {}
M.name        = "markdown-viewer"
M.version     = "1.0"
M.description = "Rendered Markdown with Mermaid diagram support."

M.tab_view = {
    file_types     = { "md", "markdown" },
    toggle_icon    = "doc.richtext.fill",
    toggle_tooltip = "Rendered view",
}

local function js_escape(s)
    return s:gsub("\\","\\\\"):gsub('"','\\"')
             :gsub("\r",""):gsub("\n","\\n"):gsub("\t","\\t")
end

function M.tab_view_content(ctx)
    local bg  = ctx.dark_mode and "#1c1c1e" or "#ffffff"
    local fg  = ctx.dark_mode and "#e5e5ea" or "#1c1c1e"
    local bg2 = ctx.dark_mode and "#2c2c2e" or "#f2f2f7"
    local tmt = ctx.dark_mode and "dark"    or "default"

    local html =
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        .. '<script src="https://cdn.jsdelivr.net/npm/marked@9/marked.min.js"></script>'
        .. '<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>'
        .. '<style>'
        .. 'body{font-family:-apple-system,sans-serif;font-size:15px;line-height:1.75;'
        .. 'padding:32px 40px;width:100%;background:' .. bg .. ';color:' .. fg .. '}'
        .. 'pre{background:' .. bg2 .. ';padding:16px;border-radius:8px;overflow-x:auto}'
        .. 'code{font-family:Menlo,monospace;font-size:.87em;background:' .. bg2 .. ';padding:2px 6px;border-radius:4px}'
        .. '.mermaid-wrap{background:' .. bg2 .. ';border-radius:12px;padding:24px;'
        .. 'margin:1em 0;display:flex;justify-content:center}'
        .. '</style></head><body><div id="root"></div><script>'
        .. 'mermaid.initialize({startOnLoad:false,theme:"' .. tmt .. '",securityLevel:"loose"});'
        .. 'marked.use({renderer:{code(c,l){'
        .. 'if(l==="mermaid")return\'<div class="mermaid-wrap"><div class="mermaid">\'+c+\'</div></div>\';'
        .. 'return\'<pre><code>\'+c.replace(/&/g,"&amp;").replace(/</g,"&lt;")+\'</code></pre>\'}}});'
        .. 'document.getElementById("root").innerHTML=marked.parse("' .. js_escape(ctx.content) .. '");'
        .. 'mermaid.run({nodes:document.querySelectorAll(".mermaid")});'
        .. '</script></body></html>'

    return ui.webview(html)
end

return M
```

---

## Minimal template

Copy this as your starting point:

```lua
local M = {}

M.name        = "my-plugin"
M.version     = "1.0"
M.author      = ""
M.description = ""

-- Declare permissions for sensitive APIs (requires user approval in Settings → Plugins):
-- M.permissions = { "shell" }

-- Uncomment the slots you need:

-- M.panel = { title = "My Panel", icon = "puzzlepiece", width = 280, side = "right" }
-- M.tab_view = { file_types = {"md"}, toggle_icon = "eye", toggle_tooltip = "Preview" }

function M.on_load()
    terminalis.log("loaded")
    -- terminalis.status.set("ready", { icon = "checkmark.circle" })
    -- Restore session state:
    -- local saved = terminalis.load("my_key")
end

function M.on_unload()
    terminalis.status.clear()
end

-- function M.on_command(ctx) end

-- function M.on_cwd_change(ctx)
--     -- ctx.remote_url contains the git remote origin URL (no shell needed)
--     -- ctx.branch, ctx.cwd, ctx.tab_name also available
-- end

-- function M.on_tab_open(ctx)  end   -- new terminal tab opened
-- function M.on_tab_close(ctx) end   -- terminal tab closed

-- function M.on_file_save(ctx)
--     -- ctx.command = absolute path of the saved file
--     -- terminalis.log("saved: " .. ctx.command)
-- end

-- function M.panel_content()
--     local tab = terminalis.active_tab()
--
--     -- Auto-detect GitHub repo from current directory:
--     -- local repo = tab.remote_url:match("github%.com[:/]([%w%-%./_]+)")
--
--     -- Persist data across sessions:
--     -- terminalis.store("key", "value")
--     -- local v = terminalis.load("key")
--
--     -- Make HTTP requests (no CORS, no shell needed):
--     -- local status, body = terminalis.http("GET", "https://api.example.com/data", {
--     --     ["Authorization"] = "token " .. (terminalis.load("token") or ""),
--     -- })
--
--     -- Always handle the error return when using shell:
--     -- local out, err = terminalis.shell("git status --short")
--     -- if err then return { ui.label("⛔ " .. err) } end
--
--     return { ui.label("Hello from " .. M.name) }
-- end

-- function M.tab_view_content(ctx)
--     return ui.webview("<html><body>" .. ctx.content .. "</body></html>")
-- end

return M
```
