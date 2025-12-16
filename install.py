#!/usr/bin/env python3
"""
Installation script for ZOA Reference CLI.

Prepares a fresh Python installation with all required dependencies:
- Installs uv (if not present)
- Creates virtual environment
- Installs project dependencies
- Installs Playwright browsers

Usage:
    python install.py
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path


def print_step(msg: str) -> None:
    """Print a step message."""
    print(f"\n{'=' * 60}")
    print(f"  {msg}")
    print(f"{'=' * 60}")


def print_success(msg: str) -> None:
    """Print a success message."""
    print(f"  [OK] {msg}")


def print_error(msg: str) -> None:
    """Print an error message."""
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
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed with exit code {e.returncode}")
        if e.stdout:
            print(f"  stdout: {e.stdout}")
        if e.stderr:
            print(f"  stderr: {e.stderr}")
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


def is_uv_installed() -> bool:
    """Check if uv is installed and accessible."""
    return shutil.which("uv") is not None


def install_uv() -> bool:
    """Install uv package manager."""
    print_step("Installing uv package manager")

    if is_uv_installed():
        print_success("uv is already installed")
        return True

    system = platform.system().lower()

    try:
        if system == "windows":
            # Use PowerShell to install uv on Windows
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
                # Fallback: try pip install
                print_info("PowerShell install failed, trying pip...")
                run_command([sys.executable, "-m", "pip", "install", "uv"])
        else:
            # Use curl on Unix-like systems
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

        # Verify installation
        if is_uv_installed():
            print_success("uv installed successfully")
            return True

        # If uv still not found, it might be installed but not in PATH yet
        # Try using pip as fallback
        print_info("uv not in PATH, installing via pip as fallback...")
        run_command([sys.executable, "-m", "pip", "install", "uv"])

        print_success("uv installed via pip")
        return True

    except Exception as e:
        print_error(f"Failed to install uv: {e}")
        print_info("You can manually install uv from: https://docs.astral.sh/uv/")
        return False


def get_uv_command() -> list[str]:
    """Get the command to run uv."""
    if shutil.which("uv"):
        return ["uv"]
    # Fallback to running as Python module
    return [sys.executable, "-m", "uv"]


def create_venv() -> bool:
    """Create virtual environment using uv."""
    print_step("Creating virtual environment")

    project_dir = Path(__file__).parent
    venv_dir = project_dir / ".venv"

    if venv_dir.exists():
        print_info(f"Virtual environment already exists at {venv_dir}")
        print_success("Using existing virtual environment")
        return True

    try:
        uv = get_uv_command()
        run_command([*uv, "venv", str(venv_dir)])
        print_success(f"Virtual environment created at {venv_dir}")
        return True
    except Exception as e:
        print_error(f"Failed to create virtual environment: {e}")
        return False


def install_dependencies() -> bool:
    """Install project dependencies."""
    print_step("Installing project dependencies")

    project_dir = Path(__file__).parent

    try:
        uv = get_uv_command()
        run_command([*uv, "pip", "install", "-e", str(project_dir)])
        print_success("Dependencies installed")
        return True
    except Exception as e:
        print_error(f"Failed to install dependencies: {e}")
        return False


def get_venv_python() -> Path:
    """Get the path to the virtual environment Python executable."""
    project_dir = Path(__file__).parent
    venv_dir = project_dir / ".venv"

    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    else:
        return venv_dir / "bin" / "python"


def get_playwright_command() -> list[str]:
    """Get the command to run playwright."""
    project_dir = Path(__file__).parent
    venv_dir = project_dir / ".venv"

    if platform.system() == "Windows":
        playwright_path = venv_dir / "Scripts" / "playwright.exe"
    else:
        playwright_path = venv_dir / "bin" / "playwright"

    if playwright_path.exists():
        return [str(playwright_path)]

    # Fallback to running as module
    venv_python = get_venv_python()
    return [str(venv_python), "-m", "playwright"]


def install_playwright_browsers() -> bool:
    """Install Playwright browsers."""
    print_step("Installing Playwright browsers")

    print_info("This may take a few minutes...")

    try:
        playwright_cmd = get_playwright_command()
        run_command([*playwright_cmd, "install", "chromium"])
        print_success("Playwright Chromium browser installed")
        return True
    except Exception as e:
        print_error(f"Failed to install Playwright browsers: {e}")
        print_info("You can manually run: playwright install chromium")
        return False


def print_final_instructions() -> None:
    """Print final usage instructions."""
    project_dir = Path(__file__).parent

    if platform.system() == "Windows":
        zoa_cmd = r".\zoa"
    else:
        zoa_cmd = "./zoa"

    print_step("Installation complete!")
    print()
    print("  To use the CLI:")
    print()
    print(f"    cd {project_dir}")
    print(f"    {zoa_cmd} --help")
    print()
    print("  Example commands:")
    print()
    print(f"    {zoa_cmd} OAK CNDEL5           # Look up a chart")
    print(f"    {zoa_cmd} route SFO LAX        # Look up routes")
    print(f"    {zoa_cmd} atis SFO             # Get ATIS for an airport")
    print(f"    {zoa_cmd} sop OAK              # Open airport SOP")
    print(f"    {zoa_cmd} airline UAL          # Look up airline code")
    print(f"    {zoa_cmd}                      # Interactive mode")
    print()


def main() -> int:
    """Main installation routine."""
    print()
    print("  ZOA Reference CLI - Installation Script")
    print("  ========================================")

    # Step 1: Check Python version
    if not check_python_version():
        return 1

    # Step 2: Install uv
    if not install_uv():
        return 1

    # Step 3: Create virtual environment
    if not create_venv():
        return 1

    # Step 4: Install dependencies
    if not install_dependencies():
        return 1

    # Step 5: Install Playwright browsers
    if not install_playwright_browsers():
        # Non-fatal - user can do this manually
        print_info("Playwright browser installation failed, but you can continue")
        print_info("Run manually: .venv/Scripts/playwright install chromium")

    # Print final instructions
    print_final_instructions()

    return 0


if __name__ == "__main__":
    sys.exit(main())
