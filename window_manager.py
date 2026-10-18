# --- window_manager.py ---
# This module contains the core logic for managing the application's desktop window.
# Its primary responsibility is to apply the necessary settings to prevent the window
# from being captured by screen recording or sharing software (e.g., Teams, Zoom, OBS).
# This is the "stealth" feature of the Shadow application.

import os
import ctypes
import ctypes.wintypes as wintypes
import webview
import time
import tkinter as tk
import platform
from typing import Optional
from threading import Thread, Timer
from dotenv import dotenv_values

# --- Scroll Configuration ---
# Configurable via .env — controls Alt+Up/Down scroll behaviour
# SCROLL_SPEED_PX: pixels per scroll tick (higher = faster). Default: 200
# SCROLL_INTERVAL_MS: milliseconds between ticks while key is held. Default: 50
# SCREEN_SHARE_SCAN_INTERVAL_S: seconds between screen-share indicator sweeps.
#
# Read the .env file directly rather than relying on os.environ: nothing in the
# app calls load_dotenv(), and neither pydantic-settings nor dotenv_values
# exports to the process environment, so these keys never reached os.environ.
# Same file and relative path as core/config.py. Precedence is unchanged:
# real environment variable > .env file > built-in default.
_ENV_FILE_VALUES = dotenv_values(".env")


def _env_setting(name: str, default, minimum, cast=int):
    """Resolve a numeric setting, falling back to the default when missing or malformed.

    Never raises: this module is imported from main.py before any UI exists, so a
    typo in .env must not take the whole app down.
    """
    raw = os.environ.get(name) or _ENV_FILE_VALUES.get(name)
    if not raw:
        return default
    try:
        value = cast(str(raw).strip())
    except (TypeError, ValueError):
        print(f"⚠️ Invalid {name}={raw!r} in .env, using default {default}")
        return default
    return value if value >= minimum else minimum


SCROLL_AMOUNT_PX = _env_setting("SCROLL_SPEED_PX", 200, 1)
SCROLL_INTERVAL_MS = _env_setting("SCROLL_INTERVAL_MS", 50, 10)
SCREEN_SHARE_SCAN_INTERVAL_S = _env_setting("SCREEN_SHARE_SCAN_INTERVAL_S", 1.0, 0.2, float)


def get_peek_seconds() -> float:
    """Seconds an Alt+Z peek stays visible before auto-hiding (0 disables).

    Read dynamically so tests and runtime changes are honoured. Never raises.
    """
    return _env_setting("STEALTH_PEEK_SECONDS", 10.0, 0.0, float)

# --- Win32 API Constants ---
# These flags are used with the SetWindowDisplayAffinity function.
# WDA_EXCLUDEFROMCAPTURE is a comprehensive flag that prevents the window from being
# captured by most common methods, rendering it as a black rectangle in recordings.
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011
SW_HIDE = 0
SW_SHOW = 5
SW_SHOWNOACTIVATE = 4  # Show window without giving it focus - crucial for stealth

# --- Win32 Function Loading ---
# We use the ctypes library to load functions directly from user32.dll, a core
# Windows library for UI management. This gives us low-level control over the window.

# Load the user32 library
_user32 = ctypes.windll.user32

# Define the function signature for SetWindowDisplayAffinity
# This tells ctypes what kind of arguments the function expects (a window handle and a flag)
# and what it returns (a boolean indicating success).
_user32.SetWindowDisplayAffinity.restype  = wintypes.BOOL
_user32.SetWindowDisplayAffinity.argtypes = (wintypes.HWND, wintypes.DWORD)

# Define the function signature for FindWindowW
# This is a fallback method to find a window by its title if the primary method fails.
_user32.FindWindowW.restype               = wintypes.HWND
_user32.FindWindowW.argtypes              = (wintypes.LPCWSTR, wintypes.LPCWSTR)

# Window-title access (used to scrub the native title while hidden so a
# hidden-window enumeration scan cannot match the name "Shadow")
_user32.GetWindowTextLengthW.argtypes     = (wintypes.HWND,)
_user32.GetWindowTextLengthW.restype      = ctypes.c_int
_user32.GetWindowTextW.argtypes           = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_user32.GetWindowTextW.restype            = ctypes.c_int
_user32.SetWindowTextW.argtypes           = (wintypes.HWND, wintypes.LPCWSTR)
_user32.SetWindowTextW.restype            = wintypes.BOOL

# Define function signatures for ShowWindow and IsWindowVisible
_user32.ShowWindow.argtypes = (wintypes.HWND, wintypes.INT)
_user32.ShowWindow.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = (wintypes.HWND,)
_user32.IsWindowVisible.restype = wintypes.BOOL

# Define the function signature for GetWindowDisplayAffinity
#   BOOL GetWindowDisplayAffinity(HWND hWnd, DWORD *pdwAffinity)
# This is the read-back counterpart of SetWindowDisplayAffinity: it lets us
# actually confirm the protection took effect instead of assuming it did.
# The lookup is guarded so an older/unusual Windows build that does not export
# the symbol keeps working with the previous best-effort check.
try:
    _user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
    _user32.GetWindowDisplayAffinity.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _HAS_GET_DISPLAY_AFFINITY = True
except AttributeError:
    _HAS_GET_DISPLAY_AFFINITY = False

# IsWindow is used as the fallback verification check
_user32.IsWindow.argtypes = (wintypes.HWND,)
_user32.IsWindow.restype = wintypes.BOOL

# Screen sharing indicator detection constants
SCREEN_SHARE_INDICATORS = [
    # Generic Windows indicators
    "Screen sharing indicator",
    "You're sharing your screen",
    "Screen Share Notification", 
    "Screen Recording Indicator",
    "Sharing indicator",
    "Recording indicator",
    "You are sharing your screen",
    "Screen share active",
    "Recording in progress",
    
    # Browser-specific indicators
    "Chrome is sharing your screen",
    "Microsoft Edge is sharing your screen", 
    "Firefox is sharing your screen",
    "Safari is sharing your screen",
    "Opera is sharing your screen",
    "Brave is sharing your screen",
    "is sharing your screen",
    "wants to share your screen",
    "Screen capture in progress",
    "Display capture active",
    
    # Video conferencing platforms
    "Zoom is sharing your screen",
    "Microsoft Teams is sharing your screen",
    "Google Meet is sharing your screen",
    "Skype is sharing your screen",
    "Discord is sharing your screen",
    "Slack is sharing your screen",
    "WebEx is sharing your screen",
    "GoToMeeting is sharing your screen",
    "BlueJeans is sharing your screen",
    "Jitsi is sharing your screen",
    "BigBlueButton is sharing your screen",
    
    # Screen recording software
    "OBS is recording your screen",
    "OBS Studio is recording",
    "Camtasia is recording",
    "Bandicam is recording",
    "Fraps is recording",
    "XSplit is recording",
    "Streamlabs is recording",
    "Action! is recording",
    "Nvidia ShadowPlay",
    "AMD ReLive",
    "Windows Game Bar recording",
    "Xbox Game Bar recording",
    
    # Remote desktop and sharing tools
    "TeamViewer is sharing your screen",
    "AnyDesk is sharing your screen", 
    "Chrome Remote Desktop",
    "Windows Remote Desktop",
    "VNC is sharing your screen",
    "LogMeIn is sharing your screen",
    "Splashtop is sharing your screen",
    "Parsec is sharing your screen",
    
    # Generic patterns
    "sharing your desktop",
    "recording your desktop", 
    "capturing your screen",
    "desktop sharing active",
    "screen capture active",
    "display recording",
    "monitor sharing",
    "window sharing",
    "application sharing",
    "presentation mode active",
    
    # Notification variations
    "Screen share notification",
    "Recording notification", 
    "Capture notification",
    "Privacy indicator",
    "Camera and microphone access",
    "Microphone access",
    "Screen access granted",
    
    # Development and testing tools
    "Selenium is controlling",
    "Puppeteer is controlling",
    "Playwright is controlling",
    "Automated testing in progress",
    "Browser automation active"
]

