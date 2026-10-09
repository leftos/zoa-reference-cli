"""Stable, AIRAC-independent links to processed chart and SOP PDFs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from zoa_ref.cache import cleanup_old_airac_caches, link_stable_pdf

NAME = "ZOA_OAK_ILS_RWY_28R.pdf"


@pytest.fixture
def symlinks_supported(tmp_path: Path) -> None:
    """Skip a test when the platform refuses a symlink inside tmp_path."""
    target = tmp_path / "symlink-probe-target"
    target.write_bytes(b"probe")
    link = tmp_path / "symlink-probe-link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("platform does not support symlinks in tmp_path")


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("zoa_ref.cache.CACHE_DIR", tmp_path)
    return tmp_path


def _write_processed(cache_dir: Path, airac: str, name: str, data: bytes) -> Path:
    folder = cache_dir / "processed" / airac
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_bytes(data)
    return target


def test_link_created_in_current_folder(
    cache_dir: Path, symlinks_supported: None
) -> None:
    """The link lands in processed/current and serves the target's bytes."""
    target = _write_processed(cache_dir, "2609", NAME, b"2609-bytes")

    link = link_stable_pdf(target)

    assert link == cache_dir / "processed" / "current" / NAME
    assert link.read_bytes() == b"2609-bytes"


def test_relink_after_cycle_change_serves_new_cycle(
    cache_dir: Path, symlinks_supported: None
) -> None:
    """A later cycle's PDF replaces the previous cycle's link."""
    old = _write_processed(cache_dir, "2609", NAME, b"2609-bytes")
    link_stable_pdf(old)
    new = _write_processed(cache_dir, "2610", NAME, b"2610-bytes")

    link = link_stable_pdf(new)

    assert link.read_bytes() == b"2610-bytes"
    assert link.resolve() == new.resolve()


def test_relink_is_idempotent(cache_dir: Path, symlinks_supported: None) -> None:
    """Linking the same target twice leaves the symlink untouched."""
    target = _write_processed(cache_dir, "2609", NAME, b"2609-bytes")

    first = link_stable_pdf(target)
    second = link_stable_pdf(target)

    assert second == first
    assert second.is_symlink()
    assert second.resolve() == target.resolve()
    assert second.read_bytes() == b"2609-bytes"


def test_dangling_link_is_replaced(cache_dir: Path, symlinks_supported: None) -> None:
    """A symlink whose target is gone is replaced, not an error."""
    current = cache_dir / "processed" / "current"
    current.mkdir(parents=True, exist_ok=True)
    dangling = current / NAME
    dangling.symlink_to(cache_dir / "processed" / "2609" / NAME)
    target = _write_processed(cache_dir, "2610", NAME, b"2610-bytes")

    link = link_stable_pdf(target)

    assert link.read_bytes() == b"2610-bytes"
    assert link.resolve() == target.resolve()


def test_symlink_failure_falls_back_to_hardlink(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When symlinking is refused, a hardlink is created instead."""

    def _no_symlink(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError("symlinks unavailable")

    monkeypatch.setattr(Path, "symlink_to", _no_symlink)
    target = _write_processed(cache_dir, "2609", NAME, b"2609-bytes")

    link = link_stable_pdf(target)

    assert link.exists()
    assert not link.is_symlink()
    assert link.read_bytes() == b"2609-bytes"
    assert os.path.samefile(link, target)


def test_hardlink_failure_falls_back_to_copy(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When symlinking and hardlinking are refused, the file is copied."""

    def _no_symlink(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError("symlinks unavailable")

    def _no_hardlink(src: str, dst: str, *args: object, **kwargs: object) -> None:
        raise OSError("hardlinks unavailable")

    monkeypatch.setattr(Path, "symlink_to", _no_symlink)
    monkeypatch.setattr("zoa_ref.cache.os.link", _no_hardlink)
    target = _write_processed(cache_dir, "2609", NAME, b"2609-bytes")

    link = link_stable_pdf(target)

    assert link.read_bytes() == b"2609-bytes"
    assert not os.path.samefile(link, target)


def test_cleanup_removes_dangling_current_link(
    cache_dir: Path, symlinks_supported: None
) -> None:
    """cleanup drops a dangling current link and keeps a live one."""
    processed = cache_dir / "processed"
    live_target = processed / "keepme.pdf"
    live_target.parent.mkdir(parents=True, exist_ok=True)
    live_target.write_bytes(b"live-bytes")
    current = processed / "current"
    current.mkdir(parents=True, exist_ok=True)
    live_link = current / "keepme.pdf"
    live_link.symlink_to(live_target)
    dangling_link = current / "gone.pdf"
    dangling_link.symlink_to(processed / "does-not-exist.pdf")

    removed = cleanup_old_airac_caches()

    assert removed == 1
    assert not dangling_link.is_symlink()
    assert live_link.is_symlink()
    assert live_link.read_bytes() == b"live-bytes"
