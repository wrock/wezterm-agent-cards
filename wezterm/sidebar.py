#!/usr/bin/env python3
"""WezTerm agent sidebar — curses TUI showing tabs as stacked cards with agent status."""

import curses
import glob
import json
import os
import re
import subprocess
import time

STATUS_FILE = "/tmp/wezterm-agent-status.json"
HOOK_FILE_PATTERN = "/tmp/wezterm-hook-*.json"
HOOK_MAX_AGE = 300  # seconds — ignore stale hook files (5 min, covers long permission waits)
REFRESH_INTERVAL = 0.5  # seconds — matches agent-deck update_interval

# Catppuccin Mocha palette (approximate curses mappings)
PAIR_NORMAL = 1
PAIR_ACTIVE = 2
PAIR_WAITING = 3
PAIR_WORKING = 4
PAIR_HEADER = 5
PAIR_BORDER = 6
PAIR_ACTIVE_BAR = 7

# Status icons
ICONS = {"working": "●", "waiting": "◔", "idle": "○", "inactive": "◌"}

# Lines matching any of these are considered noise (not shown as teaser)
NOISE_PATTERNS = [
    re.compile(r"\$\d"),              # cost indicator: $0,00
    re.compile(r"\d+%"),              # percentage: 25%
    re.compile(r"^\[#"),              # progress bar: [##----]
    re.compile(r"^❯"),               # Claude Code prompt
    re.compile(r"^>\s*$"),            # bare > prompt
    re.compile(r"^Co-Authored"),      # commit trailers
    re.compile(r"\ue0b0|\ue0b1|\ue0b2|\ue0b3"),  # powerline glyphs
    re.compile(r"^\S+@\S+"),          # user@host prompts
    re.compile(r"^[─━─┄]+$"),        # horizontal rules
    re.compile(r"^★ Insight"),        # Claude insight headers
]


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(PAIR_NORMAL, 245, -1)
    curses.init_pair(PAIR_ACTIVE, 255, 236)
    curses.init_pair(PAIR_WAITING, 0, 210)
    curses.init_pair(PAIR_WORKING, 0, 114)
    curses.init_pair(PAIR_HEADER, 75, -1)
    curses.init_pair(PAIR_BORDER, 240, -1)
    curses.init_pair(PAIR_ACTIVE_BAR, 255, -1)  # bright white for active indicator