# Window classes that can host a sharing/recording indicator. A class match
# alone is not enough: several of these are generic shells, so the title must
# also carry one of the verification keywords below.
SCREEN_SHARE_CLASSES = [
    # Windows system notifications
    "NotificationPresenterHost",  # Windows notification
    "Windows.UI.Core.CoreWindow",  # Windows 10/11 notifications
    "ApplicationFrameHost",        # Windows 10/11 app frame
    "Shell_TrayWnd",              # System tray notifications

    # Video conferencing
    "ZPContentViewWndClass",      # Zoom
    "ZPFloatToolbarClass",        # Zoom toolbar
    "TeamsWebView",               # Microsoft Teams
    "SkypeWindowClass",           # Skype
    "DiscordWindowClass",         # Discord
    "SlackWindowClass",           # Slack

    # Screen recording software
    "Qt5QWindowIcon",             # OBS Studio
    "OBSWindowClass",             # OBS
    "CamtasiaStudioWindowClass",  # Camtasia
    "BandicamWindowClass",        # Bandicam
    "XSplitWindowClass",          # XSplit
    "StreamlabsWindowClass",      # Streamlabs
    "FrapsWindowClass",           # Fraps
    "ActionWindowClass",          # Mirillis Action!

    # Remote desktop tools
    "TeamViewer_DesktopWindowClass",  # TeamViewer
    "AnyDeskWindowClass",             # AnyDesk
    "VNCWindowClass",                 # VNC viewers
    "LogMeInWindowClass",             # LogMeIn
    "SplashtopWindowClass",           # Splashtop
    "ParsecWindowClass",              # Parsec

    # System recording indicators
    "GameBarDisplayCaptureIndicator", # Xbox Game Bar
    "NvidiaGeForceExperience",        # Nvidia ShadowPlay
    "AMDReliveWindowClass",           # AMD ReLive

    # Generic Windows classes
    "NotifyIconOverflowWindow",       # System tray overflow
    "ToolbarWindow32",                # Toolbar notifications
    "Static",                         # Static text windows
    "Button"                          # Button controls
]

# Browser main-frame window classes. These are the TOP-LEVEL windows of
# browsers the user is actively using. They must NEVER be hidden, moved,
# or minimized — doing so makes the browser vanish and the user thinks
# it closed. Chrome/Edge share toasts are separate small child windows,
# so excluding the main frame class does not lose real indicator hiding.
BROWSER_MAIN_FRAME_CLASSES = {
    "Chrome_WidgetWin_1",       # Chrome / Edge / Brave (all Chromium)
    "MozillaWindowClass",       # Firefox main window
    "MozillaDialogClass",       # Firefox dialog
    "ApplicationFrameWindow",   # UWP app frame (Edge, etc.)
    "OpusApp",                  # Opera
    "CefMainWindowWindow",      # CEF-based browsers
    "Intermediate D3D Window",  # Chrome GPU window
    "Chrome_RenderWidgetHostHWND",
}

# A class match only counts as an indicator when the title contains one of these.
#
# These must stay MULTI-WORD phrases. A bare "screen" or "access" matches almost
# any browser tab title ("Screen Sharing Policy", "Remote Access", "Display
# Layouts", "Control Panel"), and since the top-level browser frame class is also
# in SCREEN_SHARE_CLASSES, a single-word keyword made the auto-hider match and
# hide the user's entire main browser window. A class match plus a generic word
# is not enough evidence that a window is a share toast.
SCREEN_SHARE_VERIFICATION_KEYWORDS = [
    "is sharing your screen", "are sharing your screen",
    "sharing your screen", "sharing your desktop", "sharing your display",
    "is recording your screen", "recording your screen", "recording your desktop",
    "is capturing your screen", "screen share", "screen record",
    "capture in progress", "recording in progress",
    "presentation mode active", "broadcasting your",
    "is being shared", "is being recorded",
    "remote control", "remote desktop"
]

# Auto-hiding is limited to small toast-sized windows. A real share indicator
# is a small bubble (~300x150 px). A main application window (browser, editor,
# exam client) is orders of magnitude larger. This is the safety net that stops
# the monitor from ever hiding a real application window even if a title
# happens to match.
MAX_INDICATOR_WIDTH_PX = 400
MAX_INDICATOR_HEIGHT_PX = 200

# Precomputed lowercase needles. find_screen_share_indicators() matches these
# against every top-level window on every scan tick, so lowercasing them once at
# import removes ~110 redundant .lower() calls per window per tick.
_INDICATORS_LOWER = tuple(text.lower() for text in SCREEN_SHARE_INDICATORS)
_SHARE_CLASSES_LOWER = tuple(name.lower() for name in SCREEN_SHARE_CLASSES)
_VERIFICATION_KEYWORDS_LOWER = tuple(k.lower() for k in SCREEN_SHARE_VERIFICATION_KEYWORDS)

