"""Global hotkey registration and terminal focus management (Windows only).

Provides:
- capture_hotkey(): Interactive key combo capture via ReadConsoleInput
- HotkeyManager: Background thread for global hotkey + focus stealing
- Persistence: Save/load/clear hotkey preference to disk
"""

import ctypes
import ctypes.wintypes as wt
import threading

import click

from .config import HOTKEY_PREF_FILE

# =============================================================================
# Win32 Constants
# =============================================================================

# Console input
STD_INPUT_HANDLE = -10
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
KEY_EVENT = 0x0001

# dwControlKeyState flags (from KEY_EVENT_RECORD)
RIGHT_ALT_PRESSED = 0x0001
LEFT_ALT_PRESSED = 0x0002
RIGHT_CTRL_PRESSED = 0x0004
LEFT_CTRL_PRESSED = 0x0008
SHIFT_PRESSED = 0x0010

# RegisterHotKey modifier flags
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

# Messages
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# ShowWindow
SW_RESTORE = 9

# Virtual key codes
VK_ESCAPE = 0x1B
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

# Modifier VK codes to ignore as the main key
_MODIFIER_VKS = {
    VK_SHIFT,
    VK_CONTROL,
    VK_MENU,
    VK_LSHIFT,
    VK_RSHIFT,
    VK_LCONTROL,
    VK_RCONTROL,
    VK_LMENU,
    VK_RMENU,
}

# VK code to display name mapping
_VK_NAMES: dict[int, str] = {
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x13: "Pause",
    0x14: "CapsLock",
    0x1B: "Esc",
    0x20: "Space",
    0x21: "PageUp",
    0x22: "PageDown",
    0x23: "End",
    0x24: "Home",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2C: "PrintScreen",
    0x2D: "Insert",
    0x2E: "Delete",
    # 0-9
    **{0x30 + i: str(i) for i in range(10)},
    # A-Z
    **{0x41 + i: chr(0x41 + i) for i in range(26)},
    # Numpad 0-9
    **{0x60 + i: f"Num{i}" for i in range(10)},
    0x6A: "Num*",
    0x6B: "Num+",
    0x6D: "Num-",
    0x6E: "Num.",
    0x6F: "Num/",
    # F1-F24
    **{0x70 + i: f"F{i + 1}" for i in range(24)},
    # OEM keys
    0xBA: ";",
    0xBB: "=",
    0xBC: ",",
    0xBD: "-",
    0xBE: ".",
    0xBF: "/",
    0xC0: "`",
    0xDB: "[",
    0xDC: "\\",
    0xDD: "]",
    0xDE: "'",
}


# =============================================================================
# Win32 Structures
# =============================================================================


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wt.BOOL),
        ("wRepeatCount", wt.WORD),
        ("wVirtualKeyCode", wt.WORD),
        ("wVirtualScanCode", wt.WORD),
        ("UnicodeChar", wt.WCHAR),
        ("dwControlKeyState", wt.DWORD),
    ]


class _EventUnion(ctypes.Union):
    _fields_ = [
        ("KeyEvent", KEY_EVENT_RECORD),
        ("_pad", ctypes.c_byte * 16),  # Other event types we don't use
    ]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventType", wt.WORD),
        ("Event", _EventUnion),
    ]


# =============================================================================
# Formatting
# =============================================================================


def _vk_name(vk: int) -> str:
    """Get display name for a virtual key code."""
    return _VK_NAMES.get(vk, f"0x{vk:02X}")


def format_hotkey(modifiers: int, vk_code: int) -> str:
    """Format RegisterHotKey modifiers + VK code as a display string.

    Args:
        modifiers: MOD_CONTROL | MOD_ALT | MOD_SHIFT flags
        vk_code: Virtual key code

    Returns:
        String like "Ctrl + Shift + F1"
    """
    parts = []
    if modifiers & MOD_CONTROL:
        parts.append("Ctrl")
    if modifiers & MOD_ALT:
        parts.append("Alt")
    if modifiers & MOD_SHIFT:
        parts.append("Shift")
    parts.append(_vk_name(vk_code))
    return " + ".join(parts)


