#!/usr/bin/env python3
"""Build script to create a standalone zoa-reference-cli binary with PyInstaller.

Cross-platform: supports Windows, Linux, and macOS. Produces a one-folder
bundle at ``dist/zoa-reference-cli-{platform}-{arch}/`` containing a
``zoa-reference-cli`` (or ``zoa-reference-cli.exe``) binary that users
can run directly.

Chromium is NOT bundled — the app downloads it on first run via
``src/zoa_ref/playwright_bootstrap.py``. This keeps release archives
under ~50 MB instead of ~500 MB.
"""

import importlib.util
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _platform_arch_slug() -> str:
    """Return a ``{os}-{arch}`` slug for naming the release archive."""
    system_map = {
        "Windows": "windows",
        "Linux": "linux",
        "Darwin": "macos",
    }
    os_name = system_map.get(platform.system(), platform.system().lower())

    machine = platform.machine().lower()
    arch_map = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    arch = arch_map.get(machine, machine)

    return f"{os_name}-{arch}"


def main() -> int:
    project_root = Path(__file__).parent
    dist_dir = project_root / "dist"
    build_dir = project_root / "build"
    src_dir = project_root / "src"
    slug = _platform_arch_slug()
    binary_name = "zoa-reference-cli"
    final_dir_name = f"{binary_name}-{slug}"

    print(f"=== ZOA Reference CLI Build Script ({slug}) ===\n")

    # Step 1: Verify runtime deps are present.
    print("[1/4] Checking dependencies...")
    for package in ("click", "playwright", "pypdf", "prompt_toolkit"):
        if importlib.util.find_spec(package) is None:
            print(f"Missing dependency: {package}")
            print("Install with: uv pip install -e '.[build]'")
            return 1

    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller not found. Install with: uv pip install -e '.[build]'")
        return 1

    # Step 2: Clean previous builds.
    print("[2/4] Cleaning previous builds...")
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    if build_dir.exists():
        shutil.rmtree(build_dir)

    # Step 3: Generate PyInstaller entry script with multiprocessing support
    # and run PyInstaller.
    print("[3/4] Building executable with PyInstaller...")
    entry_script = project_root / "_zoa_entry.py"
    entry_script.write_text(
        '"""Entry point for PyInstaller build."""\n'
        "import multiprocessing\n"
        "\n"
        "# CRITICAL: Must be called before any other imports that use\n"
        "# multiprocessing. Required for PyInstaller on Windows.\n"
        'if __name__ == "__main__":\n'
        "    multiprocessing.freeze_support()\n"
        "\n"
        "    from zoa_ref.cli import main\n"
        "    main()\n"
    )

    # Build with the binary named "zoa-reference-cli" — this produces
    # dist/zoa-reference-cli/zoa-reference-cli[.exe]. We then rename the
    # parent folder to include the platform slug for release archiving.
    pyinstaller_args = [
        sys.executable,
        "-m",
        "PyInstaller",
        f"--name={binary_name}",
        "--onedir",  # One-folder bundle — faster startup than --onefile
        "--console",
        "--noconfirm",
        # Pull in the full playwright package, including the node driver
        # files required for first-run Chromium install inside the frozen app.
        "--collect-all=playwright",
        "--hidden-import=click",
        "--hidden-import=pypdf",
        "--hidden-import=pypdf._crypt_providers",
        "--hidden-import=pypdf._crypt_providers._fallback",
        "--hidden-import=prompt_toolkit",
        "--hidden-import=nest_asyncio",
        "--hidden-import=greenlet",
        f"--paths={src_dir}",
        str(entry_script),
    ]

    try:
        result = subprocess.run(pyinstaller_args, cwd=project_root)
    finally:
        entry_script.unlink(missing_ok=True)

    if result.returncode != 0:
        print("ERROR: PyInstaller failed")
        return 1

    # Step 4: Rename dist/zoa-reference-cli ->
    # dist/zoa-reference-cli-{platform}-{arch}, then report.
    print("\n[4/4] Finalizing output...")
    built_dir = dist_dir / binary_name
    final_dir = dist_dir / final_dir_name
    if not built_dir.exists():
        print(f"ERROR: Expected PyInstaller output not found: {built_dir}")
        return 1

    if final_dir.exists():
        shutil.rmtree(final_dir)
    built_dir.rename(final_dir)

    exe_suffix = ".exe" if platform.system() == "Windows" else ""
    binary_path = final_dir / f"{binary_name}{exe_suffix}"
    folder_size = sum(f.stat().st_size for f in final_dir.rglob("*") if f.is_file())
    folder_size_mb = folder_size / (1024 * 1024)

    print(f"   Output:  {final_dir}")
    print(f"   Binary:  {binary_path}")
    print(f"   Size:    {folder_size_mb:.1f} MB")
    print(f"\n   Test with: {binary_path} --help")

    return 0


if __name__ == "__main__":
    sys.exit(main())
