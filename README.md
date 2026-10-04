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
| [`accelerometer_3_files)`](https://github.com/harrislab-brown/OpenShaker/tree/main/accelerometer_3_files%20(Data%20Collection)) | Experimental three-sensor data-collection work |
| [Wiki](https://github.com/harrislab-brown/OpenShaker/wiki) | Parts, fabrication, assembly, software, safety, and performance documentation |

## Software quick start

Go to 8. [Python, PID, and Plotting Overview](https://github.com/harrislab-brown/OpenShaker/wiki/8.-Python,-PID,-and-Plotting-Overview)

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
| Example sweep | 25–300 Hz in 5 Hz increments, 5000 Hz sensor rate, 1.0 G peak target |


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
