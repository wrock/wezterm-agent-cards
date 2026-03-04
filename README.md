# WezTerm Agent Cards

A Claude Code plugin that adds a curses-based sidebar to WezTerm showing your
Claude Code sessions as stacked status cards with real-time state tracking.

Strongly inspired by [CMUX](https://github.com/manaflow-ai/cmux), a native
macOS terminal that surfaces AI agent status through vertical tabs and
notification rings. WezTerm Agent Cards brings the same idea to Linux (and
anywhere WezTerm runs) — using Claude Code hooks, a Python TUI, and a thin
Lua module instead of a dedicated terminal app.

![status: working](https://img.shields.io/badge/status-working-brightgreen)
![platform: linux](https://img.shields.io/badge/platform-linux%20%7C%20macOS-blue)
![license: MIT](https://img.shields.io/badge/license-MIT-yellow)

## What it does

- Spawns a narrow sidebar pane in every WezTerm tab
- Shows each tab as a card with project name and last output line
- Cards change color based on Claude Code status:
  - **Green** — working (running tools, generating)
  - **Pink** — waiting (permission dialog, finished, notification)
  - **Dim** — inactive (no Claude session)
- Click a card or press Enter to switch tabs
- Auto-exits when its sibling pane closes

## How it works

The plugin has three layers:

1. **Hooks** (`hooks/`) — Claude Code lifecycle hooks write per-pane status to
   `/tmp/wezterm-hook-<pane_id>.json`. Subagent start/stop events maintain a
   counter to prevent subagent activity from clobbering the main status.

2. **Lua module** (`wezterm/init.lua`) — Registers WezTerm events to spawn the
   sidebar in new tabs, bridge agent-deck state to a JSON file, and add
   keybindings for tab/pane navigation.

3. **Python TUI** (`wezterm/sidebar.py`) — Curses app that reads both status
   sources and renders the card stack with click/keyboard navigation.

### CMUX vs. Agent Cards

| | CMUX | Agent Cards |
|---|---|---|
| Platform | macOS only | Linux, macOS, anywhere WezTerm runs |
| Terminal | Custom (libghostty) | WezTerm split pane |
| Rendering | Native AppKit | Python curses |
| Agent detection | Terminal escape sequences + CLI hooks | Claude Code plugin hooks + agent-deck |
| Extra features | Built-in browser, workspace persistence | Lightweight, no extra dependencies |

Both solve the same problem: when you run multiple Claude Code sessions in
parallel, you need to see at a glance which ones need your attention.

## Requirements

- [WezTerm](https://wezfurlong.org/wezterm/)
- [agent-deck](https://github.com/Eric162/wezterm-agent-deck) WezTerm plugin
- Python 3 (for the sidebar TUI)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

## Installation

### 1. Clone the plugin

```bash
mkdir -p ~/.claude/plugins
git clone https://github.com/YOURUSER/wezterm-agent-cards.git \
  ~/.claude/plugins/wezterm-agent-cards
```

### 2. Enable the plugin

Add to `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "wezterm-agent-cards@wezterm-agent-cards": true
  }
}
```

### 3. Load the Lua module in your wezterm.lua

```lua
local wezterm = require('wezterm')
local config  = wezterm.config_builder()

-- Load agent-deck (required for status bridge)
local agent_deck = wezterm.plugin.require(
  'https://github.com/Eric162/wezterm-agent-deck'
)

-- Load agent cards sidebar
local agent_cards = dofile(
  os.getenv('HOME') .. '/.claude/plugins/wezterm-agent-cards/wezterm/init.lua'
)

-- Your appearance config ...

-- Apply sidebar
agent_cards.apply_to_config(config, {
  agent_deck   = agent_deck,
  sidebar_cols = 26,
})

-- Apply agent-deck (detection only, sidebar handles rendering)
agent_deck.apply_to_config(config, {
  update_interval = 500,
  notifications   = { enabled = false },
  tab_title       = { enabled = false },
})

return config
```

### 4. Restart Claude Code and WezTerm

- In Claude Code, run `/hooks` to verify the plugin's 8 hooks are registered.
- Open WezTerm — the sidebar should appear in the initial tab.

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `agent_deck` | `nil` | Agent-deck plugin reference. Required for the status bridge. |
| `sidebar_cols` | `26` | Sidebar width in terminal columns. |
| `hide_tab_bar` | `true` | Disable WezTerm's native tab bar (the sidebar replaces it). |
| `webroot_names` | `{docroot, web, public, html}` | Folder names to skip when extracting project name from CWD. |

## Keybindings

| Key | Action |
|-----|--------|
| Ctrl+Shift+T | New tab with sidebar |
| Ctrl+Shift+W | Close tab |
| Ctrl+Shift+Up/Down | Previous/next tab |
| Alt+1..9 | Jump to tab by number |
| Ctrl+Shift+D | Split horizontal |
| Ctrl+Shift+E | Split vertical |
| Alt+Shift+Left/Right | Focus left/right pane |

## Plugin structure

```
wezterm-agent-cards/
├── .claude-plugin/
│   └── plugin.json        # Claude Code plugin manifest
├── hooks/
│   ├── hooks.json         # 8 lifecycle hooks (auto-registered)
│   └── status-hook.sh     # Per-pane status writer + subagent counter
├── wezterm/
│   ├── init.lua           # Lua module for WezTerm config
│   └── sidebar.py         # Python curses TUI
└── README.md
```

## How status detection works

The sidebar merges two data sources, with hooks taking priority:

1. **Claude Code hooks** (primary) — fire on actual lifecycle events:
   - `UserPromptSubmit` → working
   - `PostToolUse` → working (with sticky guard when subagents active)
   - `PermissionRequest` / `Notification` / `Stop` → waiting
   - `SubagentStart` / `SubagentStop` → counter management
   - `SessionEnd` → cleanup

2. **agent-deck** (fallback) — pattern-matches terminal output to detect agent
   state. Less reliable but provides status when hooks haven't fired yet.

### Sticky "waiting" rule

When subagents are active, `PostToolUse`'s "working" state cannot overwrite
"waiting". This prevents a subagent's tool use from hiding a permission dialog
on the main agent. Only `UserPromptSubmit` (with force flag) or a new
waiting/cleanup event can clear it.

## Acknowledgements

- [CMUX](https://github.com/manaflow-ai/cmux) by Manaflow AI — the original
  inspiration for surfacing agent status in a terminal sidebar
- [agent-deck](https://github.com/Eric162/wezterm-agent-deck) — WezTerm plugin
  for AI agent detection that provides the fallback status data

## License

MIT
