#!/usr/bin/env python3
"""Build script to create a standalone zoa.exe with bundled Chromium browser."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_playwright_browser_path() -> Path | None:
    """Find the Playwright Chromium browser installation."""
    # Playwright stores browsers in %LOCALAPPDATA%/ms-playwright on Windows
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        return None

    pw_path = Path(local_app_data) / "ms-playwright"
    if not pw_path.exists():
        return None

    # Find chromium directory (e.g., chromium-1140)
    chromium_dirs = list(pw_path.glob("chromium-*"))
    if not chromium_dirs:
        return None

    # Use the latest version
    chromium_dirs.sort(reverse=True)
    return chromium_dirs[0]


def main():
    project_root = Path(__file__).parent
    dist_dir = project_root / "dist"
    build_dir = project_root / "build"
    src_dir = project_root / "src"

    print("=== ZOA Reference CLI Build Script ===\n")

    # Step 1: Ensure we're in a venv with dependencies
    print("[1/5] Checking dependencies...")
    for package in ["click", "playwright"]:
        if importlib.util.find_spec(package) is None:
            print(f"Missing dependency: {package}")
            print("Please install dependencies first:")
            print("  pip install -e .")
            print("  playwright install chromium")
            sys.exit(1)

    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller not found. Installing...")
        # Try uv first (faster), fall back to pip
        try:
            subprocess.run(["uv", "pip", "install", "pyinstaller>=6.0.0"], check=True)
        except FileNotFoundError:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "pyinstaller>=6.0.0"],
                check=True,
            )

    # Step 2: Check for Chromium browser
    print("[2/5] Locating Playwright Chromium browser...")
    browser_path = get_playwright_browser_path()
    if not browser_path:
        print("Chromium not found. Installing...")
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"], check=True
        )
        browser_path = get_playwright_browser_path()
        if not browser_path:
            print("ERROR: Failed to install Chromium")
            sys.exit(1)

    print(f"   Found: {browser_path}")

    # Step 3: Clean previous builds
    print("[3/5] Cleaning previous builds...")
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    if build_dir.exists():
        shutil.rmtree(build_dir)

    # Step 4: Run PyInstaller
    print("[4/5] Building executable with PyInstaller...")
    print("   (This may take several minutes...)")

    # Create a simple entry point script with multiprocessing freeze support
    entry_script = project_root / "_zoa_entry.py"
    entry_script.write_text('''"""Entry point for PyInstaller build."""
import multiprocessing

# CRITICAL: Must be called before any other imports that use multiprocessing
# This is required for PyInstaller to work with multiprocessing on Windows
if __name__ == "__main__":
    multiprocessing.freeze_support()

    from zoa_ref.cli import main
    main()
''')

    # PyInstaller command
    pyinstaller_args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=zoa",
        "--onedir",  # Create a folder (faster startup than onefile)
        "--console",  # Console application
        "--noconfirm",  # Overwrite without asking
        f"--add-data={browser_path};chromium",  # Bundle Chromium
        "--hidden-import=playwright",
        "--hidden-import=playwright.sync_api",
        "--hidden-import=playwright._impl",
        "--hidden-import=playwright._impl._api_types",
        "--hidden-import=click",
        "--hidden-import=pypdf",
        "--hidden-import=pypdf._crypt_providers",
        "--hidden-import=pypdf._crypt_providers._fallback",
        "--hidden-import=prompt_toolkit",
        "--hidden-import=nest_asyncio",
        "--hidden-import=greenlet",
        "--collect-submodules=playwright",
        "--collect-data=playwright",
        f"--paths={src_dir}",
        str(entry_script),
    ]

    result = subprocess.run(pyinstaller_args, cwd=project_root)

    # Clean up entry script
    entry_script.unlink(missing_ok=True)

    if result.returncode != 0:
        print("ERROR: PyInstaller failed")
        sys.exit(1)

    # Step 5: Report results
    print("\n[5/5] Build complete!")
    exe_path = dist_dir / "zoa" / "zoa.exe"
    if exe_path.exists():
        # Calculate total folder size
        folder_size = sum(
            f.stat().st_size for f in (dist_dir / "zoa").rglob("*") if f.is_file()
        )
        folder_size_mb = folder_size / (1024 * 1024)

        print(f"\n   Output folder: {dist_dir / 'zoa'}")
        print(f"   Total size: {folder_size_mb:.1f} MB")
        print("\n   To distribute:")
        print("   1. Zip the entire 'dist/zoa' folder")
        print("   2. Users extract and run zoa.exe from the folder")
        print("\n   Test with: dist\\zoa\\zoa.exe --help")
    else:
        print("WARNING: Executable not found at expected location")
        print("Check the build output above for errors.")


if __name__ == "__main__":
    main()
