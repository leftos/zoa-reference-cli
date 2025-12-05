"""Interactive input handling with history and custom key bindings."""

from pathlib import Path

import nest_asyncio
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

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
    @bindings.add('escape', 'escape')
    def double_escape(event):
        """Clear the input buffer on double escape."""
        event.current_buffer.reset()

    return bindings


def create_prompt_session() -> PromptSession:
    """Create a prompt session with history and custom key bindings.

    Features:
    - Persistent command history across sessions
    - Up/Down arrows recall previous commands
    - If text is in buffer when pressing up, it's preserved for return with down
    - Double escape clears the buffer
    - Ctrl+Left/Right moves cursor by word (built-in)
    """
    # Ensure history directory exists
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    history = NoDuplicatesFileHistory(str(HISTORY_FILE))
    bindings = create_key_bindings()

    return PromptSession(
        history=history,
        key_bindings=bindings,
        enable_history_search=True,  # Ctrl+R for reverse history search
    )


def prompt_with_history(session: PromptSession, prompt_text: str = "zoa> ") -> str | None:
    """Prompt for input with history support.

    Returns the input string, or None if the user pressed Ctrl+C or Ctrl+D.
    """
    try:
        return session.prompt(prompt_text)
    except (EOFError, KeyboardInterrupt):
        return None
