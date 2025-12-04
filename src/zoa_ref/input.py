"""Interactive input handling with history and custom key bindings."""

from pathlib import Path

import nest_asyncio
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

# Allow nested event loops (needed because Playwright's sync API uses asyncio)
nest_asyncio.apply()

HISTORY_FILE = Path.home() / ".zoa-ref" / "history"


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

    history = FileHistory(str(HISTORY_FILE))
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