class WindowManager:
    def __init__(self):
        self.hwnd: Optional[int] = None
        self.is_windows = platform.system() == "Windows"
        self.current_transparency = 1.0
        self.is_ghost_mode = False
        self.screen_share_monitor_active = False
        self.hidden_screen_share_windows = {}  # hwnd -> original RECT tuple
        self.stealth_active = False            # True once hide-by-default stealth is applied
        self._peek_timer = None                # auto-hide timer for Alt+Z peeks
        self._last_scroll_activity = 0.0       # monotonic stamp of last scroll hotkey repeat
        self._native_title_scrubbed = False    # native title blanked while hidden
        self._hidden_native_title = ""         # original title to restore on show
        self._pre_hide_rect = None             # window rect before hiding, for restore
        
        # Continuous scrolling state
        self.scrolling_up = False
        self.scrolling_down = False
        self.scroll_thread = None
        self.hotkey_listener = None
        self.alt_pressed = False

        if self.is_windows:
            self._setup_win32_api_definitions()

    def _setup_win32_api_definitions(self):
        """Defines all necessary Win32 API functions, constants, and types."""
        # Constants
        self.GWL_EXSTYLE = -20
        self.WS_EX_LAYERED = 0x80000
        self.WS_EX_TOPMOST = 0x8
        self.WS_EX_TRANSPARENT = 0x20
        self.WS_EX_TOOLWINDOW = 0x80  # Added for taskbar hiding
        self.LWA_ALPHA = 0x2
        self.HWND_TOPMOST = -1
        self.HWND_NOTOPMOST = -2
        self.SWP_NOMOVE = 0x2
        self.SWP_NOSIZE = 0x1
        self.SWP_NOACTIVATE = 0x10  # Don't activate the window when moving
        self.SWP_NOZORDER = 0x4     # Don't change Z-order

        self.user32 = ctypes.windll.user32
        
        # Correctly define SetWindowLongPtr and GetWindowLongPtr for 32/64-bit
        is_64bit = platform.architecture()[0] == '64bit'
        if is_64bit:
            self.GetWindowLongPtr = self.user32.GetWindowLongPtrW
            self.SetWindowLongPtr = self.user32.SetWindowLongPtrW
        else:
            self.GetWindowLongPtr = self.user32.GetWindowLongW
            self.SetWindowLongPtr = self.user32.SetWindowLongW

        self.GetWindowLongPtr.restype = wintypes.LPARAM
        self.GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
        self.SetWindowLongPtr.restype = wintypes.LPARAM
        self.SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LPARAM]

        # SetLayeredWindowAttributes
        self.SetLayeredWindowAttributes = self.user32.SetLayeredWindowAttributes
        self.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
        self.SetLayeredWindowAttributes.restype = wintypes.BOOL

        # SetWindowPos
        self.SetWindowPos = self.user32.SetWindowPos
        self.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.SetWindowPos.restype = wintypes.BOOL

        # EnumWindows for finding all windows
        self.EnumWindows = self.user32.EnumWindows
        self.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
        self.EnumWindows.restype = wintypes.BOOL

        # GetWindowText for getting window titles
        self.GetWindowTextW = self.user32.GetWindowTextW
        self.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.GetWindowTextW.restype = ctypes.c_int

        # GetClassName for getting window class names
        self.GetClassNameW = self.user32.GetClassNameW
        self.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.GetClassNameW.restype = ctypes.c_int

        # Define RECT structure for GetWindowRect
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long)
            ]
        
        self.RECT = RECT

        # GetWindowRect for getting window position and size
        self.GetWindowRect = self.user32.GetWindowRect
        self.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        self.GetWindowRect.restype = wintypes.BOOL
            
    def set_window_handle(self, window_handle: int):
        """Set the window handle for transparency operations"""
        self.hwnd = window_handle
        if self.is_windows and self.hwnd:
            self._enable_transparency()
        
    def _enable_transparency(self):
        """Enable transparency capability for the window"""
        if not self.is_windows or not self.hwnd:
            return False
            
        try:
            # Get current window style
            ex_style = self.GetWindowLongPtr(self.hwnd, self.GWL_EXSTYLE)
            
            # Add layered window style if not present
            if not (ex_style & self.WS_EX_LAYERED):
                new_style = ex_style | self.WS_EX_LAYERED
                self.SetWindowLongPtr(self.hwnd, self.GWL_EXSTYLE, new_style)
                
            return True
        except Exception as e:
            print(f"Error enabling transparency: {e}")
            return False
    
    def set_transparency(self, transparency: float) -> bool:
        """
        Set window transparency level
        Args:
            transparency: Float between 0.0 (fully transparent) and 1.0 (fully opaque)
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_windows or not self.hwnd:
            print("Transparency not supported on this platform or no window handle")
            return False
            
        # Clamp transparency value
        transparency = max(0.0, min(1.0, transparency))
        self.current_transparency = transparency
        
        try:
            # Convert to Windows alpha value (0-255)
            alpha = int(transparency * 255)
            
            # Apply transparency
            result = self.SetLayeredWindowAttributes(
                self.hwnd,
                0,  # colorkey (not used)
                alpha,  # alpha value
                self.LWA_ALPHA  # use alpha
            )
            
            if result:
                print(f"✅ Window transparency set to {transparency*100:.0f}%")
                return True
            else:
                print("❌ Failed to set window transparency")
                return False
                
        except Exception as e:
            print(f"❌ Error setting transparency: {e}")
            return False
    
    def get_transparency(self) -> float:
        """Get current transparency level"""
        return self.current_transparency
    
    def set_transparency_percent(self, percent: int) -> bool:
        """
        Set transparency as percentage
        Args:
            percent: Integer between 0 (fully transparent) and 100 (fully opaque)
        """
        transparency = percent / 100.0
        return self.set_transparency(transparency)
    
    def make_transparent(self) -> bool:
        """Make window 60% transparent (40% opacity) - good for interviews"""
        return self.set_transparency(0.4)
    
    def make_semi_transparent(self) -> bool:
        """Make window semi-transparent (70% opacity)"""
        return self.set_transparency(0.7)
    
    def make_opaque(self) -> bool:
        """Make window fully opaque"""
        return self.set_transparency(1.0)
    
    def find_window_by_title(self, title: str) -> Optional[int]:
        """Find this process's window handle by title (PID-filtered).

        The old blind FindWindowW call could match another process's window
        that happens to share the title — all stealth operations then silently
        acted on the wrong window.
        """
        if not self.is_windows:
            return None
            
        try:
            hwnd = _find_own_window(title)
            if hwnd:
                self.set_window_handle(hwnd)
                return hwnd
            return None
        except Exception as e:
            print(f"Error finding window: {e}")
            return None

    def find_screen_share_indicators(self, only_visible: bool = True) -> list:
        """Find all screen sharing indicator windows.

        only_visible=False also returns indicators this app already hid —
        needed to track whether a share is *active* (the window still exists)
        rather than merely visible at this instant.
        """
        if not self.is_windows:
            return []
        
        found_windows = []
        
        def enum_windows_callback(hwnd, lparam):
            try:
                # Get window title
                title_buffer = ctypes.create_unicode_buffer(512)
                title_length = self.GetWindowTextW(hwnd, title_buffer, 512)
                title = title_buffer.value if title_length > 0 else ""
                
                # Get window class name
                class_buffer = ctypes.create_unicode_buffer(256)
                class_length = self.GetClassNameW(hwnd, class_buffer, 256)
                class_name = class_buffer.value if class_length > 0 else ""
                
                # A share indicator is a small toast, never a full application
                # window. Bail out on anything large so a browser/editor/exam
                # window can never be treated as an indicator, whatever its title.
                rect = self.RECT()
                if not self.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return True
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if width > MAX_INDICATOR_WIDTH_PX or height > MAX_INDICATOR_HEIGHT_PX:
                    return True

                # NEVER touch a browser's main top-level window. This is the
                # safety net that stops Chrome/Firefox/Edge from vanishing.
                if class_name in BROWSER_MAIN_FRAME_CLASSES:
                    return True

                # Check if this looks like a screen sharing indicator
                is_indicator = False
                
                # Check title for screen sharing keywords
                title_lower = title.lower()
                for indicator_text in _INDICATORS_LOWER:
                    if indicator_text in title_lower:
                        is_indicator = True
                        break
                
                # Check class name for known screen sharing/recording classes
                if not is_indicator:
                    class_name_lower = class_name.lower()
                    for share_class in _SHARE_CLASSES_LOWER:
                        if share_class in class_name_lower:
                            # Additional verification for these classes
                            if any(keyword in title_lower for keyword in _VERIFICATION_KEYWORDS_LOWER):
                                is_indicator = True
                                break
                
                if is_indicator and (not only_visible or _user32.IsWindowVisible(hwnd)):
                    found_windows.append({
                        'hwnd': hwnd,
                        'title': title,
                        'class': class_name,
                        'rect': (rect.left, rect.top, rect.right, rect.bottom)
                    })
                    if _user32.IsWindowVisible(hwnd):
                        print(f"🔍 Found screen share indicator: '{title}' (Class: {class_name})")
                
            except Exception as e:
                # Continue enumeration even if one window fails
                pass
            
            return True  # Continue enumeration
        
        try:
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            callback = callback_type(enum_windows_callback)
            self.EnumWindows(callback, 0)
        except Exception as e:
            print(f"❌ Error enumerating windows: {e}")
        
        return found_windows

    def hide_screen_share_indicator(self, hwnd: int, rect=None) -> bool:
        """Hide a specific screen sharing indicator window"""
        if not self.is_windows:
            return False
        
        try:
            # Remember where the window was so it can be put back later.
            # Nothing in the app restored these windows before, which is why a
            # wrongly hidden window stayed gone for the rest of the session.
            if rect is None:
                probe = self.RECT()
                if self.GetWindowRect(hwnd, ctypes.byref(probe)):
                    rect = (probe.left, probe.top, probe.right, probe.bottom)

            # Method 1: Try to hide the window completely.
            # ShowWindow returns the *previous* visibility state, not success, so
            # its return value cannot be used as a success flag. Check afterwards.
            _user32.ShowWindow(hwnd, SW_HIDE)
            if not _user32.IsWindowVisible(hwnd):
                print(f"✅ Hidden screen share indicator (HWND: {hex(hwnd)})")
                self.hidden_screen_share_windows[hwnd] = rect
                return True
            
            # Method 2: Try to move it off-screen if hiding failed
            try:
                self.SetWindowPos(
                    hwnd, 0, 
                    -10000, -10000,  # Move far off-screen
                    0, 0,  # Don't change size
                    self.SWP_NOSIZE | self.SWP_NOZORDER | self.SWP_NOACTIVATE
                )
                print(f"✅ Moved screen share indicator off-screen (HWND: {hex(hwnd)})")
                self.hidden_screen_share_windows[hwnd] = rect
                return True
            except:
                pass
            
            # Method 3: Try to minimize the window
            try:
                _user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
                print(f"✅ Minimized screen share indicator (HWND: {hex(hwnd)})")
                self.hidden_screen_share_windows[hwnd] = rect
                return True
            except:
                pass
                
            print(f"❌ Failed to hide screen share indicator (HWND: {hex(hwnd)})")
            return False
            
        except Exception as e:
            print(f"❌ Error hiding screen share indicator: {e}")
            return False

    def restore_hidden_indicators(self) -> int:
        """Re-show and re-position every window this monitor hid, then clear the cache."""
        restored = 0
        for hwnd, rect in list(self.hidden_screen_share_windows.items()):
            try:
                if not _user32.IsWindow(hwnd):
                    continue  # Window is gone; nothing to restore.
                if rect:
                    self.SetWindowPos(
                        hwnd, 0, rect[0], rect[1],
                        0, 0,
                        self.SWP_NOSIZE | self.SWP_NOZORDER | self.SWP_NOACTIVATE
                    )
                _user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                restored += 1
            except Exception as e:
                print(f"⚠️ Could not restore window {hex(hwnd)}: {e}")
        self.hidden_screen_share_windows.clear()
        if restored:
            print(f"♻️ Restored {restored} previously hidden window(s)")
        return restored

    def hide_all_screen_share_indicators(self) -> int:
        """Find and hide all screen sharing indicators"""
        if not self.is_windows:
            return 0
        
        indicators = self.find_screen_share_indicators()
        hidden_count = 0
        
        for indicator in indicators:
            hwnd = indicator['hwnd']
            if hwnd not in self.hidden_screen_share_windows:
                if self.hide_screen_share_indicator(hwnd, indicator.get('rect')):
                    hidden_count += 1
        
        if hidden_count > 0:
            print(f"🕵️ Successfully hidden {hidden_count} screen sharing indicator(s)")
        
        return hidden_count

    def start_screen_share_monitor(self):
        """Start monitoring for screen sharing indicators and auto-hide them"""
        if not self.is_windows or self.screen_share_monitor_active:
            return
        
        print("🔍 Starting screen sharing indicator monitor...")
        self.screen_share_monitor_active = True
        
        def monitor_thread():
            share_was_active = False
            while self.screen_share_monitor_active:
                try:
                    # Existence-based (not visibility-based): we hide these
                    # indicators ourselves, so "visible right now" would flap.
                    indicators = self.find_screen_share_indicators(only_visible=False)
                    for indicator in indicators:
                        if _user32.IsWindowVisible(indicator['hwnd']) and indicator['hwnd'] not in self.hidden_screen_share_windows:
                            self.hide_screen_share_indicator(indicator['hwnd'], indicator.get('rect'))

                    # Rising edge: a share just appeared while Shadow is on screen
                    # (e.g. the user shared before the interview formally started).
                    # Hide immediately — the interview-start hide would come later.
                    share_active = bool(indicators)
                    if share_active and not share_was_active:
                        if self.hwnd and _user32.IsWindowVisible(self.hwnd):
                            print("🖥️ Screen share detected — hiding Shadow immediately (stealth)")
                            self.hide_window()
                    share_was_active = share_active

                    time.sleep(SCREEN_SHARE_SCAN_INTERVAL_S)  # Configurable via .env
                except Exception as e:
                    print(f"❌ Error in screen share monitor: {e}")
                    time.sleep(2.0)  # Wait longer on error
        
        monitor = Thread(target=monitor_thread, daemon=True)
        monitor.start()
        print("✅ Screen sharing indicator monitor started")

    def stop_screen_share_monitor(self):
        """Stop monitoring for screen sharing indicators"""
        if self.screen_share_monitor_active:
            self.screen_share_monitor_active = False
            # Give the thread a moment to notice the flag before restoring.
            time.sleep(SCREEN_SHARE_SCAN_INTERVAL_S + 0.2)
            self.restore_hidden_indicators()
            print("🛑 Screen sharing indicator monitor stopped")
    
    def set_always_on_top(self, on_top: bool) -> bool:
        """
        Set window to always stay on top
        Args:
            on_top: True to set always on top, False to remove
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_windows or not self.hwnd:
            print("Always on top not supported on this platform or no window handle")
            return False
            
        try:
            # Add debugging
            print(f"🔧 Attempting to set always on top: {on_top}, HWND: {self.hwnd}")
            
            hwnd_insert_after = self.HWND_TOPMOST if on_top else self.HWND_NOTOPMOST
            
            # Call SetWindowPos with proper error handling
            result = self.SetWindowPos(
                self.hwnd,
                hwnd_insert_after,
                0, 0, 0, 0,  # x, y, width, height (ignored due to flags)
                self.SWP_NOMOVE | self.SWP_NOSIZE  # Don't move or resize
            )
            
            if result:
                status = "on top" if on_top else "normal"
                print(f"✅ Window set to {status}")
                return True
            else:
                # Get the last error code for debugging
                error_code = ctypes.windll.kernel32.GetLastError()
                print(f"❌ SetWindowPos failed (Error {error_code}), trying alternative method...")
                
                # Try alternative method using window style
                return self._set_always_on_top_alternative(on_top)
                
        except Exception as e:
            print(f"❌ Error setting always on top: {e}")
            return False

    def _set_always_on_top_alternative(self, on_top: bool) -> bool:
        """
        Alternative method to set always on top using window extended styles
        """
        try:
            # Get current extended window style
            ex_style = self.GetWindowLongPtr(self.hwnd, self.GWL_EXSTYLE)
            
            if on_top:
                # Add topmost style
                new_style = ex_style | self.WS_EX_TOPMOST
            else:
                # Remove topmost style
                new_style = ex_style & ~self.WS_EX_TOPMOST
            
            # Set the new style
            result = self.SetWindowLongPtr(self.hwnd, self.GWL_EXSTYLE, new_style)
            
            if result or ex_style != new_style:
                # Force window update
                self.user32.SetWindowPos(
                    self.hwnd, 0, 0, 0, 0, 0,
                    self.SWP_NOMOVE | self.SWP_NOSIZE | 0x0020  # SWP_FRAMECHANGED
                )
                status = "on top" if on_top else "normal"
                print(f"✅ Window set to {status} (alternative method)")
                return True
            else:
                print("❌ Alternative method also failed")
                return False
                
        except Exception as e:
            print(f"❌ Error in alternative always-on-top method: {e}")
            return False

    def get_window_info(self) -> dict:
        """Get current window transparency info"""
        return {
            "transparency": self.current_transparency,
            "transparency_percent": int(self.current_transparency * 100),
            "is_transparent": self.current_transparency < 1.0,
            "platform_supported": self.is_windows,
            "window_handle": self.hwnd,
            "screen_share_monitor_active": self.screen_share_monitor_active,
            "hidden_screen_share_windows": len(self.hidden_screen_share_windows)
        }

    def set_ghost_mode(self, enabled: bool):
        """Enable or disable 'click-through' (ghost) mode."""
        if not self.is_windows or not self.hwnd:
            return

        try:
            current_style = self.GetWindowLongPtr(self.hwnd, self.GWL_EXSTYLE)
            if enabled:
                new_style = current_style | self.WS_EX_TRANSPARENT
                print("👻 Ghost Mode Enabled (click-through)")
            else:
                new_style = current_style & ~self.WS_EX_TRANSPARENT
                print("🖱️ Ghost Mode Disabled (normal interaction)")

            self.SetWindowLongPtr(self.hwnd, self.GWL_EXSTYLE, new_style)
            self.is_ghost_mode = enabled
            
            # Force re-apply always-on-top after style change
            self.set_always_on_top(True)
            
        except Exception as e:
            print(f"❌ Error setting ghost mode: {e}")

    def toggle_ghost_mode(self):
        """Toggles the ghost mode on or off."""
        self.set_ghost_mode(not self.is_ghost_mode)

    def enable_proctoring_stealth_mode(self):
        """
        Enable complete stealth mode for proctoring environments.
        
        This mode combines multiple stealth features:
        - Ghost mode (click-through) to prevent accidental focus
        - Screen capture protection
        - Always on top but without focus
        - Hidden from taskbar
        
        Use global hotkeys (Alt+Z, Alt+X, etc.) to interact safely.
        """
        if not self.is_windows or not self.hwnd:
            print("❌ Proctoring stealth mode requires Windows and valid window handle")
            return False
        
        try:
            print("🎯 Enabling PROCTORING STEALTH MODE...")
            
            # 1. Enable ghost mode (click-through)
            self.set_ghost_mode(True)
            
            # 2. Hide from taskbar
            self.hide_from_taskbar()
            
            # 3. Set always on top but without focus
            self.set_always_on_top(True)
            
            # 4. Make semi-transparent for visibility without being obvious
            self.set_transparency(0.7)
            
            print("✅ PROCTORING STEALTH MODE ENABLED")
            print("   🚨 IMPORTANT: Use ONLY global hotkeys to interact:")
            print("   📌 Alt+Z: Toggle visibility (no focus change)")
            print("   📌 Alt+X: Toggle ghost mode")
            print("   📌 Alt+1/2/3: Adjust transparency")
            print("   📌 DO NOT click on the window - it will trigger focus detection!")
            
            return True
            
        except Exception as e:
            print(f"❌ Error enabling proctoring stealth mode: {e}")
            return False

    def move_window(self, dx: int, dy: int) -> bool:
        """
        Move window by specified offset without changing focus (stealth movement).
        
        Args:
            dx: Horizontal offset in pixels (positive = right, negative = left)
            dy: Vertical offset in pixels (positive = down, negative = up)
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_windows or not self.hwnd:
            print("❌ Window movement requires Windows and valid window handle")
            return False
        
        try:
            # Get current window position
            rect = self.RECT()
            if not self.GetWindowRect(self.hwnd, ctypes.byref(rect)):
                print("❌ Failed to get current window position")
                return False
            
            # Calculate new position
            new_x = rect.left + dx
            new_y = rect.top + dy
            
            # Move window without activating it
            result = self.SetWindowPos(
                self.hwnd,
                0,  # hwndInsertAfter (ignored due to SWP_NOZORDER)
                new_x, new_y,  # new position
                0, 0,  # width, height (ignored due to SWP_NOSIZE)
                self.SWP_NOSIZE | self.SWP_NOACTIVATE | self.SWP_NOZORDER
            )
            
            if result:
                direction = ""
                if dx > 0:
                    direction += f"right {dx}px "
                elif dx < 0:
                    direction += f"left {abs(dx)}px "
                if dy > 0:
                    direction += f"down {dy}px"
                elif dy < 0:
                    direction += f"up {abs(dy)}px"
                
                print(f"🎯 Window moved {direction.strip()} (stealth - no focus change)")
                return True
            else:
                print("❌ Failed to move window")
                return False
                
        except Exception as e:
            print(f"❌ Error moving window: {e}")
            return False


    def _cancel_peek_timer(self):
        """Cancel a pending auto-hide timer, if one is running."""
        if self._peek_timer is not None:
            try:
                self._peek_timer.cancel()
            except Exception:
                pass
            self._peek_timer = None

    def _scrub_title(self):
        """Blank the native window title while hidden.

        SW_HIDE windows remain enumerable — a proctoring scan that lists
        hidden top-level windows would otherwise match the name "Shadow".
        """
        if not self.is_windows or not self.hwnd or self._native_title_scrubbed:
            return
        try:
            length = _user32.GetWindowTextLengthW(self.hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(self.hwnd, buf, length + 1)
                self._hidden_native_title = buf.value
            _user32.SetWindowTextW(self.hwnd, "")
            self._native_title_scrubbed = True
        except Exception as e:
            print(f"⚠️ Could not scrub window title: {e}")

    def _restore_title(self):
        """Restore the native window title after a peek/show."""
        if not self.is_windows or not self.hwnd or not self._native_title_scrubbed:
            return
        try:
            _user32.SetWindowTextW(self.hwnd, self._hidden_native_title or "Shadow")
            self._native_title_scrubbed = False
        except Exception as e:
            print(f"⚠️ Could not restore window title: {e}")

    def _start_peek_timer(self):
        """Auto-hide the window STEALTH_PEEK_SECONDS after it is shown (0 disables)."""
        self._cancel_peek_timer()
        seconds = get_peek_seconds()
        if seconds <= 0:
            return

        def _auto_hide():
            if self.hwnd and _user32.IsWindow(self.hwnd) and _user32.IsWindowVisible(self.hwnd):
                _user32.ShowWindow(self.hwnd, SW_HIDE)
                self.set_ghost_mode(False)
                self._scrub_title()
                print(f"🕵️‍ Window auto-hidden after {seconds:.0f}s peek (stealth).")

        self._peek_timer = Timer(seconds, _auto_hide)
        self._peek_timer.daemon = True
        self._peek_timer.start()
        print(f"⏱️ Peek auto-hide in {seconds:.0f}s (STEALTH_PEEK_SECONDS=0 to disable).")

    def hide_window(self) -> bool:
        """Programmatically hide the Shadow window (stealth)."""
        if not self.is_windows or not self.hwnd:
            return False
        self._cancel_peek_timer()
        was_visible = bool(_user32.IsWindowVisible(self.hwnd))
        # Remember where the window was so we can bring it back (only when visible).
        if was_visible:
            try:
                r = wintypes.RECT()
                if _user32.GetWindowRect(self.hwnd, ctypes.byref(r)):
                    self._pre_hide_rect = (r.left, r.top, r.right - r.left, r.bottom - r.top)
            except Exception:
                pass
        for _ in range(3):
            _user32.ShowWindow(self.hwnd, SW_HIDE)
            time.sleep(0.05)
            if not _user32.IsWindowVisible(self.hwnd):
                break
        # Off-screen fallback only if still visible.
        try:
            if _user32.IsWindowVisible(self.hwnd):
                _user32.SetWindowPos(self.hwnd, None, -32000, -32000, 0, 0, 0x0001 | 0x0010)
        except Exception:
            pass
        self.set_ghost_mode(False)
        self._scrub_title()
        if was_visible:
            print("Window hidden (stealth) - press Alt+Z to peek.")
        return True

    def show_window(self) -> bool:
        """Show the Shadow window without focus change and without auto-hide (e.g. after interview ends)."""
        if not self.is_windows or not self.hwnd:
            return False
        self._cancel_peek_timer()
        # Restore original on-screen position if we moved it off-screen.
        try:
            rect = getattr(self, "_pre_hide_rect", None)
            if rect:
                _user32.SetWindowPos(self.hwnd, None, rect[0], rect[1], rect[2], rect[3], 0x0010 | 0x0004)
        except Exception:
            pass
        _user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self._restore_title()
        self.set_ghost_mode(False)  # interactive again once the interview is over
        self.set_always_on_top(True)
        print("Window shown (no auto-hide) - Alt+Z hides it again.")
        return True

    def toggle_visibility(self):
        """Toggle the window's visibility without changing focus (stealth mode)."""
        if not self.is_windows or not self.hwnd:
            print("Window visibility control not supported or no window handle.")
            return

        if _user32.IsWindowVisible(self.hwnd):
            self._cancel_peek_timer()
            _user32.ShowWindow(self.hwnd, SW_HIDE)
            self.set_ghost_mode(False)
            self._scrub_title()
            print("🕵️‍ Window hidden via global hotkey.")
        else:
            # Restore on-screen position if we moved it off-screen.
            try:
                rect = getattr(self, "_pre_hide_rect", None)
                if rect:
                    _user32.SetWindowPos(self.hwnd, None, rect[0], rect[1], rect[2], rect[3], 0x0010 | 0x0004)
            except Exception:
                pass
            # Use SW_SHOWNOACTIVATE to show window without giving it focus
            _user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            self._restore_title()
            # Click-through while peeking: any click falls through to the app
            # behind, so the interview page NEVER receives a blur event.
            # (Alt+X disables this manually if you need to click Shadow itself.)
            self.set_ghost_mode(True)
            print("✨ Window shown via global hotkey (stealth - no focus, click-through).")
            # Re-apply always-on-top state when showing the window
            self.set_always_on_top(True)
            self._start_peek_timer()

    def hide_from_taskbar(self) -> bool:
        """Hide the window from the taskbar by setting WS_EX_TOOLWINDOW."""
        if not self.is_windows or not self.hwnd:
            print("Cannot hide from taskbar: Not on Windows or no window handle")
            return False
        try:
            # Get current extended style
            ex_style = self.GetWindowLongPtr(self.hwnd, self.GWL_EXSTYLE)
            # Add WS_EX_TOOLWINDOW and remove WS_EX_APPWINDOW (0x40000) if present
            new_style = (ex_style | self.WS_EX_TOOLWINDOW) & ~0x40000
            # Set the new style
            self.SetWindowLongPtr(self.hwnd, self.GWL_EXSTYLE, new_style)
            print("✅ Window hidden from taskbar")
            return True
        except Exception as e:
            print(f"❌ Error hiding from taskbar: {e}")
            return False

    def _start_hotkey_listener_thread(self):
        """The actual listener thread for global hotkeys."""
        print("🎧 Starting global hotkey listener thread...")

        def on_hide_show():
            self.toggle_visibility()
            return False

        def on_toggle_ghost():
            self.toggle_ghost_mode()
            return False

        def on_toggle_vision_mode():
            """Toggle vision mode (Alt+V)"""
            self.send_vision_command("toggle_vision_mode")
            return False

        def on_capture_screenshot():
            """Capture screenshot (Alt+S)"""
            self.send_vision_command("capture_screenshot")
            return False

        def on_process_screenshots():
            """Process screenshots with AI (Alt+P)"""
            self.send_vision_command("process_screenshots")
            return False

        def on_switch_primary():
            """Switch to primary AI preset (Alt+Q)"""
            self.send_preset_switch_signal("primary")
            return False

        def on_switch_secondary():
            """Switch to secondary AI preset (Alt+W)"""
            self.send_preset_switch_signal("secondary")
            return False

        def on_auto_select():
            """Auto-select best available AI preset (Alt+E)"""
            self.send_context_aware_command("auto_select_preset")
            return False

        def on_switch_vision_model():
            """Switch vision model (Alt+T)"""
            self.send_vision_switch_command("switch_vision_model")
            return False

        def on_transparency_transparent():
            """Set window to transparent (40% opacity) - Alt+1"""
            self.send_transparency_command("transparent")
            return False

        def on_transparency_semi():
            """Set window to semi-transparent (70% opacity) - Alt+2"""
            self.send_transparency_command("semi")
            return False

        def on_transparency_opaque():
            """Set window to opaque (100% opacity) - Alt+3"""
            self.send_transparency_command("opaque")
            return False

        def on_toggle_mic_mute():
            """Toggle microphone mute (Alt+M)"""
            self.send_audio_command("toggle_mic_mute")
            return False

        def on_toggle_universal_mute():
            """Toggle universal mute/pause (Alt+U)"""
            self.send_audio_command("toggle_universal_mute")
            return False

        def on_reset_screenshot_queue():
            """Reset/clear screenshot queue (Alt+R)"""
            self.send_vision_command("reset_screenshot_queue")
            return False

        def on_enable_proctoring_stealth():
            """Enable proctoring stealth mode (Alt+Shift+S)"""
            self.enable_proctoring_stealth_mode()
            return False

        def on_move_left():
            """Move window left (Alt+Left)"""
            self.move_window(-20, 0)
            return False

        def on_move_right():
            """Move window right (Alt+Right)"""
            self.move_window(20, 0)
            return False

        def on_move_up():
            """Move window up (Alt+I) - SWAPPED"""
            self.move_window(0, -20)
            return False

        def on_move_down():
            """Move window down (Alt+J) - SWAPPED"""
            self.move_window(0, 20)
            return False

        def on_reset_interview():
            """Reset interview session (Alt+O)"""
            self.send_interview_command("reset_interview")
            return False

        def on_answer_feedback_good():
            """Rate last AI answer as good (Alt+G)"""
            self.send_answer_feedback("good")
            return False

        def on_answer_feedback_bad():
            """Rate last AI answer as missed/bad (Alt+B)"""
            self.send_answer_feedback("bad")
            return False

        # --- Scroll hold-to-repeat via OS key repeat -------------------------
        # The old pynput release listener required WH_KEYBOARD_LL. Instead we
        # register Alt+Up/Down WITHOUT MOD_NOREPEAT so the OS auto-repeat keeps
        # stamping activity, and a watchdog stops scrolling when repeats cease.
        def on_scroll_up_start():
            """Start continuous scroll up (Alt+Up)"""
            self._last_scroll_activity = time.monotonic()
            if not self.scrolling_up:
                self.scrolling_up = True
                self._start_continuous_scrolling()
                print("🔼 Starting continuous scroll up")
            return False

        def on_scroll_down_start():
            """Start continuous scroll down (Alt+Down)"""
            self._last_scroll_activity = time.monotonic()
            if not self.scrolling_down:
                self.scrolling_down = True
                self._start_continuous_scrolling()
                print("🔽 Starting continuous scroll down")
            return False

        def scroll_watchdog():
            """Stop scrolling when OS key-repeat stops (i.e. key released)."""
            while True:
                time.sleep(0.15)
                if self.scrolling_up or self.scrolling_down:
                    if time.monotonic() - self._last_scroll_activity > 0.3:
                        self.scrolling_up = False
                        self.scrolling_down = False
                        print("🛑 Stopped continuous scroll (key released)")

        Thread(target=scroll_watchdog, daemon=True).start()

        # --- Hotkey dispatch: Win32 RegisterHotKey (NO keyboard hook) -------
        # pynput's GlobalHotKeys installs a WH_KEYBOARD_LL hook that any
        # proctoring software can enumerate as an injection-capable listener.
        # RegisterHotKey installs no hook at all: the OS posts WM_HOTKEY to
        # this thread's queue only for the exact combos registered below.
        MOD_ALT = 0x0001
        MOD_SHIFT = 0x0004
        MOD_NOREPEAT = 0x4000
        WM_HOTKEY = 0x0312
        VK = {
            'x': 0x58, 'z': 0x5A, 'v': 0x56, 's': 0x53, 'p': 0x50, 'r': 0x52,
            'q': 0x51, 'w': 0x57, 'e': 0x45, 't': 0x54, 'm': 0x4D, 'u': 0x55,
            '1': 0x31, '2': 0x32, '3': 0x33, 'o': 0x4F, 'i': 0x49, 'j': 0x4A,
            'g': 0x47, 'b': 0x42,
            'left': 0x25, 'right': 0x27, 'up': 0x26, 'down': 0x28,
        }

        # (modifiers, virtual-key, handler, description)
        # MOD_NOREPEAT everywhere except the scroll keys (which rely on repeat).
        specs = [
            (MOD_ALT | MOD_NOREPEAT, VK['x'], on_toggle_ghost, 'Alt+X: Toggle ghost mode (click-through)'),
            (MOD_ALT | MOD_NOREPEAT, VK['z'], on_hide_show, 'Alt+Z: Toggle window visibility (stealth)'),
            (MOD_ALT | MOD_NOREPEAT, VK['v'], on_toggle_vision_mode, 'Alt+V: Toggle vision mode'),
            (MOD_ALT | MOD_NOREPEAT, VK['s'], on_capture_screenshot, 'Alt+S: Capture screenshot'),
            (MOD_ALT | MOD_NOREPEAT, VK['p'], on_process_screenshots, 'Alt+P: Process screenshots with AI'),
            (MOD_ALT | MOD_NOREPEAT, VK['r'], on_reset_screenshot_queue, 'Alt+R: Reset screenshot queue'),
            (MOD_ALT | MOD_NOREPEAT, VK['q'], on_switch_primary, 'Alt+Q: Switch to primary AI preset'),
            (MOD_ALT | MOD_NOREPEAT, VK['w'], on_switch_secondary, 'Alt+W: Switch to secondary AI preset'),
            (MOD_ALT | MOD_NOREPEAT, VK['e'], on_auto_select, 'Alt+E: Auto-select best AI preset'),
            (MOD_ALT | MOD_NOREPEAT, VK['t'], on_switch_vision_model, 'Alt+T: Switch vision model'),
            (MOD_ALT | MOD_NOREPEAT, VK['m'], on_toggle_mic_mute, 'Alt+M: Toggle microphone mute'),
            (MOD_ALT | MOD_NOREPEAT, VK['u'], on_toggle_universal_mute, 'Alt+U: Toggle universal mute (pause)'),
            (MOD_ALT | MOD_NOREPEAT, VK['1'], on_transparency_transparent, 'Alt+1: Set transparent (40% opacity)'),
            (MOD_ALT | MOD_NOREPEAT, VK['2'], on_transparency_semi, 'Alt+2: Set semi-transparent (70% opacity)'),
            (MOD_ALT | MOD_NOREPEAT, VK['3'], on_transparency_opaque, 'Alt+3: Set opaque (100% opacity)'),
            (MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, VK['s'], on_enable_proctoring_stealth, 'Alt+Shift+S: Enable proctoring stealth mode'),
            (MOD_ALT | MOD_NOREPEAT, VK['left'], on_move_left, 'Alt+Left: Move window left'),
            (MOD_ALT | MOD_NOREPEAT, VK['right'], on_move_right, 'Alt+Right: Move window right'),
            (MOD_ALT | MOD_NOREPEAT, VK['i'], on_move_up, 'Alt+I: Move window up'),
            (MOD_ALT | MOD_NOREPEAT, VK['j'], on_move_down, 'Alt+J: Move window down'),
            (MOD_ALT | MOD_NOREPEAT, VK['o'], on_reset_interview, 'Alt+O: Reset interview session'),
            (MOD_ALT | MOD_NOREPEAT, VK['g'], on_answer_feedback_good, 'Alt+G: Rate last AI answer as good'),
            (MOD_ALT | MOD_NOREPEAT, VK['b'], on_answer_feedback_bad, 'Alt+B: Rate last AI answer as missed/bad'),
            (MOD_ALT, VK['up'], on_scroll_up_start, 'Alt+Up: Scroll up (hold for continuous)'),
            (MOD_ALT, VK['down'], on_scroll_down_start, 'Alt+Down: Scroll down (hold for continuous)'),
        ]

        register_hotkey = _user32.RegisterHotKey
        register_hotkey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        register_hotkey.restype = ctypes.c_bool
        unregister_hotkey = _user32.UnregisterHotKey
        unregister_hotkey.argtypes = [wintypes.HWND, ctypes.c_int]
        unregister_hotkey.restype = ctypes.c_bool
        get_message = _user32.GetMessageW
        get_message.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
        get_message.restype = ctypes.c_int

        callbacks = {}
        registered_ids = []
        for hotkey_id, (mods, vk, handler, description) in enumerate(specs, start=1):
            if register_hotkey(None, hotkey_id, mods, vk):
                callbacks[hotkey_id] = handler
                registered_ids.append(hotkey_id)
                print(f"   ✔ {description}")
            else:
                print(f"   ⚠ RegisterHotKey failed for {description} (error {ctypes.GetLastError()})")

        msg = wintypes.MSG()
        try:
            # Blocks until WM_QUIT; posts to THIS thread's queue (hence the loop
            # must live on the thread that called RegisterHotKey — it does).
            while get_message(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    handler = callbacks.get(int(msg.wParam))
                    if handler:
                        try:
                            handler()
                        except Exception as handler_err:
                            print(f"❌ Hotkey handler error: {handler_err}")
        finally:
            for hotkey_id in registered_ids:
                unregister_hotkey(None, hotkey_id)

    def send_preset_switch_signal(self, preset_key: str):
        """Send preset switch signal to the application"""
        try:
            from datetime import datetime
            print(f"🔄 Global hotkey triggered: Switching to {preset_key} preset")
            self._write_command_file({
                "command": "switch_preset",
                "preset_key": preset_key,
                "timestamp": datetime.now().isoformat(),
                "source": "global_hotkey"
            })
        except Exception as e:
            print(f"❌ Error sending preset switch signal: {e}")

    def send_vision_command(self, command: str):
        """Send vision-related command to the application"""
        try:
            from datetime import datetime
            print(f"👁️ Global hotkey triggered: {command}")
            self._write_command_file({
                "command": command,
                "timestamp": datetime.now().isoformat(),
                "source": "global_hotkey"
            })
        except Exception as e:
            print(f"❌ Error sending vision command: {e}")

    def send_transparency_command(self, level: str):
        """Send transparency command to the application"""
        try:
            from datetime import datetime
            print(f"🔍 Global hotkey triggered: set_transparency_{level}")
            self._write_command_file({
                "command": "set_transparency",
                "level": level,
                "timestamp": datetime.now().isoformat(),
                "source": "global_hotkey"
            })
        except Exception as e:
            print(f"❌ Error sending transparency command: {e}")

    def send_audio_command(self, command: str):
        """Send audio-related command to the application"""
        try:
            from datetime import datetime
            print(f"🎤 Global hotkey triggered: {command}")
            self._write_command_file({
                "command": command,
                "timestamp": datetime.now().isoformat(),
                "source": "global_hotkey"
            })
        except Exception as e:
            print(f"❌ Error sending audio command: {e}")

    def send_context_aware_command(self, command: str):
        """Send command for context-aware actions like auto-selecting presets."""
        try:
            from datetime import datetime
            print(f"🔄 Global hotkey triggered: {command}")
            self._write_command_file({
                "command": "context_aware_action",
                "action": command,
                "timestamp": datetime.now().isoformat(),
                "source": "global_hotkey"
            })
        except Exception as e:
            print(f"❌ Error sending context-aware command: {e}")

    def send_vision_switch_command(self, command: str):
        """Send command to switch vision model"""
        try:
            from datetime import datetime
            print(f"👁️ Global hotkey triggered: {command}")
            self._write_command_file({
                "command": command,
                "timestamp": datetime.now().isoformat(),
                "source": "global_hotkey"
            })
        except Exception as e:
            print(f"❌ Error sending vision switch command: {e}")

    def send_answer_feedback(self, rating: str):
        """Send last-answer feedback (Alt+G good / Alt+B missed) to the app."""
        try:
            from datetime import datetime
            print(f"🎯 Global hotkey triggered: answer_feedback ({rating})")
            self._write_command_file({
                "command": "answer_feedback",
                "rating": rating,
                "timestamp": datetime.now().isoformat(),
                "source": "global_hotkey"
            })
        except Exception as e:
            print(f"❌ Error sending answer feedback: {e}")

    def send_interview_command(self, command: str):
        """Send interview-related command to the application"""
        try:
            from datetime import datetime
            print(f"🎤 Global hotkey triggered: {command}")
            self._write_command_file({
                "command": command,
                "timestamp": datetime.now().isoformat(),
                "source": "global_hotkey"
            })
        except Exception as e:
            print(f"❌ Error sending interview command: {e}")

    def send_scroll_command(self, direction: str):
        """Send scroll command to the application"""
        try:
            from datetime import datetime
            print(f"📜 Global hotkey triggered: scroll_{direction} ({SCROLL_AMOUNT_PX}px)")
            self._write_command_file({
                "command": "scroll",
                "direction": direction,
                "amount": SCROLL_AMOUNT_PX,
                "timestamp": datetime.now().isoformat(),
                "source": "global_hotkey"
            })
        except Exception as e:
            print(f"❌ Error sending scroll command: {e}")

    def _continuous_scroll_loop(self):
        """Continuous scrolling loop that runs while scroll keys are held"""
        import time
        while self.scrolling_up or self.scrolling_down:
            try:
                if self.scrolling_up:
                    self.send_scroll_command("up")
                elif self.scrolling_down:
                    self.send_scroll_command("down")
                
                # Wait between scroll commands for smooth scrolling
                time.sleep(SCROLL_INTERVAL_MS / 1000)
            except Exception as e:
                print(f"❌ Error in continuous scroll loop: {e}")
                break
        
        # Reset scroll thread when loop exits
        self.scroll_thread = None
        print("🔄 Continuous scroll loop ended")

    def _start_continuous_scrolling(self):
        """Start the continuous scrolling thread if not already running"""
        if self.scroll_thread is None or not self.scroll_thread.is_alive():
            self.scroll_thread = Thread(target=self._continuous_scroll_loop, daemon=True)
            self.scroll_thread.start()
            print("🔄 Started continuous scroll loop")

    def _write_command_file(self, command_data: dict):
        """Write command to temp file for inter-process communication"""
        import tempfile
        import json
        import os
        
        # Write command to a temp file that could be monitored
        temp_dir = tempfile.gettempdir()
        command_file = os.path.join(temp_dir, "shadow_command.json")
        
        with open(command_file, "w") as f:
            json.dump(command_data, f)
        
        print(f"📄 Command written to: {command_file}")

    def start_hotkey_listener(self):
        """Starts the global hotkey listener in a separate thread."""
        if not self.is_windows:
            print("Global hotkeys not supported on this platform.")
            return

        print("🚀 Initializing global hotkey listener...")
        print("   Alt+X: Toggle ghost mode (click-through)")
        print("   Alt+Z: Toggle window visibility (stealth - no focus)")
        print("   Alt+Left/Right Arrow: Move window left/right (stealth - no focus)")
        print("   Alt+I: Move window up (stealth - no focus)")
        print("   Alt+J: Move window down (stealth - no focus)")
        print("   Alt+Up Arrow: Continuous scroll up (hold for continuous)")
        print("   Alt+Down Arrow: Continuous scroll down (hold for continuous)")
        print("   Alt+V: Toggle vision mode")
        print("   Alt+S: Capture screenshot")
        print("   Alt+P: Process screenshots with AI")
        print("   Alt+R: Reset screenshot queue")
        print("   Alt+O: Reset interview session")
        print("   Alt+G: Rate last AI answer as good")
        print("   Alt+B: Rate last AI answer as missed/bad")
        print("   Alt+Q: Switch to primary AI preset")
        print("   Alt+W: Switch to secondary AI preset")
        print("   Alt+E: Auto-select best AI preset")
        print("   Alt+T: Switch vision model")
        print("   Alt+M: Toggle microphone mute")
        print("   Alt+U: Toggle universal mute (pause)")
        print("   Alt+1: Set transparent (40% opacity)")
        print("   Alt+2: Set semi-transparent (70% opacity)")
        print("   Alt+3: Set opaque (100% opacity)")
        print("   Alt+Shift+S: Enable proctoring stealth mode")
        
        # Ensure we have the handle before starting
        if not self.hwnd:
            if not self.find_window_by_title("Shadow"):
                 print("❌ Cannot start hotkey listener: Shadow window not found.")
                 return
        
        listener_thread = Thread(target=self._start_hotkey_listener_thread, daemon=True)
        listener_thread.start()

# Global instance
window_manager = WindowManager()

# Convenience functions for easy use
def set_app_transparency(transparency: float) -> bool:
    """Set app window transparency (0.0 to 1.0)"""
    return window_manager.set_transparency(transparency)

def set_app_transparency_percent(percent: int) -> bool:
    """Set app window transparency as percentage (0 to 100)"""
    return window_manager.set_transparency_percent(percent)

def make_app_transparent() -> bool:
    """Make app window 60% transparent (good for interviews)"""
    return window_manager.make_transparent()

def make_app_semi_transparent() -> bool:
    """Make app window semi-transparent"""
    return window_manager.make_semi_transparent()

def make_app_opaque() -> bool:
    """Make app window fully opaque"""
    return window_manager.make_opaque()

def find_shadow_window() -> bool:
    """Find and set Shadow window for transparency control"""
    hwnd = window_manager.find_window_by_title("Shadow")
    return hwnd is not None

def set_app_always_on_top(on_top: bool) -> bool:
    """Set app window to always stay on top"""
    return window_manager.set_always_on_top(on_top)

def get_transparency_info() -> dict:
    """Get current transparency information"""
    return window_manager.get_window_info()

def hide_screen_share_indicators() -> int:
    """Hide all screen sharing indicators and return count hidden"""
    return window_manager.hide_all_screen_share_indicators()

def start_screen_share_monitor():
    """Start automatically monitoring and hiding screen share indicators"""
    window_manager.start_screen_share_monitor()

def stop_screen_share_monitor():
    """Stop monitoring screen share indicators"""
    window_manager.stop_screen_share_monitor()

def enable_proctoring_stealth_mode():
    """Enable complete stealth mode for proctoring environments"""
    return window_manager.enable_proctoring_stealth_mode()

def move_window(dx: int, dy: int) -> bool:
    """Move window by specified offset without changing focus"""
    return window_manager.move_window(dx, dy)

def test_screen_share_detection():
    """Test function to show all currently detected screen sharing indicators"""
    print("🔍 Testing screen share indicator detection...")
    indicators = window_manager.find_screen_share_indicators()
    
    if not indicators:
        print("✅ No screen sharing indicators currently detected")
        return []
    
    print(f"🚨 Found {len(indicators)} screen sharing indicator(s):")
    for i, indicator in enumerate(indicators, 1):
        print(f"   {i}. Title: '{indicator['title']}'")
        print(f"      Class: '{indicator['class']}'") 
        print(f"      HWND: {hex(indicator['hwnd'])}")
        print()
    
    return indicators

def _find_own_window(title: str) -> Optional[int]:
    """Return the top-level window titled `title` owned by this process, else None.

    Filters by PID so we never attach to another process's window that happens
    to share the name — a blind FindWindowW title match could do exactly that.
    """
    target_pid = os.getpid()
    user32 = _user32
    found = []
    candidates = []  # (area, hwnd) for fallback largest-window selection

    get_text_len = user32.GetWindowTextLengthW
    get_text_len.argtypes = (wintypes.HWND,)
    get_text_len.restype = ctypes.c_int
    get_text = user32.GetWindowTextW
    get_text.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    get_text.restype = ctypes.c_int
    get_pid = user32.GetWindowThreadProcessId
    get_pid.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    get_pid.restype = wintypes.DWORD
    get_rect = user32.GetWindowRect
    user32.EnumWindows.argtypes = (ctypes.c_void_p, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_cb(hwnd, _lparam):
        pid = wintypes.DWORD(0)
        get_pid(hwnd, ctypes.byref(pid))
        if pid.value != target_pid:
            return True
        # Track every visible top-level window of this process for fallback.
        try:
            r = wintypes.RECT()
            if get_rect(hwnd, ctypes.byref(r)):
                area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
                if area > 0:
                    candidates.append((area, int(hwnd)))
        except Exception:
            pass
        length = get_text_len(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        get_text(hwnd, buf, length + 1)
        if title and buf.value == title:
            found.append(int(hwnd))
            return False  # stop enumeration — match found
        return True

    user32.EnumWindows(enum_cb, 0)
    if found:
        return found[0]
    # Fallback: largest-area visible window owned by this process.
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]
    return None


def apply_capture_protection(window):
    """
    Applies hide-by-default stealth to the Shadow window.

    Windows has no API for a window that is visible to the user but fully
    invisible in screen capture (WDA_EXCLUDEFROMCAPTURE renders a black
    rectangle; transparency still leaks content). So instead:

    1. The window stays visible during onboarding/setup only.
    2. When the interview starts it is hidden with SW_HIDE — while hidden
       it does not exist for the screen compositor, so it appears NOWHERE
       in the share: no black rectangle, no content.
    3. Alt+Z peeks it back for STEALTH_PEEK_SECONDS (default 10s), then it
       auto-hides. While peeked it IS visible in the share — peek briefly.
    4. Hidden from taskbar, always-on-top, never steals focus.

    Set STEALTH_MODE=blackout in .env to fall back to the old
    WDA_EXCLUDEFROMCAPTURE approach if desired.

    Args:
        window: The pywebview window object.
    """
    hwnd = None
    print("🛡️ APPLYING HIDE-BY-DEFAULT STEALTH MODE...")

    # --- Method 1: Get handle from pywebview's private attribute ---
    hwnd = getattr(window, '_hwnd', None)
    if hwnd and not _user32.IsWindow(hwnd):
        print(f"⚠️ window._hwnd {hex(hwnd)} is not a live window — discarding")
        hwnd = None
    print(f"🔍 Method 1 (window._hwnd): {hex(hwnd) if hwnd else 'Not found'}")

    # --- Method 2: PID-filtered EnumWindows (up to ~1s of retries) ---
    # FindWindowW matches ANY process's window titled "Shadow", so it can attach
    # to an unrelated window (another app's Shadow-named dialog, etc). We only
    # ever accept a top-level window owned by this process.
    if not hwnd:
        print("⚠️ Private attribute not found, enumerating this process's windows...")
        title = window.title or "Shadow"
        for attempt in range(10):
            time.sleep(0.1)
            hwnd = _find_own_window(title)
            if hwnd:
                print(f"🔍 Method 2 (EnumWindows PID-filtered, attempt {attempt + 1}): Found {hex(hwnd)}")
                break

    # Method 2 already tried title match; if still no hwnd, retry with empty
    # title to trigger the largest-window fallback.
    if not hwnd:
        for attempt in range(5):
            time.sleep(0.1)
            hwnd = _find_own_window("")
            if hwnd:
                print(f"🔍 Method 2b (largest window fallback, attempt {attempt + 1}): Found {hex(hwnd)}")
                break

    # --- Optional: old blackout mode via STEALTH_MODE env var ---
    stealth_mode = (os.environ.get("STEALTH_MODE") or _ENV_FILE_VALUES.get("STEALTH_MODE") or "invisible").strip().lower()
    if stealth_mode == "blackout":
        print(f"🛡️ [BLACKOUT MODE] Applying WDA_MONITOR (0x{WDA_MONITOR:08X}) — black rectangle in capture")
        success = _user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR)
        if success:
            window_manager.set_window_handle(hwnd)
            window_manager.hide_from_taskbar()
            window_manager.start_screen_share_monitor()
            verify_protection(hwnd)
            return True
        else:
            error_code = ctypes.GetLastError()
            print(f"❌ FAILED: SetWindowDisplayAffinity failed! Error Code: {error_code}")
            return False

    if stealth_mode in ("hide", "hide-by-default", "invisible-hide"):
        # old hide-by-default branch (kept as opt-in)
        window_manager.set_window_handle(hwnd)
        window_manager.stealth_active = True
        window_manager.hide_from_taskbar()
        window_manager.set_always_on_top(True)
        window_manager.start_screen_share_monitor()
        print("✅ HIDE-BY-DEFAULT STEALTH MODE ENABLED")
        return True

    # Default "invisible": Cluely-style — window stays visible to the user but is
    # excluded from screen capture entirely (no black rectangle).
    print(f"🛡️ [INVISIBLE MODE] Applying WDA_EXCLUDEFROMCAPTURE (0x{WDA_EXCLUDEFROMCAPTURE:08X}) — visible to you, invisible in capture")
    success = _user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    window_manager.set_window_handle(hwnd)
    window_manager.hide_from_taskbar()
    window_manager.set_always_on_top(True)
    # Screen-share indicator monitor is NOT needed in invisible mode: WDA_EXCLUDEFROMCAPTURE
    # already excludes the window from capture, and hiding toast windows can cause
    # flicker/instability. Only enable in hide-by-default/blackout modes.
    if success:
        print("✅ INVISIBLE STEALTH MODE ENABLED (Cluely-style)")
        print("   📌 Window stays visible to you; absent from screen shares/recordings")
        print("   📌 No black rectangle — excluded from capture entirely")
        verify_protection(hwnd)
        return True
    else:
        error_code = ctypes.GetLastError()
        print(f"❌ FAILED: SetWindowDisplayAffinity failed! Error Code: {error_code}")
        print("   🚨 Falling back to hide-by-default mode")
        window_manager.stealth_active = True
        # hide on interview start still applies
        return True

def verify_protection(hwnd) -> Optional[bool]:
    """Verify that capture protection is actually applied.

    Returns True when the window's display affinity reads back as
    WDA_EXCLUDEFROMCAPTURE, False when it reads back as something else, and
    None when verification was not possible (API unavailable, call failed, or
    an unexpected error). Diagnostic only - this never raises and the result
    can safely be ignored.
    """
    try:
        # Try to get current display affinity (this is a read-only check)
        print(f"🔬 Verifying protection on window {hex(hwnd)}...")
        
        # Read the affinity back so this is a real confirmation, not a guess.
        if _HAS_GET_DISPLAY_AFFINITY:
            affinity = wintypes.DWORD(0)
            if _user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity)):
                if affinity.value == WDA_EXCLUDEFROMCAPTURE:
                    print(f"✅ CONFIRMED: display affinity is WDA_EXCLUDEFROMCAPTURE (0x{affinity.value:08X})")
                    return True
                print(f"❌ MISMATCH: display affinity is 0x{affinity.value:08X}, expected 0x{WDA_EXCLUDEFROMCAPTURE:08X}")
                print("   🚨 WARNING: Window may still be visible in screen recordings!")
                return False
            print(f"⚠️ GetWindowDisplayAffinity failed (Error Code: {ctypes.GetLastError()}) - falling back to handle check")
        else:
            print("⚠️ GetWindowDisplayAffinity unavailable on this system - falling back to handle check")

        # Fallback (previous behaviour): a valid handle is weak evidence only.
        is_window_valid = _user32.IsWindow(hwnd)
        if is_window_valid:
            print("✅ Window handle is valid - protection likely applied")
        else:
            print("❌ Window handle is invalid - protection may have failed")
        return None
            
    except Exception as e:
        print(f"⚠️ Could not verify protection: {e}")


# --- Example Usage (for testing this module directly) ---
if __name__ == '__main__':
    print("Running window_manager.py in test mode...")

    # Create a pywebview window for testing purposes
    test_window = webview.create_window(
        'Shadow Stealth Test',
        html='<h1>This window should be black in screen recordings.</h1>',
        width=800,
        height=600
    )

    # Hook our protection function to the 'shown' event. This is critical.
    # The 'shown' event fires after the window is created and visible, ensuring
    # that a window handle exists.
    test_window.events.shown += lambda: apply_capture_protection(test_window)

    # Start the GUI event loop
    webview.start()
# This function is not called if DEV_MODE in main.py is True
    print("--- Running window_manager.py in test mode ---")