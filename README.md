# OpenShaker

OpenShaker is a low-cost, flexure-guided vibration platform for fluid-mechanics experiments. It uses an affordable base shaker, a compliant stinger, and two disk flexures to reduce unwanted horizontal motion so that the bath moves predominantly in the vertical direction.

The project is designed to be reproducible and adaptable. This repository contains the 3D-print files, mechanical models, flexure geometry, control and analysis code, parts information, and build documentation needed to reproduce the current system.

<p align="center">
  <img src="https://github.com/user-attachments/assets/7f919fe4-374f-42e0-b600-63f82a08b39d" alt="Assembled OpenShaker system" width="760">
</p>

> [!WARNING]
> OpenShaker combines moving hardware, a power amplifier, fabricated spring-steel flexures, power tools, and nearby liquids. Read the [safety guidance](https://github.com/harrislab-brown/OpenShaker/wiki/1.-Safety) before fabrication or operation. Inspect and tighten the assembly before every run, keep electronics dry, know how to stop the amplifier and software quickly, and begin new tests with conservative settings.

## How the system works

1. A 50 W base shaker, driven by an external amplifier, supplies the vibration.
2. A thin music-wire stinger transfers vertical motion while remaining compliant in the horizontal plane.
3. Two spiral disk flexures guide the bath assembly and resist planar motion.
4. Two bath-mounted LSM6DS3 accelerometers measure the response at separate locations.
5. A VibeCheck controller and the supplied Python code adjust drive amplitude to reach a target Bath 1 Z-axis acceleration while recording both sensors for later comparison.

This arrangement is intended to provide a defined and repeatable input for experiments involving vertically forced fluids. It is a research platform under active development, not a calibrated commercial vibration table.

## Start here

The [OpenShaker wiki](https://github.com/harrislab-brown/OpenShaker/wiki) contains the complete build and operating instructions. New users should follow the pages in this order:

1. [Safety](https://github.com/harrislab-brown/OpenShaker/wiki/1.-Safety)
2. [Required Tools](https://github.com/harrislab-brown/OpenShaker/wiki/2.-Required-Tools)
3. [Complete Parts List](https://github.com/harrislab-brown/OpenShaker/wiki/3.-Complete-Parts-List)
4. [3D Printing Guide](https://github.com/harrislab-brown/OpenShaker/wiki/4.-3D-Printing-Guide)
5. [Aluminum Extrusion and Bass Shaker Preparation](https://github.com/harrislab-brown/OpenShaker/wiki/5.-Aluminum-Extrusion-and-Bass-Shaker-Preparation)
6. [Laser Cutting the Disk Flexures](https://github.com/harrislab-brown/OpenShaker/wiki/6.-Laser-Engraving-for-Disk-Flexure-Cutting)
7. [Shaker Assembly Guide](https://github.com/harrislab-brown/OpenShaker/wiki/7.-Shaker-Assembly-Guide)
8. [Python, PID, and Plotting Overview](https://github.com/harrislab-brown/OpenShaker/wiki/8.-Python,-PID,-and-Plotting-Overview)
9. [Shaker Performance](https://github.com/harrislab-brown/OpenShaker/wiki/9.-Shaker-Performance)
10. [Ideas and Future Work](https://github.com/harrislab-brown/OpenShaker/wiki/9.1-Ideas-and-Future-Work)

## Repository contents

| Location | Contents |
| --- | --- |
| [`3D Print STLs`](https://github.com/harrislab-brown/OpenShaker/tree/main/3D%20Print%20STLs) | Individual printable parts |
| [`Bambu Print Files`](https://github.com/harrislab-brown/OpenShaker/tree/main/Bambu%20Print%20Files) | Prepared Bambu Studio project files and build plates |
| [`Code`](https://github.com/harrislab-brown/OpenShaker/tree/main/Code) | Current sweep-control, data-collection, setup, and plotting scripts |
| [`Flexure Files`](https://github.com/harrislab-brown/OpenShaker/tree/main/Flexure%20Files) | Disk-flexure geometry for fabrication |
| [`Fusion Files`](https://github.com/harrislab-brown/OpenShaker/tree/main/Fusion%20Files) | Editable mechanical design files |
| [`THIRD SENSOR (Data Collection)`](https://github.com/harrislab-brown/OpenShaker/tree/main/THIRD%20SENSOR%20%28Data%20Collection%29) | Experimental three-sensor data-collection work |
| [Wiki](https://github.com/harrislab-brown/OpenShaker/wiki) | Parts, fabrication, assembly, software, safety, and performance documentation |

## Software quick start

The current workflow uses **Python 3.13** and three files in the [`Code`](https://github.com/harrislab-brown/OpenShaker/tree/main/Code) folder:

| File | Purpose |
| --- | --- |
| `PID_1.2 2AWin.py` | Controls the VibeCheck, runs a frequency sweep, regulates Bath 1 Z-axis acceleration with PID control, and records both bath sensors to CSV |
| `plot_1.2_A2Win.py` | Reads a sweep CSV and creates RMS, planar-response, drive-amplitude, planar-to-Z, and time-trace plots |
| `install_packages.py` | Installs and checks NumPy, pandas, Matplotlib, and pyserial |

`Shaker_Live_3.6.py` and files in `Code/Old` are archived and are not part of the current workflow.

### 1. Download the repository

Use **Code > Download ZIP** on GitHub, or clone the repository:

```bash
git clone https://github.com/harrislab-brown/OpenShaker.git
cd OpenShaker/Code
```

### 2. Create the Python environment

On macOS:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python install_packages.py
```

On Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe install_packages.py
```

### 3. Select and test the serial connection

Connect the VibeCheck with a USB data cable, list the available ports, and copy the correct device name into the `PORT` setting near the beginning of the PID script.

macOS:

```bash
python -m serial.tools.list_ports -v
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m serial.tools.list_ports -v
```

Only one program can use the VibeCheck serial port at a time. Close serial monitors and other programs connected to the device before running a sweep.

### 4. Review the test settings, then run

Before each test, check the frequency range, target acceleration, drive limit, sensor rate, bath-mass label, flexure orientation, stinger length, and spacer label near the beginning of the PID script.

macOS, with the environment activated:

```bash
python "PID_1.2 2AWin.py"
python "plot_1.2_A2Win.py"
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe "PID_1.2 2AWin.py"
.\.venv\Scripts\python.exe "plot_1.2_A2Win.py"
```

Run one command at a time. The plotting script can be used without the hardware connected. During a sweep, press `P` in the active plot window to pause or resume, press `S` to skip the current frequency, or close the plot window to stop and run the cleanup routine.

> [!NOTE]
> Some earlier downloads use the filename `PID_1.2 2A.py`. Use the exact filename present in your `Code` folder and keep filenames containing spaces inside quotation marks.

For the full Visual Studio Code setup, macOS and Windows instructions, output-file descriptions, and troubleshooting steps, see [Python, PID, and Plotting Overview](https://github.com/harrislab-brown/OpenShaker/wiki/8.-Python,-PID,-and-Plotting-Overview).

## Documented performance configuration

The comparison sweeps currently published in the wiki use the following configuration:

| Component or setting | Reference value |
| --- | --- |
| Flexures | Two three-arm spiral flexures, 180° relative orientation |
| Flexure material | 1095 blue-tempered spring steel, 0.010 in (0.254 mm) thick |
| Stinger | 100 mm of 0.033 in music wire |
| Threaded support rod | 110 mm long, 1/4 in diameter |
| Standard bath | 100 mm, approximately 0.070 kg total moving bath mass |
| Sensors | Two LSM6DS3 accelerometers on the bath assembly |
| Example sweep | 25–300 Hz in 5 Hz increments, 840 Hz sensor rate, 1.0 G peak target |

Initial comparisons also tested a larger 190 mm, approximately 0.130 kg bath and added base-shaker mass. Of the four documented sweeps, the standard 0.070 kg bath without added washers provided the best overall suppression of planar motion. A strong rocking mode was observed near 195 Hz with the larger bath. These results are preliminary closed-loop comparisons rather than complete transfer-function measurements; see [Shaker Performance](https://github.com/harrislab-brown/OpenShaker/wiki/9.-Shaker-Performance) for the figures, limitations, and interpretation.

The current Python guide shows `DEGREE = 270` as the default filename label, while the published comparison sweeps used 180° flexures. Update this and the other physical labels in the script so every output filename describes the assembly that was actually tested.

## Fabrication notes

- The frame uses 2020 aluminum extrusion. The documented cut list includes four 400 mm columns and fourteen 190 mm horizontal or shelf members.
- The standard build uses 19 unique printed part types and 32 required printed pieces, or 34 when both optional pieces are included.
- The original flexures were cut from 0.010 in 1095 blue-tempered spring steel using the supplied 60 mm disk-flexure geometry.
- Flexure material, thickness, cutting quality, bath mass, and assembly alignment can all change the system response. Treat substitutions as new configurations that require cautious testing.

## Data produced by a sweep

The PID script creates a timestamped CSV containing:

- sample time;
- commanded frequency and drive amplitude;
- sensor channel (`0` for Bath 1 and `2` for Bath 2); and
- raw X-, Y-, and Z-axis acceleration in G.

The plotting script groups the data by frequency, calculates AC RMS response, compares the two Z-axis measurements, evaluates combined planar motion, and reports the planar-to-Z ratio. It also saves high-resolution sweep plots and paginated time traces.

## Project status and support

OpenShaker is under active development. The wiki describes the current two-bath-sensor workflow; the `THIRD SENSOR (Data Collection)` folder contains separate experimental work. Check the script settings and wiki before building or running the system because filenames, procedures, and reference configurations may continue to change.

If you find an error or have a reproducibility problem, [open a GitHub issue](https://github.com/harrislab-brown/OpenShaker/issues) and include:

- the step or script you were using;
- your operating system and Python version;
- the mechanical configuration and test settings; and
- the complete error message or relevant data figure.

## License

A project license has not yet been added to this repository. Until one is included, contact the maintainers before redistributing or adapting the project files.

## Acknowledgments

OpenShaker is being developed by the [Harris Lab at Brown University](https://github.com/harrislab-brown). The control and measurement workflow uses the VibeCheck platform.
