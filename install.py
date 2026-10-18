#!/usr/bin/env python3
"""
Installation script for the ZOA Reference CLI.

Installs a snapshot of the app outside this repository with ``uv tool
install`` into a user bin directory that is already on PATH. The install
follows ``uv.lock``: the lock is exported to a constraints file and passed to
``uv tool install``, so the installed tool gets the same versions the tests
run against. An install stamp records the source hash and the installed
executable, so later runs only reinstall when the source has actually changed.

The script uses only the standard library: it must run on a bare system
Python 3.10+ before any project dependency exists, and never imports the
``zoa_ref`` package.

Usage:
    python install.py
"""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

STAMP_PATH = Path.home() / ".zoa-ref" / "install-stamp.json"

BLOCK_START = "# >>> zoa-reference-cli >>>"
BLOCK_END = "# <<< zoa-reference-cli <<<"


class InstallError(RuntimeError):
    """Raised when the CLI cannot be installed."""


def print_step(msg: str) -> None:
    """Print a step message."""
    print(f"\n{'=' * 60}")
    print(f"  {msg}")
    print(f"{'=' * 60}")


def print_success(msg: str) -> None:
    """Print a success message."""
    print(f"  [OK] {msg}")


def print_error(msg: str) -> None:
    """Print an error message to stderr."""
    print(f"  [ERROR] {msg}", file=sys.stderr)


def print_info(msg: str) -> None:
    """Print an info message."""
    print(f"  [INFO] {msg}")


