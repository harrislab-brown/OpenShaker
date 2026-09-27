"""Install dependencies for the plotting and PID scripts.

Run with: py install_packages.py
Requires Python 3 and an internet connection.
"""

import subprocess
import sys

PACKAGES = ["numpy", "pandas", "matplotlib", "pyserial"]


def main():
    print(f"Installing packages for: {sys.executable}", flush=True)
    try:
        pip_check = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if pip_check.returncode != 0:
            subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", *PACKAGES])
        subprocess.check_call([
            sys.executable,
            "-c",
            "import numpy, pandas, matplotlib, serial; "
            "print('All packages installed successfully!')",
        ])
        return 0
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"\nInstallation did not finish: {exc}", file=sys.stderr)
        print("Review the error above.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    result = main()
    # Keep the console open when this file is launched by double-clicking.
    try:
        input("\nPress Enter to close...")
    except (EOFError, OSError):
        pass
    sys.exit(result)
