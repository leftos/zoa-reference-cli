"""Interactive input handling with history and custom key bindings."""

import sys
from pathlib import Path

import nest_asyncio
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

# For single-key input on Windows
if sys.platform == "win32":
    import msvcrt

# Allow nested event loops (needed because Playwright's sync API uses asyncio)
nest_asyncio.apply()

HISTORY_FILE = Path.home() / ".zoa-ref" / "history"


QUIT_ALIASES = frozenset(("quit", "exit", "q"))


class NoDuplicatesFileHistory(FileHistory):
    """File-backed history that removes duplicates, keeping most recent."""

    def store_string(self, string: str) -> None:
        """Store a string in history, removing any existing duplicate."""
        # Note: append_string() already inserted the string at position 0
        # before calling this method. We need to remove duplicates at other
        # positions, not at position 0.

        # Never store quit aliases in history
        if string.lower() in QUIT_ALIASES:
            # Remove from memory since append_string already added it
            if self._loaded_strings and self._loaded_strings[0] == string:
                self._loaded_strings.pop(0)
            return

        # Remove duplicate if present at position > 0 (not the one just added)
        for i in range(1, len(self._loaded_strings)):
            if self._loaded_strings[i] == string:
                self._loaded_strings.pop(i)
                break

        # Write to file
        super().store_string(string)


def create_key_bindings() -> KeyBindings:
    """Create custom key bindings for the prompt."""
    bindings = KeyBindings()

    # Track escape press for double-escape detection
    @bindings.add("escape", "escape")
    def double_escape(event):
        """Clear the input buffer on double escape."""
        event.current_buffer.reset()

    return bindings


def create_prompt_session(
    completer: Completer | None = None,
    history: FileHistory | None = None,
) -> PromptSession:
    """Create a prompt session with history, key bindings, and optional autocomplete.

    Args:
        completer: Optional prompt_toolkit Completer for tab completion.
        history: Optional FileHistory instance. If None, creates default history.

    Features:
    - Persistent command history across sessions
    - Up/Down arrows recall previous commands
    - If text is in buffer when pressing up, it's preserved for return with down
    - Double escape clears the buffer
    - Ctrl+Left/Right moves cursor by word (built-in)
    - Tab completion (if completer provided)
    - Inline auto-suggest from history (fish-style, press right arrow to accept)
    """
    # Ensure history directory exists
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    if history is None:
        history = NoDuplicatesFileHistory(str(HISTORY_FILE))
    bindings = create_key_bindings()

    return PromptSession(
        history=history,
        key_bindings=bindings,
        enable_history_search=True,  # Ctrl+R for reverse history search
        completer=completer,
        complete_while_typing=True,
        auto_suggest=AutoSuggestFromHistory(),
    )


def prompt_with_history(
    session: PromptSession, prompt_text: str = "zoa> "
) -> str | None:
    """Prompt for input with history support.

    Returns the input string, or None if the user pressed Ctrl+C or Ctrl+D.
    """
    try:
        return session.prompt(prompt_text)
    except (EOFError, KeyboardInterrupt):
        return None


def prompt_single_choice(
    num_choices: int,
    prompt_text: str = "Enter number to select (or 'q' to cancel): ",
) -> int | None:
    """Prompt user to select from a numbered list.

    For 1-9 choices, reads a single keypress (no Enter required).
    For 10+ choices, uses standard line input.

    Args:
        num_choices: Total number of choices available
        prompt_text: The prompt to display

    Returns:
        Selected index (1-based), or None if cancelled/invalid
    """
    if num_choices < 1:
        return None

    # For 10+ choices, use line input (requires Enter)
    if num_choices >= 10:
        try:
            choice = input(prompt_text).strip()
            if choice.lower() in ("q", "quit", ""):
                return None
            idx = int(choice)
            if 1 <= idx <= num_choices:
                return idx
            return None
        except (ValueError, EOFError, KeyboardInterrupt):
            return None

    # For 1-9 choices, use single keypress
    print(prompt_text, end="", flush=True)

    if sys.platform == "win32":
        # Windows: use msvcrt for single-key input
        while True:
            try:
                ch = msvcrt.getwch()
            except KeyboardInterrupt:
                print()
                return None

            if ch.lower() == "q":
                print("q")
                return None
            if ch in "\r\n":  # Enter pressed without selection
                print()
                return None
            if ch == "\x03":  # Ctrl+C
                print()
                return None
            if ch == "\x1b":  # Escape
                print()
                return None
            try:
                idx = int(ch)
                if 1 <= idx <= num_choices:
                    print(ch)
                    return idx
            except ValueError:
                pass  # Ignore non-numeric keys, keep waiting
    else:
        # Unix-like: use termios for single-key input
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)

                if ch.lower() == "q":
                    print("q")
                    return None
                if ch in "\r\n":
                    print()
                    return None
                if ch == "\x03":  # Ctrl+C
                    print()
                    return None
                if ch == "\x1b":  # Escape
                    print()
                    return None
                try:
                    idx = int(ch)
                    if 1 <= idx <= num_choices:
                        print(ch)
                        return idx
                except ValueError:
                    pass
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