def _control_state_to_modifiers(state: int) -> int:
    """Convert dwControlKeyState to RegisterHotKey modifier flags."""
    mods = 0
    if state & (LEFT_CTRL_PRESSED | RIGHT_CTRL_PRESSED):
        mods |= MOD_CONTROL
    if state & (LEFT_ALT_PRESSED | RIGHT_ALT_PRESSED):
        mods |= MOD_ALT
    if state & SHIFT_PRESSED:
        mods |= MOD_SHIFT
    return mods


# =============================================================================
# Key Capture
# =============================================================================


def capture_hotkey() -> tuple[int, int] | None:
    """Enter key listening mode and capture a hotkey combination.

    Reads raw console input events to detect modifier+key combos.
    Displays the current capture in real-time.

    State machine:
        EMPTY -> press combo -> CAPTURED
        CAPTURED -> Enter -> return (modifiers, vk_code)
        CAPTURED -> Esc -> EMPTY
        EMPTY -> Esc -> return None (cancelled)

    Returns:
        (modifiers, vk_code) tuple for RegisterHotKey, or None if cancelled.
    """
    kernel32 = ctypes.windll.kernel32

    # Get console input handle
    h_input = kernel32.GetStdHandle(STD_INPUT_HANDLE)

    # Save original console mode
    original_mode = wt.DWORD()
    kernel32.GetConsoleMode(h_input, ctypes.byref(original_mode))

    # Set raw mode: disable line input, echo, and processed input (Ctrl+C)
    raw_mode = original_mode.value & ~(
        ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT | ENABLE_PROCESSED_INPUT
    )
    kernel32.SetConsoleMode(h_input, raw_mode)

    captured_modifiers = 0
    captured_vk = 0
    has_capture = False

    click.echo("Listening for hotkey... (Esc to cancel)")
    click.echo("Press a key combination (modifier + key), then Enter to confirm.")
    click.echo()
    _show_capture(None)

    try:
        record = INPUT_RECORD()
        events_read = wt.DWORD()

        while True:
            # Block until a console input event is available
            kernel32.ReadConsoleInputW(
                h_input, ctypes.byref(record), 1, ctypes.byref(events_read)
            )

            if record.EventType != KEY_EVENT:
                continue

            key_event = record.Event.KeyEvent
            if not key_event.bKeyDown:
                continue

            vk = key_event.wVirtualKeyCode
            control_state = key_event.dwControlKeyState

            # Escape handling
            if vk == VK_ESCAPE:
                if has_capture:
                    # Clear current capture
                    captured_modifiers = 0
                    captured_vk = 0
                    has_capture = False
                    _show_capture(None)
                else:
                    # Cancel
                    click.echo("\r" + " " * 60 + "\r", nl=False)
                    return None

            # Enter handling
            elif vk == VK_RETURN:
                if has_capture:
                    click.echo("\r" + " " * 60 + "\r", nl=False)
                    return (captured_modifiers, captured_vk)
                # Ignore Enter when nothing captured

            # Skip bare modifier keys
            elif vk in _MODIFIER_VKS:
                continue

            # Capture a key combo
            else:
                mods = _control_state_to_modifiers(control_state)
                if mods == 0:
                    # Require at least one modifier
                    _show_capture(
                        None, hint="Need at least one modifier (Ctrl/Alt/Shift)"
                    )
                    continue
                captured_modifiers = mods
                captured_vk = vk
                has_capture = True
                _show_capture(format_hotkey(mods, vk))

    finally:
        # Restore original console mode
        kernel32.SetConsoleMode(h_input, original_mode.value)


def _show_capture(combo: str | None, hint: str | None = None) -> None:
    """Update the capture display line in-place."""
    if combo:
        text = (
            f"  Captured: {click.style(combo, bold=True)}  (Enter=confirm, Esc=clear)"
        )
    elif hint:
        text = f"  {hint}"
    else:
        text = "  Waiting for key combo..."
    # Pad to overwrite previous content, use \r to stay on same line
    click.echo(f"\r{text:<70}", nl=False)