def run_command(
    cmd: list[str], check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess:
    """Run a command and handle errors."""
    print(f"  Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            check=check,
            capture_output=capture,
            text=True,
        )
        return result
    except subprocess.CalledProcessError as exc:
        print_error(f"Command failed with exit code {exc.returncode}")
        if exc.stdout:
            print(f"  stdout: {exc.stdout}")
        if exc.stderr:
            print(f"  stderr: {exc.stderr}")
        raise


def check_python_version() -> bool:
    """Check that Python version is 3.10+."""
    print_step("Checking Python version")

    version = sys.version_info
    print_info(f"Python {version.major}.{version.minor}.{version.micro}")

    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print_error("Python 3.10 or higher is required")
        return False

    print_success("Python version OK")
    return True


def get_uv_path() -> Path | None:
    """Get the path to the uv executable, checking PATH and common install locations."""
    uv_in_path = shutil.which("uv")
    if uv_in_path:
        return Path(uv_in_path)

    system = platform.system().lower()
    if system != "windows":
        local_bin_uv = Path.home() / ".local" / "bin" / "uv"
        if local_bin_uv.exists():
            return local_bin_uv

    return None


def install_uv() -> bool:
    """Install the uv package manager."""
    print_step("Installing uv package manager")

    if get_uv_path() is not None:
        print_success("uv is already installed")
        return True

    system = platform.system().lower()

    try:
        if system == "windows":
            print_info("Installing uv via PowerShell...")
            result = subprocess.run(
                [
                    "powershell",
                    "-ExecutionPolicy",
                    "ByPass",
                    "-Command",
                    "irm https://astral.sh/uv/install.ps1 | iex",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print_info("PowerShell install failed, trying pip...")
                run_command([sys.executable, "-m", "pip", "install", "uv"])
        else:
            print_info("Installing uv via curl...")
            result = subprocess.run(
                ["curl", "-LsSf", "https://astral.sh/uv/install.sh"],
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                ["sh"],
                input=result.stdout,
                check=True,
                text=True,
            )

        if get_uv_path() is not None:
            print_success("uv installed successfully")
            return True

        print_error("uv installation completed but the executable was not found")
        return False

    except Exception as exc:
        print_error(f"Failed to install uv: {exc}")
        print_info("You can manually install uv from: https://docs.astral.sh/uv/")
        return False


def ensure_uv() -> list[str]:
    """Return the command that runs uv, installing uv first when it is missing.

    Returns:
        The uv command as a list of arguments.

    Raises:
        InstallError: If uv cannot be found and cannot be installed.
    """
    uv_path = get_uv_path()
    if uv_path is not None:
        return [str(uv_path)]

    if not install_uv():
        raise InstallError(
            "uv is required but could not be installed. Install it from "
            "https://docs.astral.sh/uv/ and run this script again."
        )

    uv_path = get_uv_path()
    if uv_path is None:
        raise InstallError(
            "uv was installed but is not on PATH. Open a new shell and run this "
            "script again, or install it from https://docs.astral.sh/uv/."
        )
    return [str(uv_path)]


def uv_default_bin_dir(uv: list[str]) -> Path:
    """Return uv's default tool bin directory."""
    result = subprocess.run(
        [*uv, "tool", "dir", "--bin"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def path_dirs_from_env() -> list[Path]:
    """Return the non-empty PATH entries as paths."""
    return [Path(entry) for entry in os.environ["PATH"].split(os.pathsep) if entry]


def _normalized_path(path: Path) -> str:
    """Return a comparable form of a path, ignoring case and trailing separators."""
    return os.path.normcase(os.path.abspath(str(path)))


def choose_bin_dir(
    uv_default: Path, home: Path, path_dirs: list[Path]
) -> tuple[Path, bool]:
    """Pick the first candidate bin directory that is already on PATH.

    Candidates are considered in order: the uv default tool bin directory,
    ``~/.local/bin`` and ``~/bin``. Only ``path_dirs`` is consulted, never the
    real environment.

    Args:
        uv_default: uv's default tool bin directory.
        home: The user's home directory.
        path_dirs: The PATH entries to compare against.

    Returns:
        A tuple of the chosen directory and whether it is on PATH. When no
        candidate is on PATH, the uv default directory is returned with False.
    """
    candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in (uv_default, home / ".local" / "bin", home / "bin"):
        key = _normalized_path(candidate)
        if key not in seen:
            seen.add(key)
            candidates.append(candidate)

    path_keys = {_normalized_path(entry) for entry in path_dirs}
    for candidate in candidates:
        if _normalized_path(candidate) in path_keys:
            return candidate, True
    return uv_default, False


def exe_name() -> str:
    """Return the installed executable's file name."""
    return "zoa.exe" if platform.system() == "Windows" else "zoa"


def _is_build_output(relative: Path) -> bool:
    """Return whether a path under the repo is generated by a build, not source."""
    parts = relative.parts
    in_generated_dir = any(part == "__pycache__" or part.endswith(".egg-info") for part in parts)
    return in_generated_dir or relative.suffix == ".pyc"


def source_hash(repo: Path) -> str:
    """Return a SHA-256 hash over the install inputs.

    The inputs are ``pyproject.toml``, ``uv.lock`` when it exists, and every
    file under ``src``. Files are visited in sorted order of their relative
    POSIX path, feeding the relative path followed by the file bytes. Build
    output is skipped: ``__pycache__`` and ``*.egg-info`` contents (setuptools
    writes the latter into ``src`` on every build) and ``*.pyc`` files.

    Args:
        repo: The repository root.

    Returns:
        The lowercase hexadecimal digest.
    """
    files = [repo / "pyproject.toml"]
    lock = repo / "uv.lock"
    if lock.is_file():
        files.append(lock)
    src = repo / "src"
    if src.is_dir():
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            if _is_build_output(path.relative_to(repo)):
                continue
            files.append(path)

    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(repo).as_posix()):
        digest.update(path.relative_to(repo).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def read_stamp(path: Path) -> dict | None:
    """Return the stamp stored at ``path``, or None when it is missing or invalid."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        print_info(f"Ignoring unreadable install stamp {path}: {exc}")
        return None
    if not isinstance(data, dict):
        print_info(f"Ignoring unreadable install stamp {path}: not a JSON object")
        return None
    return data


def write_stamp(path: Path, source_hash: str, exe: Path) -> None:
    """Write the install stamp with the source hash and executable path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"source_hash": source_hash, "exe": str(exe)}
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")


def constraints_path(stamp_path: Path) -> Path:
    """Return the constraints file written beside the install stamp."""
    return stamp_path.parent / "install-constraints.txt"


def export_constraints(uv: list[str], repo: Path, dest: Path) -> Path:
    """Export the locked requirements of ``repo`` to ``dest`` as constraints.

    Runs a frozen ``uv export``, so the file holds exactly the versions pinned
    in ``uv.lock``.

    Args:
        uv: The uv command.
        repo: The repository root whose lock to export.
        dest: The constraints file to write.

    Returns:
        ``dest``.

    Raises:
        InstallError: If ``uv export`` fails.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        *uv,
        "export",
        "--project",
        str(repo),
        "--frozen",
        "--no-dev",
        "--no-hashes",
        "--no-emit-project",
        "-o",
        str(dest),
    ]
    print_info(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise InstallError(
            f"`uv export` failed with exit code {result.returncode}: "
            f"{result.stderr.strip()}\n"
            "uv.lock must exist and be current; run `uv lock` in the repo."
        )
    return dest


def install_tool(uv: list[str], repo: Path, bin_dir: Path, constraints: Path) -> Path:
    """Install the project as a uv tool into ``bin_dir`` and return its executable.

    Args:
        uv: The uv command.
        repo: The repository root to install from.
        bin_dir: The tool bin directory uv should install into.
        constraints: The constraints file pinning dependency versions.

    Returns:
        The path to the installed executable.

    Raises:
        InstallError: If uv fails or the expected executable is missing.
    """
    env = dict(os.environ)
    env["UV_TOOL_BIN_DIR"] = str(bin_dir)
    cmd = [
        *uv,
        "tool",
        "install",
        "--reinstall",
        "--constraints",
        str(constraints),
        str(repo),
    ]
    print_info(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        raise InstallError(
            f"`uv tool install` failed with exit code {result.returncode}.\n"
            "If a zoa window or process is open, close it and retry "
            "(Windows locks the running executable).\n"
            "If uv reports an executable that it does not own, remove or rename "
            "it and retry."
        )

    exe = bin_dir / exe_name()
    if not exe.exists():
        raise InstallError(f"`uv tool install` succeeded but {exe} does not exist.")
    return exe


def ensure_installed(
    repo: Path, force: bool, stamp_path: Path = STAMP_PATH
) -> Path:
    """Return the installed executable, reinstalling only when the source changed.

    Args:
        repo: The repository root.
        force: Reinstall even when the stamp matches.
        stamp_path: The stamp file to read and write (a test seam).

    Returns:
        The path to the installed executable.

    Raises:
        InstallError: If the install cannot be completed.
    """
    current_hash = source_hash(repo)

    if not force:
        stamp = read_stamp(stamp_path)
        if stamp is not None and stamp.get("source_hash") == current_hash:
            stamped = stamp.get("exe")
            if isinstance(stamped, str) and Path(stamped).exists():
                return Path(stamped)

    uv = ensure_uv()
    constraints = export_constraints(uv, repo, constraints_path(stamp_path))
    bin_dir, on_path = choose_bin_dir(
        uv_default_bin_dir(uv), Path.home(), path_dirs_from_env()
    )
    exe = install_tool(uv, repo, bin_dir, constraints)
    write_stamp(stamp_path, current_hash, exe)
    if not on_path:
        offer_aliases(exe)
    return exe


def _block_text(body: list[str]) -> str:
    """Return the marker-delimited block text for ``body``."""
    lines = [BLOCK_START, *body, BLOCK_END]
    return "".join(f"{line}\n" for line in lines)


def upsert_block(text: str, body: list[str]) -> str:
    """Insert or replace the marker-delimited block in ``text``.

    Args:
        text: The existing profile text.
        body: The lines between the markers.

    Returns:
        The updated text. When both markers are present the block is replaced
        in place; otherwise the block is appended.
    """
    block = _block_text(body)
    lines = text.splitlines()
    if BLOCK_START in lines and BLOCK_END in lines:
        start = lines.index(BLOCK_START)
        end = lines.index(BLOCK_END, start)
        prefix = "".join(f"{line}\n" for line in lines[:start])
        suffix = "".join(f"{line}\n" for line in lines[end + 1 :])
        return prefix + block + suffix

    if text and not text.endswith("\n"):
        text += "\n"
    return text + block


def pwsh_alias_line(exe: Path) -> str:
    """Return a PowerShell alias line for ``exe``."""
    escaped = str(exe).replace("'", "''")
    return f"Set-Alias -Name zoa -Value '{escaped}'"


def bash_alias_line(exe: Path) -> str:
    """Return a Bash alias line for ``exe``."""
    return f"alias zoa='{exe.as_posix()}'"


def pwsh_profile_path() -> Path | None:
    """Return the current-user pwsh profile path, or None without pwsh."""
    pwsh = shutil.which("pwsh")
    if not pwsh:
        return None
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", "$PROFILE.CurrentUserAllHosts"],
        check=False,
        capture_output=True,
        text=True,
    )
    profile = result.stdout.strip()
    if result.returncode != 0 or not profile:
        return None
    return Path(profile)


def bash_profile_path() -> Path | None:
    """Return the user's Bash profile path, or None without bash."""
    if not shutil.which("bash"):
        return None
    return Path.home() / ".bashrc"


def _offer_one_alias(shell: str, profile: Path, line: str) -> None:
    """Offer to add one alias line to one profile file."""
    try:
        existing = profile.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""

    if _block_text([line]) in existing:
        print_info(f"{shell} alias already present in {profile}")
        return

    if not sys.stdin.isatty():
        print_info(f"Add this line to {profile}: {line}")
        return

    answer = input(f"  Add a 'zoa' alias to {profile}? [y/N] ")
    if answer.strip().lower() not in {"y", "yes"}:
        return

    profile.parent.mkdir(parents=True, exist_ok=True)
    with profile.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(upsert_block(existing, [line]))
    print_success(f"Alias added to {profile}; a new {shell} session picks it up.")


def offer_aliases(exe: Path) -> None:
    """Offer to add a ``zoa`` alias to each installed shell's profile."""
    print_info(f"{exe.parent} is not on PATH.")
    shells = [
        ("pwsh", pwsh_profile_path(), pwsh_alias_line(exe)),
        ("bash", bash_profile_path(), bash_alias_line(exe)),
    ]
    offered = False
    for shell, profile, line in shells:
        if profile is None:
            continue
        offered = True
        _offer_one_alias(shell, profile, line)
    if not offered:
        print_info(f"No supported shell found; run the tool directly: {exe}")


def main() -> int:
    """Install the CLI and print usage examples."""
    print()
    print("  ZOA Reference CLI - Installation Script")
    print("  ========================================")

    if not check_python_version():
        return 1

    repo = Path(__file__).resolve().parent
    try:
        exe = ensure_installed(repo, force=True)
    except InstallError as exc:
        print_error(str(exc))
        return 1

    print_step("Installation complete!")
    print()
    print(f"  Installed: {exe}")
    print()
    print("  Example commands:")
    print()
    print("    zoa OAK CNDEL5           # Look up a chart")
    print("    zoa route SFO LAX        # Look up routes")
    print("    zoa atis SFO             # Get ATIS for an airport")
    print("    zoa sop OAK              # Open airport SOP")
    print("    zoa airline UAL          # Look up airline code")
    print("    zoa                      # Interactive mode")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
