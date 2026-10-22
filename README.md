# CorridorKey 2.0 Workbench GUI

A desktop application for CorridorKey 2.0 AI video background removal and green screen keying.

## Quick Start

1. Clone or download this repository:

```bash
git clone https://github.com/greenyamao/CorridorKey-2.0-GUI.git
cd CorridorKey-2.0-GUI
```

If you do not use Git, click the green Code button above, choose Download ZIP, and extract the folder.

2. Double click `launch_gui.bat`

The launcher will automatically install all required packages, set up FFmpeg, and prepare the AI engine.

Alternatively, you can run from a terminal:

```bash
python run_gui.py
```

## First Launch

1. Click the yellow Download button in the top right corner to download the AI models (about 5 GB).
2. Once the download finishes, the application is ready to use.

## How to Use

1. Click `+ File` on the left to add your video.
2. Adjust keying and output settings on the right panel.
3. Click `Render` to process your video.

## Requirements

* Windows 10 or 11 (64 bit)
* NVIDIA graphics card with at least 8 GB VRAM
* Python 3.10, 3.11, or 3.12 installed with PATH enabled

## License

This GUI application is licensed under the MIT License.
