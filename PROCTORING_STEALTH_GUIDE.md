# Stealth Mode Guide

> **Note:** Parts of this document predate the current hide-by-default stealth
> mode, in which the window is fully hidden during a session and `Alt+Z` produces
> a click-through peek that auto-hides. Prefer the behavior described in the
> [README](README.md) for current defaults. The guidance on focus discipline and
> window control below still applies.

## Overview

Nyx is designed to be operated entirely through global hotkeys, without the
overlay window ever taking focus. This guide explains how the stealth features
work and how to operate the overlay during a monitored or recorded session.

## Stealth features

### Focus-free visibility

The window is shown and hidden with `SW_SHOWNOACTIVATE` rather than `SW_SHOW`.
This shows the window without activating it, so showing or hiding the overlay
does not change which window has focus.

### Click-through ghost mode (`Alt+X`)

Ghost mode applies `WS_EX_TRANSPARENT` (combined with `WS_EX_LAYERED`) so clicks
pass through the overlay to the window underneath. The overlay cannot
accidentally gain focus by being clicked while ghost mode is active.

### Screen-capture exclusion

The window uses the Windows `WDA_EXCLUDEFROMCAPTURE` API, so it does not appear
in screen recordings or shared screens (OBS, Camtasia, Teams, Zoom, and capture
APIs that honor display affinity).

### Global hotkeys

All actions are available through system-wide hotkeys that work from any
application. No clicking or focusing of the overlay is required. See the
[hotkey table](README.md#hotkeys) in the README for the full list.

## Operating during a session

### Do

- Keep the monitored application in focus at all times.
- Use global hotkeys exclusively to control the overlay.
- Use `Alt+Z` to show or hide the overlay as needed.
- Reposition the window with `Alt+Left/Right` and `Alt+I/J` (20px per press).
- Scroll content with `Alt+Up/Down` (hold for continuous scrolling).
- Use `Alt+1` for the lowest opacity when you want the overlay least visible.

### Avoid

- Clicking on the overlay window.
- Dragging, resizing, minimizing, or maximizing it with the mouse.
- Using `Alt+Tab` to switch to the overlay.
- Pressing `Alt+X` unintentionally during a session, which would disable ghost
  mode and make the window clickable again.

## Window control reference

Window and transparency:

- `Alt+Shift+S`: enable stealth mode.
- `Alt+Z`: toggle visibility (no focus change).
- `Alt+X`: toggle ghost mode (click-through).
- `Alt+Left` / `Alt+Right`: move left / right (20px).
- `Alt+I` / `Alt+J`: move up / down (20px).
- `Alt+1` / `Alt+2` / `Alt+3`: set opacity to 40% / 70% / 100%.

Scrolling:

- `Alt+Up` / `Alt+Down`: continuous scroll up / down while held.

See the README for AI, vision, and audio hotkeys.

## Technical details

| Feature | Implementation |
|---|---|
| Focus-free show | `SW_SHOWNOACTIVATE` (shows without activation) instead of `SW_SHOW` |
| Ghost mode | `WS_EX_TRANSPARENT` plus `WS_EX_LAYERED` for click-through and transparency |
| Capture exclusion | `WDA_EXCLUDEFROMCAPTURE` excludes the window from screen capture |
| Taskbar/Alt+Tab | `WS_EX_TOOLWINDOW` keeps the window out of the taskbar and switcher |

## Testing your setup

Before a session where this matters:

1. Confirm every hotkey responds.
2. Verify the opacity levels with `Alt+1/2/3`.
3. Confirm ghost mode is active (`Alt+X`) and that clicks pass through.
4. Record your screen to confirm the overlay is excluded from capture.
5. Rehearse the workflow so you can operate it without looking away.

## Troubleshooting

**Hotkeys not working**

- Restart the application.
- Ensure no other software has registered the same global hotkeys.

**Window gaining focus**

- Use `Alt+Z` rather than clicking to show or hide.
- Confirm ghost mode is enabled with `Alt+X`.

**Visible in recordings**

- Confirm the capture-exclusion API applied at startup.
- Restart the application if it did not.
- Lower the opacity as a fallback.

## Responsible use

Stealth Mode is provided to support your own work and study. It is your
responsibility to comply with the laws, regulations, and policies that apply to
you, and to review the rules of any exam or interview provider before use. Use
Nyx to augment your own knowledge and preparation, not to misrepresent your
abilities.
