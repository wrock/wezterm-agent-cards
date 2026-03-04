---------------------------------------------------------------------------
-- WezTerm Agent Cards — sidebar module
-- Usage in wezterm.lua:
--   local agent_cards = dofile(os.getenv('HOME') .. '/.claude/plugins/wezterm-agent-cards/wezterm/init.lua')
--   agent_cards.apply_to_config(config, { agent_deck = agent_deck, sidebar_cols = 26 })
---------------------------------------------------------------------------
local wezterm = require('wezterm')

local M = {}

---------------------------------------------------------------------------
-- Resolve paths relative to this file
-- Note: WezTerm's Lua sandbox strips the `debug` library, so we derive
-- the plugin directory from $HOME instead of debug.getinfo().
---------------------------------------------------------------------------
local PLUGIN_DIR     = os.getenv('HOME') .. '/.claude/plugins/wezterm-agent-cards'
local SIDEBAR_CMD    = PLUGIN_DIR .. '/wezterm/sidebar.py'
local STATUS_FILE    = '/tmp/wezterm-agent-status.json'

---------------------------------------------------------------------------
-- Helper: extract project folder from pane cwd
---------------------------------------------------------------------------
local DEFAULT_WEBROOT_NAMES = { docroot = true, web = true, public = true, html = true }

local function project_name(pane_info, webroot_names)
  local cwd = pane_info.current_working_dir
  if not cwd then return '~' end
  local path = type(cwd) == 'string' and cwd or cwd.file_path
  if not path then return '~' end
  path = path:gsub('/$', '')
  local name = path:match('([^/]+)$') or path
  if webroot_names[name] then
    local parent = path:match('([^/]+)/[^/]+$')
    if parent then name = parent end
  end
  return name
end

---------------------------------------------------------------------------
-- Spawn sidebar in the current tab's left pane
---------------------------------------------------------------------------
local function spawn_sidebar(window, tab_pane, sidebar_cols)
  local sidebar_pane = tab_pane:split({
    direction = 'Left',
    size      = sidebar_cols / (sidebar_cols + 120),
    args      = { 'python3', SIDEBAR_CMD },
    set_environment_variables = {
      TERM = 'xterm-256color',
    },
  })

  if sidebar_pane then
    sidebar_pane:inject_output('\x1b]0;agent-sidebar\x07')
  end

  tab_pane:activate()
end

