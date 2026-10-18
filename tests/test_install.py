"""Tests for the out-of-repo installer and its alias helpers."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_install() -> ModuleType:
    """Load the repository-root ``install.py`` without importing the package."""
    spec = importlib.util.spec_from_file_location(
        "zoa_install", REPO_ROOT / "install.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


install = _load_install()


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Create a minimal repository tree with a pyproject and one source file."""
    repo = tmp_path / "repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n", newline="\n")
    (repo / "src" / "pkg" / "a.py").write_text("x = 1\n", newline="\n")
    return repo


@pytest.fixture
def install_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Wire ensure_installed to a fake install that writes its exe into tmp."""
    bin_dir = tmp_path / "bin"
    calls: list[tuple[list[str], Path, Path]] = []

    def fake_install_tool(uv: list[str], repo: Path, target: Path) -> Path:
        calls.append((uv, repo, target))
        target.mkdir(parents=True, exist_ok=True)
        exe = target / install.exe_name()
        exe.write_text("", newline="\n")
        return exe

    monkeypatch.setattr(install, "ensure_uv", lambda: ["uv"])
    monkeypatch.setattr(install, "uv_default_bin_dir", lambda uv: bin_dir)
    monkeypatch.setattr(install, "path_dirs_from_env", lambda: [bin_dir])
    monkeypatch.setattr(install, "install_tool", fake_install_tool)
    return bin_dir, calls


# choose_bin_dir


def test_choose_bin_dir_prefers_uv_default_on_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    uv_default = tmp_path / "uv-bin"
    result = install.choose_bin_dir(
        uv_default, home, [home / ".local" / "bin", uv_default]
    )
    assert result == (uv_default, True)


def test_choose_bin_dir_falls_back_to_local_bin(tmp_path: Path) -> None:
    home = tmp_path / "home"
    uv_default = tmp_path / "uv-bin"
    local_bin = home / ".local" / "bin"
    result = install.choose_bin_dir(uv_default, home, [local_bin])
    assert result == (local_bin, True)


def test_choose_bin_dir_falls_back_to_home_bin(tmp_path: Path) -> None:
    home = tmp_path / "home"
    uv_default = tmp_path / "uv-bin"
    home_bin = home / "bin"
    result = install.choose_bin_dir(uv_default, home, [home_bin])
    assert result == (home_bin, True)


def test_choose_bin_dir_none_on_path_returns_uv_default_false(tmp_path: Path) -> None:
    home = tmp_path / "home"
    uv_default = tmp_path / "uv-bin"
    result = install.choose_bin_dir(uv_default, home, [tmp_path / "elsewhere"])
    assert result == (uv_default, False)


def test_choose_bin_dir_ignores_case_and_trailing_separator(tmp_path: Path) -> None:
    home = tmp_path / "home"
    uv_default = tmp_path / "uv-bin"

    with_separator = Path(str(uv_default) + os.sep)
    assert install.choose_bin_dir(uv_default, home, [with_separator]) == (uv_default, True)

    if sys.platform == "win32":
        upper = Path(str(uv_default).upper())
        assert install.choose_bin_dir(uv_default, home, [upper]) == (uv_default, True)


# source_hash


def test_source_hash_stable(fake_repo: Path) -> None:
    assert install.source_hash(fake_repo) == install.source_hash(fake_repo)


def test_source_hash_changes_on_src_edit(fake_repo: Path) -> None:
    before = install.source_hash(fake_repo)
    (fake_repo / "src" / "pkg" / "a.py").write_text("x = 2\n", newline="\n")
    assert install.source_hash(fake_repo) != before


def test_source_hash_changes_on_pyproject_edit(fake_repo: Path) -> None:
    before = install.source_hash(fake_repo)
    (fake_repo / "pyproject.toml").write_text("[project]\nname = 'y'\n", newline="\n")
    assert install.source_hash(fake_repo) != before


def test_source_hash_ignores_pycache_and_pyc(fake_repo: Path) -> None:
    before = install.source_hash(fake_repo)
    cache = fake_repo / "src" / "pkg" / "__pycache__"
    cache.mkdir()
    (cache / "a.cpython-312.pyc").write_bytes(b"junk")
    (fake_repo / "src" / "pkg" / "stray.pyc").write_bytes(b"junk")
    assert install.source_hash(fake_repo) == before


def test_source_hash_ignores_egg_info(fake_repo: Path) -> None:
    before = install.source_hash(fake_repo)
    egg_info = fake_repo / "src" / "pkg.egg-info"
    egg_info.mkdir()
    (egg_info / "PKG-INFO").write_text("Metadata-Version: 2.1\n", encoding="utf-8")
    assert install.source_hash(fake_repo) == before


# upsert_block


def test_upsert_block_appends_to_empty() -> None:
    body = ["alias zoa='x'"]
    assert install.upsert_block("", body) == (
        "# >>> zoa-reference-cli >>>\n"
        "alias zoa='x'\n"
        "# <<< zoa-reference-cli <<<\n"
    )


def test_upsert_block_appends_after_existing_text() -> None:
    result = install.upsert_block("existing", ["line"])
    assert result.startswith("existing\n")
    assert install.BLOCK_START in result
    assert install.BLOCK_END in result


def test_upsert_block_replaces_existing_block_in_place() -> None:
    text = (
        f"before\n{install.BLOCK_START}\nold\n{install.BLOCK_END}\nafter\n"
    )
    result = install.upsert_block(text, ["new"])
    assert result == (
        f"before\n{install.BLOCK_START}\nnew\n{install.BLOCK_END}\nafter\n"
    )


def test_upsert_block_idempotent() -> None:
    once = install.upsert_block("existing", ["line"])
    assert install.upsert_block(once, ["line"]) == once


# alias lines


def test_bash_alias_line_uses_forward_slashes(tmp_path: Path) -> None:
    exe = tmp_path / "bin" / "zoa"
    line = install.bash_alias_line(exe)
    assert line == f"alias zoa='{exe.as_posix()}'"
    assert "\\" not in line


def test_pwsh_alias_line_quotes_path(tmp_path: Path) -> None:
    exe = tmp_path / "o'brien" / "zoa.exe"
    line = install.pwsh_alias_line(exe)
    assert line.startswith("Set-Alias -Name zoa -Value '")
    assert "o''brien" in line


# ensure_installed


def test_ensure_installed_skips_when_stamp_matches(
    fake_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "bin" / install.exe_name()
    exe.parent.mkdir()
    exe.write_text("", newline="\n")
    stamp = tmp_path / "stamp.json"
    stamp.write_text(
        json.dumps(
            {"source_hash": install.source_hash(fake_repo), "exe": str(exe)}
        ),
        encoding="utf-8",
    )

    def boom(*args, **kwargs):
        raise AssertionError("uv must not be touched when the stamp matches")

    monkeypatch.setattr(install, "install_tool", boom)
    monkeypatch.setattr(install, "ensure_uv", boom)

    assert install.ensure_installed(fake_repo, force=False, stamp_path=stamp) == exe


def test_ensure_installed_reinstalls_on_hash_mismatch(
    fake_repo: Path, tmp_path: Path, install_env
) -> None:
    bin_dir, calls = install_env
    stale_exe = tmp_path / "old" / install.exe_name()
    stale_exe.parent.mkdir()
    stale_exe.write_text("", newline="\n")
    stamp = tmp_path / "stamp.json"
    stamp.write_text(
        json.dumps({"source_hash": "stale", "exe": str(stale_exe)}),
        encoding="utf-8",
    )

    exe = install.ensure_installed(fake_repo, force=False, stamp_path=stamp)

    assert calls
    assert exe == bin_dir / install.exe_name()
    written = json.loads(stamp.read_text(encoding="utf-8"))
    assert written["source_hash"] == install.source_hash(fake_repo)
    assert written["exe"] == str(exe)


def test_ensure_installed_reinstalls_when_exe_missing(
    fake_repo: Path, tmp_path: Path, install_env
) -> None:
    _bin_dir, calls = install_env
    missing_exe = tmp_path / "gone" / install.exe_name()
    stamp = tmp_path / "stamp.json"
    stamp.write_text(
        json.dumps(
            {"source_hash": install.source_hash(fake_repo), "exe": str(missing_exe)}
        ),
        encoding="utf-8",
    )

    install.ensure_installed(fake_repo, force=False, stamp_path=stamp)

    assert calls


def test_ensure_installed_force_reinstalls(
    fake_repo: Path, tmp_path: Path, install_env
) -> None:
    _bin_dir, calls = install_env
    exe = tmp_path / "bin" / install.exe_name()
    exe.parent.mkdir()
    exe.write_text("", newline="\n")
    stamp = tmp_path / "stamp.json"
    stamp.write_text(
        json.dumps(
            {"source_hash": install.source_hash(fake_repo), "exe": str(exe)}
        ),
        encoding="utf-8",
    )

    install.ensure_installed(fake_repo, force=True, stamp_path=stamp)

    assert calls


def test_ensure_installed_offers_alias_when_not_on_path(
    fake_repo: Path, tmp_path: Path, install_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(install, "path_dirs_from_env", lambda: [])
    offered: list[Path] = []
    monkeypatch.setattr(install, "offer_aliases", offered.append)

    exe = install.ensure_installed(
        fake_repo, force=True, stamp_path=tmp_path / "stamp.json"
    )

    assert offered == [exe]


# install_tool


def test_install_tool_raises_on_uv_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=2)

    monkeypatch.setattr(install.subprocess, "run", fake_run)

    with pytest.raises(install.InstallError) as excinfo:
        install.install_tool(["uv"], tmp_path, tmp_path / "bin")

    message = str(excinfo.value)
    assert "2" in message
    assert "zoa" in message
    assert "close" in message.lower()


def test_install_tool_sets_uv_tool_bin_dir_and_no_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    captured: dict = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / install.exe_name()).write_text("", newline="\n")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(install.subprocess, "run", fake_run)

    exe = install.install_tool(["uv"], tmp_path / "repo", bin_dir)

    assert captured["cmd"] == [
        "uv",
        "tool",
        "install",
        "--reinstall",
        str(tmp_path / "repo"),
    ]
    assert "--force" not in captured["cmd"]
    assert captured["env"]["UV_TOOL_BIN_DIR"] == str(bin_dir)
    assert exe == bin_dir / install.exe_name()