# =============================================================================
# HotkeyManager
# =============================================================================


class HotkeyManager:
    """Manages a global hotkey that brings the console to the foreground.

    Uses a background daemon thread running a Win32 message pump.
    Thread-safe registration/unregistration.
    """

    _HOTKEY_ID = 0x0001

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._registered = False
        self._modifiers: int = 0
        self._vk_code: int = 0
        self._console_hwnd = None
        self._ready_event = threading.Event()

    @property
    def is_registered(self) -> bool:
        return self._registered

    @property
    def current_hotkey_display(self) -> str | None:
        """Human-readable string of current hotkey, or None."""
        if not self._registered:
            return None
        return format_hotkey(self._modifiers, self._vk_code)

    def register(self, modifiers: int, vk_code: int) -> bool:
        """Register a global hotkey. Unregisters any existing one first.

        Args:
            modifiers: MOD_CONTROL | MOD_ALT | MOD_SHIFT flags
            vk_code: Virtual key code

        Returns:
            True if registration succeeded.
        """
        if self._registered:
            self.unregister()

        self._modifiers = modifiers
        self._vk_code = vk_code
        self._console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()

        if not self._console_hwnd:
            return False

        self._ready_event.clear()

        self._thread = threading.Thread(
            target=self._message_pump,
            daemon=True,
        )
        self._thread.start()

        # Wait for the pump thread to confirm registration
        if not self._ready_event.wait(timeout=3.0):
            return False
        return self._registered

    def unregister(self):
        """Unregister the current hotkey and stop the message pump."""
        if self._thread and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=2.0)
        self._registered = False
        self._thread = None
        self._thread_id = None

    def cleanup(self):
        """Clean shutdown. Call from interactive mode's finally block."""
        self.unregister()

    def _message_pump(self):
        """Background thread: register hotkey and pump Win32 messages."""
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        result = ctypes.windll.user32.RegisterHotKey(
            None,
            self._HOTKEY_ID,
            self._modifiers | MOD_NOREPEAT,
            self._vk_code,
        )
        self._registered = bool(result)
        self._ready_event.set()

        if not result:
            return

        msg = wt.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self._bring_to_foreground()

        # Cleanup on thread exit
        ctypes.windll.user32.UnregisterHotKey(None, self._HOTKEY_ID)
        self._registered = False

    def _bring_to_foreground(self):
        """Bring the console window to the foreground."""
        hwnd = self._console_hwnd
        if not hwnd:
            return

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        fg_hwnd = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
        our_tid = kernel32.GetCurrentThreadId()

        # Attach input threads to bypass focus-stealing prevention
        attached = False
        if fg_tid != our_tid:
            attached = bool(user32.AttachThreadInput(fg_tid, our_tid, True))

        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)

        if attached:
            user32.AttachThreadInput(fg_tid, our_tid, False)


# =============================================================================
# Persistence
# =============================================================================


def save_hotkey_preference(modifiers: int, vk_code: int) -> None:
    """Save hotkey preference to disk."""
    HOTKEY_PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOTKEY_PREF_FILE.write_text(f"{modifiers}:{vk_code}")


def load_hotkey_preference() -> tuple[int, int] | None:
    """Load saved hotkey preference.

    Returns:
        (modifiers, vk_code) or None if no preference or parse error.
    """
    try:
        if not HOTKEY_PREF_FILE.exists():
            return None
        text = HOTKEY_PREF_FILE.read_text().strip()
        if ":" not in text:
            return None
        parts = text.split(":", 1)
        modifiers = int(parts[0])
        vk_code = int(parts[1])
        if modifiers <= 0 or vk_code <= 0:
            return None
        return (modifiers, vk_code)
    except (ValueError, OSError):
        return None


def clear_hotkey_preference() -> None:
    """Remove saved hotkey preference."""
    try:
        HOTKEY_PREF_FILE.unlink(missing_ok=True)
    except OSError:
        pass