---------------------------------------------------------------------------
-- apply_to_config: register events and keybindings
---------------------------------------------------------------------------
function M.apply_to_config(config, opts)
  opts = opts or {}
  local agent_deck    = opts.agent_deck
  local sidebar_cols  = opts.sidebar_cols or 26
  local hide_tab_bar  = opts.hide_tab_bar ~= false  -- default true
  local webroot_names = opts.webroot_names or DEFAULT_WEBROOT_NAMES

  -- Convert list to set if user passed an array
  if webroot_names[1] then
    local set = {}
    for _, v in ipairs(webroot_names) do set[v] = true end
    webroot_names = set
  end

  -- Hide native tab bar (sidebar replaces it)
  if hide_tab_bar then
    config.enable_tab_bar = false
  end

  -------------------------------------------------------------------------
  -- Write agent state to JSON for the sidebar to read
  -------------------------------------------------------------------------
  if agent_deck then
    wezterm.on('update-status', function(window, pane)
      local mux_win = window:mux_window()
      local tabs = mux_win:tabs()
      local data = {}

      for ti, tab in ipairs(tabs) do
        local tab_index = ti - 1

        for _, p in ipairs(tab:panes()) do
          local pane_id = p:pane_id()
          local ok, state = pcall(function()
            return agent_deck.get_agent_state(pane_id)
          end)
          local status = 'inactive'
          if ok and state and state.status then
            status = state.status
          end

          data[tostring(pane_id)] = {
            status    = status,
            tab_index = tab_index,
            cwd       = project_name({ current_working_dir = p:get_current_working_dir() }, webroot_names),
          }
        end
      end

      local tmp = STATUS_FILE .. '.tmp'
      local f = io.open(tmp, 'w')
      if f then
        local parts = {}
        for k, v in pairs(data) do
          table.insert(parts, string.format(
            '"%s":{"status":"%s","tab_index":%d,"cwd":"%s"}',
            k, v.status, v.tab_index, (v.cwd:gsub('"', '\\"'))
          ))
        end
        f:write('{' .. table.concat(parts, ',') .. '}')
        f:close()
        os.rename(tmp, STATUS_FILE)
      end
    end)
  end

  -------------------------------------------------------------------------
  -- gui-startup: create initial tab with sidebar
  -------------------------------------------------------------------------
  wezterm.on('gui-startup', function(cmd)
    local tab, main_pane, window = wezterm.mux.spawn_window(cmd or {})
    spawn_sidebar(window, main_pane, sidebar_cols)
  end)

  -------------------------------------------------------------------------
  -- Custom SpawnTab action: new tab + auto-sidebar
  -------------------------------------------------------------------------
  local spawn_tab_with_sidebar = wezterm.action_callback(function(window, pane)
    window:perform_action(wezterm.action.SpawnTab('CurrentPaneDomain'), pane)

    wezterm.time.call_after(0.1, function()
      local mux_win = window:mux_window()
      local active_tab = mux_win:active_tab()
      if active_tab then
        local panes = active_tab:panes()
        if #panes == 1 then
          spawn_sidebar(window, panes[1], sidebar_cols)
        end
      end
    end)
  end)

  -------------------------------------------------------------------------
  -- Keybindings
  -------------------------------------------------------------------------
  config.keys = config.keys or {}

  local sidebar_keys = {
    -- Tabs: custom spawn with sidebar
    { key = 't', mods = 'CTRL|SHIFT', action = spawn_tab_with_sidebar },
    { key = 'w', mods = 'CTRL|SHIFT', action = wezterm.action.CloseCurrentTab({ confirm = true }) },
    { key = 'UpArrow',   mods = 'CTRL|SHIFT', action = wezterm.action.ActivateTabRelative(-1) },
    { key = 'DownArrow', mods = 'CTRL|SHIFT', action = wezterm.action.ActivateTabRelative(1) },
    -- Quick jump Alt+1..9
    { key = '1', mods = 'ALT', action = wezterm.action.ActivateTab(0) },
    { key = '2', mods = 'ALT', action = wezterm.action.ActivateTab(1) },
    { key = '3', mods = 'ALT', action = wezterm.action.ActivateTab(2) },
    { key = '4', mods = 'ALT', action = wezterm.action.ActivateTab(3) },
    { key = '5', mods = 'ALT', action = wezterm.action.ActivateTab(4) },
    { key = '6', mods = 'ALT', action = wezterm.action.ActivateTab(5) },
    { key = '7', mods = 'ALT', action = wezterm.action.ActivateTab(6) },
    { key = '8', mods = 'ALT', action = wezterm.action.ActivateTab(7) },
    { key = '9', mods = 'ALT', action = wezterm.action.ActivateTab(8) },
    -- Split panes
    { key = 'd', mods = 'CTRL|SHIFT', action = wezterm.action.SplitHorizontal({ domain = 'CurrentPaneDomain' }) },
    { key = 'e', mods = 'CTRL|SHIFT', action = wezterm.action.SplitVertical({ domain = 'CurrentPaneDomain' }) },
    -- Focus panes
    { key = 'LeftArrow',  mods = 'ALT|SHIFT', action = wezterm.action.ActivatePaneDirection('Left') },
    { key = 'RightArrow', mods = 'ALT|SHIFT', action = wezterm.action.ActivatePaneDirection('Right') },
  }

  for _, binding in ipairs(sidebar_keys) do
    table.insert(config.keys, binding)
  end
end

return M