def read_agent_status():
    """Read agent state JSON written by the WezTerm Lua update-status handler."""
    try:
        with open(STATUS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def read_hook_status():
    """Read per-pane hook status files written by Claude Code hooks.

    Returns dict mapping pane_id (str) to status string.
    Hook data takes priority over agent-deck because hooks fire on actual
    lifecycle events rather than pattern-matching terminal output.
    """
    now = time.time()
    result = {}
    for path in glob.glob(HOOK_FILE_PATTERN):
        try:
            # Extract pane_id from filename: /tmp/wezterm-hook-7.json → "7"
            basename = os.path.basename(path)
            pane_id = basename.replace("wezterm-hook-", "").replace(".json", "")
            with open(path, "r") as f:
                data = json.load(f)
            ts = data.get("ts", 0)
            if now - ts < HOOK_MAX_AGE:
                result[pane_id] = data.get("status", "inactive")
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    return result


def read_wezterm_tabs():
    """Get tab/pane list from wezterm CLI."""
    try:
        result = subprocess.run(
            ["wezterm", "cli", "list", "--format", "json"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return []


def is_noise(line):
    """Check if a line is terminal noise (prompts, status bars, etc.)."""
    return any(p.search(line) for p in NOISE_PATTERNS)


def get_pane_teaser(pane_id):
    """Fetch last meaningful line from a pane via wezterm CLI."""
    try:
        result = subprocess.run(
            ["wezterm", "cli", "get-text", "--pane-id", str(pane_id)],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout:
            # Walk lines in reverse to find last meaningful content
            for line in reversed(result.stdout.splitlines()):
                stripped = line.strip()
                if len(stripped) > 2 and not is_noise(stripped):
                    return stripped
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def project_name_from_cwd(cwd):
    """Extract last folder component from a CWD path.

    If the last component is a generic webroot name (docroot, web, public, html),
    use the parent folder instead (e.g. reiwag/docroot → reiwag).
    """
    if not cwd:
        return "~"
    path = cwd.rstrip("/")
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    name = os.path.basename(path)
    if name in ("docroot", "web", "public", "html"):
        name = os.path.basename(os.path.dirname(path)) or name
    return name or "~"


def build_tab_list(panes_info, agent_status, hook_status, my_tab_id):
    """Build a deduplicated list of tabs with their main pane info and agent state.

    my_tab_id: the tab this sidebar instance lives in (= the currently visible tab).
    hook_status: dict from read_hook_status(), takes priority over agent_status.
    """
    tabs = {}
    for pane in panes_info:
        tab_id = pane.get("tab_id", 0)
        pane_id = pane.get("pane_id", 0)
        title = pane.get("title", "")
        cwd = pane.get("cwd", "")

        # Skip utility panes (sidebar, broot, etc.)
        if "agent-sidebar" in title or "broot" in title:
            continue

        # Keep the first non-sidebar pane per tab
        if tab_id not in tabs:
            pane_key = str(pane_id)
            # Hook status (from Claude Code hooks) takes priority over
            # agent-deck status (from terminal pattern matching)
            if pane_key in hook_status:
                status = hook_status[pane_key]
            else:
                status_info = agent_status.get(pane_key, {})
                status = status_info.get("status", "inactive")
            tabs[tab_id] = {
                "tab_id": tab_id,
                "pane_id": pane_id,
                "cwd": cwd,
                "project": project_name_from_cwd(cwd),
                "status": status,
                "is_active_tab": tab_id == my_tab_id,
            }

    # Sort by tab_id (creation order) and assign sequential indices
    sorted_tabs = sorted(tabs.values(), key=lambda t: t["tab_id"])
    for i, tab in enumerate(sorted_tabs):
        tab["tab_index"] = i
    return sorted_tabs


def draw_card(win, y, x, width, tab, is_selected):
    """Draw a single tab card with teaser line."""
    h = win.getmaxyx()[0]
    if y + 3 >= h or width < 8:
        return

    idx_str = str(tab["tab_index"] + 1)
    project = tab["project"]
    teaser = tab.get("last_line", "")

    # Determine color pair
    status = tab["status"]
    if status == "waiting":
        pair = PAIR_WAITING
    elif status == "working":
        pair = PAIR_WORKING
    elif is_selected:
        pair = PAIR_ACTIVE
    else:
        pair = PAIR_NORMAL

    attr = curses.color_pair(pair)
    if is_selected:
        attr |= curses.A_BOLD

    # Content area is between the full-block borders (2 chars used for L+R)
    content_w = width - 2
    name_space = content_w - len(idx_str) - 3
    if name_space < 1:
        name_space = 1
    truncated = project[:name_space].ljust(name_space)
    title_content = f" {idx_str}  {truncated}"
    title_content = title_content[:content_w].ljust(content_w)

    # Teaser line: dimmed, truncated to content width
    teaser_content = " " + teaser[:content_w - 2] + " " if teaser else ""
    teaser_content = teaser_content[:content_w].ljust(content_w)
    teaser_attr = curses.color_pair(PAIR_NORMAL) | curses.A_DIM
    if status in ("waiting", "working"):
        teaser_attr = attr | curses.A_DIM

    try:
        bar_attr = curses.color_pair(PAIR_ACTIVE_BAR) | curses.A_BOLD
        bar_char = "█"

        # Row 0: blank spacer row with borders
        spacer = " " * content_w
        if is_selected:
            win.addstr(y, x, bar_char, bar_attr)
            win.addnstr(y, x + 1, spacer, content_w, attr)
            win.addstr(y, x + width - 1, bar_char, bar_attr)
        else:
            win.addnstr(y, x, " " * width, width, attr)

        # Row 1: title with borders
        win.addstr(y + 1, x, bar_char if is_selected else " ", bar_attr if is_selected else attr)
        win.addnstr(y + 1, x + 1, title_content, content_w, attr)
        win.addstr(y + 1, x + width - 1, bar_char if is_selected else " ", bar_attr if is_selected else attr)

        # Row 2: teaser with borders
        win.addstr(y + 2, x, bar_char if is_selected else " ", bar_attr if is_selected else attr)
        win.addnstr(y + 2, x + 1, teaser_content, content_w, teaser_attr)
        win.addstr(y + 2, x + width - 1, bar_char if is_selected else " ", bar_attr if is_selected else attr)

        # Row 3: thin separator line between cards
        if y + 3 < h:
            sep_attr = curses.color_pair(PAIR_BORDER)
            if is_selected:
                win.addstr(y + 3, x, bar_char, bar_attr)
                win.addnstr(y + 3, x + 1, "▁" * content_w, content_w, sep_attr)
                win.addstr(y + 3, x + width - 1, bar_char, bar_attr)
            else:
                win.addnstr(y + 3, x, "▁" * width, width, sep_attr)
    except curses.error:
        pass


def draw_header(win, width):
    """Draw the sidebar header."""
    h = win.getmaxyx()[0]
    if h < 1 or width < 4:
        return
    attr = curses.color_pair(PAIR_HEADER) | curses.A_BOLD
    title = " Tabs"[:width].ljust(width)
    try:
        win.addnstr(0, 0, title, width, attr)
    except curses.error:
        pass


def main(stdscr):
    curses.curs_set(0)
    stdscr.timeout(int(REFRESH_INTERVAL * 1000))
    stdscr.keypad(True)
    curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    init_colors()

    selected = 0
    my_pane_id = int(os.environ.get("WEZTERM_PANE", -1))
    CARD_START_Y = 2
    CARD_HEIGHT = 4

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 3 or w < 6:
            stdscr.addnstr(0, 0, "too small", min(9, w))
            stdscr.refresh()
            key = stdscr.getch()
            if key == ord("q"):
                break
            continue

        # Read data from both sources
        agent_status = read_agent_status()
        hook_status = read_hook_status()
        panes_info = read_wezterm_tabs()

        # Resolve our own tab_id from our pane_id
        my_tab_id = None
        if my_pane_id >= 0 and panes_info:
            for p in panes_info:
                if p.get("pane_id") == my_pane_id:
                    my_tab_id = p.get("tab_id")
                    break
            # Auto-exit if we're the only pane left in our tab
            if my_tab_id is not None:
                has_sibling = any(
                    p.get("tab_id") == my_tab_id and p.get("pane_id") != my_pane_id
                    for p in panes_info
                )
                if not has_sibling:
                    break

        tabs = build_tab_list(panes_info, agent_status, hook_status, my_tab_id)

        if not tabs:
            msg = " No tabs"[:w]
            stdscr.addnstr(1, 0, msg, w, curses.color_pair(PAIR_NORMAL))
            stdscr.refresh()
            key = stdscr.getch()
            if key == ord("q"):
                break
            continue

        # Fetch teasers for each tab's main pane
        for tab in tabs:
            tab["last_line"] = get_pane_teaser(tab["pane_id"])

        # Sync selection to the currently active tab
        for i, t in enumerate(tabs):
            if t["is_active_tab"]:
                selected = i
                break

        selected = max(0, min(selected, len(tabs) - 1))

        # Draw
        draw_header(stdscr, w)
        card_y = CARD_START_Y
        for i, tab in enumerate(tabs):
            is_selected = i == selected
            draw_card(stdscr, card_y, 0, w, tab, is_selected)
            card_y += CARD_HEIGHT
            if card_y >= h - 1:
                break

        stdscr.refresh()

        # Input handling
        key = stdscr.getch()
        if key == ord("q"):
            break
        elif key == curses.KEY_UP or key == ord("k"):
            selected = max(0, selected - 1)
        elif key == curses.KEY_DOWN or key == ord("j"):
            selected = min(len(tabs) - 1, selected + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            if 0 <= selected < len(tabs):
                tab_idx = tabs[selected]["tab_id"]
                try:
                    subprocess.run(
                        ["wezterm", "cli", "activate-tab", "--tab-id", str(tab_idx)],
                        timeout=2, capture_output=True,
                    )
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass
        elif key == curses.KEY_MOUSE:
            try:
                _, _, my, _, bstate = curses.getmouse()
                if my >= CARD_START_Y:
                    clicked = (my - CARD_START_Y) // CARD_HEIGHT
                    if 0 <= clicked < len(tabs):
                        selected = clicked
                        if bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED):
                            tab_idx = tabs[selected]["tab_id"]
                            try:
                                subprocess.run(
                                    ["wezterm", "cli", "activate-tab", "--tab-id", str(tab_idx)],
                                    timeout=2, capture_output=True,
                                )
                            except (subprocess.TimeoutExpired, FileNotFoundError):
                                pass
            except curses.error:
                pass
        elif key == curses.KEY_RESIZE:
            curses.update_lines_cols()


if __name__ == "__main__":
    os.environ.setdefault("ESCDELAY", "25")
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
