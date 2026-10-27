
# CorridorKey 2.0 Workbench GUI
A desktop application for CorridorKey 2.0 AI video background removal and green screen keying.
<img width="1280" height="756" alt="python_tRI5Bo6giI" src="https://github.com/user-attachments/assets/b1b381ae-e813-40e2-81ee-62c29fbb238a" />
Manually select what to cut out for problematic shots.
<img width="768" height="488" alt="python_hWr4i0xrlY" src="https://github.com/user-attachments/assets/476bfd59-7f46-4c41-97f6-cf09a19ff984" />
## Quick Start

1. Clone or download this repository:
```bash
git clone https://github.com/greenyamao/CorridorKey-2.0-GUI.git
```
2. Double click `launch_gui.bat`
Alternatively, you can run from a terminal:
```bash
python run_gui.py
```
## Issue
If you encounter a bug, run into an error, or have a feature request, please open an issue.

## Requirements

* **Operating System:** Windows 10 or 11 (64-bit)
* **GPU:** NVIDIA GeForce RTX 30-series or newer (RTX 30xx, RTX 40xx, RTX 50xx / Ampere, Ada Lovelace, Blackwell) with native `bfloat16` Tensor Core support.
  * At least 4 GB VRAM for footage up to 1440p (`Low GPU Memory` mode).
  * At least 6–8 GB VRAM for 4K (`Low GPU Memory` mode).
  * *Note:* Older GPUs (RTX 20-series, GTX 10-series/16-series, AMD Radeon, Intel Arc) are not supported because they lack hardware `bfloat16` execution units required by the vision transformer architecture.
* **Python:** Python 3.10, 3.11, or 3.12 with CUDA-enabled PyTorch installed
* **FFmpeg:** Installed and available on system PATH (handled automatically by `launch_gui.bat`)

## Acknowledgements & Core Engine

This GUI application is an independent frontend interface built to run alongside the core **[CorridorKey 2.0](https://github.com/nikopueringer/CorridorKey2.0)** engine created by Niko Pueringer, Zachary Harris, and Corridor Digital LLC.

* **CorridorKey 2.0 Engine:** [https://github.com/nikopueringer/CorridorKey2.0](https://github.com/nikopueringer/CorridorKey2.0)
* **Official Project & Plugin:** [https://corridorkey.com](https://corridorkey.com)
* **Model Weights (Hugging Face):** [https://huggingface.co/nikopueringer/corridorkey](https://huggingface.co/nikopueringer/corridorkey)

## License

* **GUI Code:** Licensed under the [MIT License](LICENSE).
* **Core Engine & Model Weights:** The underlying CorridorKey 2.0 engine (automatically downloaded to `./engine/`) and its model weights are licensed under the **[CorridorKey License (CC BY-NC-SA 4.0 with Additional Terms)](https://github.com/nikopueringer/CorridorKey2.0/blob/master/LICENSE)** by Corridor Digital LLC.
  * **Video Output:** The images and videos you produce with this tool are 100% yours and can be used for any personal or commercial project.
  * **Usage Restrictions:** You may not repackage, redistribute, or sell the CorridorKey engine or weights as a paid product, nor offer paid inference APIs using CorridorKey without a separate commercial agreement from Corridor Digital LLC.
