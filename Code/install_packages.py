r"""Install and check dependencies for the OpenShaker PID and plotting scripts.

Put this file beside the scripts and run it with the project's Python 3.13:
  Windows PowerShell: .\.venv\Scripts\python.exe install_packages.py
  macOS:              .venv/bin/python install_packages.py
An internet connection is required. No shaker connection is needed.
"""

import subprocess
import sys
from pathlib import Path

PACKAGES = ["numpy", "pandas", "matplotlib", "pyserial"]

# Check the libraries without importing the PID script (which opens hardware).
PACKAGE_CHECK = """
import io
import numpy as np
import pandas as pd
import serial
import serial.tools.list_ports
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec
from matplotlib.animation import FuncAnimation

# Exercise CSV reading, numerical operations, and PNG rendering in memory.
df = pd.read_csv(io.StringIO('X,Y,Z\\n1,2,3\\n4,5,6\\n'))
assert np.isfinite(df.to_numpy(dtype=float)).all()
fig, ax = plt.subplots()
ax.plot(df['X'], df['Z'])
image = io.BytesIO()
fig.savefig(image, format='png')
assert image.getvalue().startswith(b'\\x89PNG')
plt.close(fig)
print('Package and plot-saving checks passed.')
"""

# Tk is included with standard python.org Windows/macOS installations;
# it is not a pip package. Check both the file picker imports and plot canvas.
GUI_CHECK = """
import tkinter as tk
from tkinter import filedialog
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
root = tk.Tk()
root.withdraw()
try:
    fig = Figure()
    fig.add_subplot().plot([0, 1], [0, 1])
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.draw()
    root.update_idletasks()
    canvas.get_tk_widget().destroy()
finally:
    root.destroy()
print('Plot-window and file-picker checks passed.')
"""


def main():
    folder = Path(__file__).resolve().parent
    print(f"Code folder: {folder}", flush=True)
    print(f"Installing packages for: {sys.executable}", flush=True)
    print(f"Python version: {sys.version.split()[0]}", flush=True)
    if sys.version_info[:2] != (3, 13):
        print("The OpenShaker tutorial uses Python 3.13. "
              "For that setup, rerun this installer with the Python 3.13 .venv.",
              flush=True)
    try:
        pip_check = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if pip_check.returncode != 0:
            subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", *PACKAGES])
        subprocess.check_call([sys.executable, "-c", PACKAGE_CHECK])
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"\nInstallation or package check did not finish: {exc}", file=sys.stderr)
        print("Check your internet connection, then run this installer again. "
              "If it still fails, copy the last error and the Python path above "
              "when asking for help.", file=sys.stderr)
        return 1

    try:
        subprocess.check_call([sys.executable, "-c", GUI_CHECK])
    except (subprocess.CalledProcessError, OSError):
        print("\nPackages are installed, but the plot-window/file-picker check failed.",
              file=sys.stderr)
        print("Run this on your desktop computer. If the error mentions tkinter "
              "or Tcl/Tk, repair or reinstall Python 3.13 from python.org with "
              "Tcl/Tk support, then rerun this installer. Tkinter is not installed "
              "with pip. If it still fails, copy the last error and the Python "
              "path above when asking for help.", file=sys.stderr)
        return 1

    print("\nAll packages installed successfully!", flush=True)
    print("In VS Code, choose Python: Select Interpreter and select this exact Python:")
    print(sys.executable)
    print("Use that same Python to run the PID and plotting scripts.")
    print("The plotting script creates PID and PID2 beside the CSV when saving plots.")
    return 0


if __name__ == "__main__":
    result = main()
    # Keep the console open when launched by double-clicking.
    try:
        input("\nPress Enter to close...")
    except (EOFError, OSError):
        pass
    sys.exit(result)
