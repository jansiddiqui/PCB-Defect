# PCB Defect Detection and Classification

An AI-powered system to **automatically detect and classify defects on Printed Circuit Boards (PCBs)** using deep learning (EfficientNet-B0 fine-tuned on defect crops extracted from the DeepPCB dataset).

---

## Results

| Metric | Value |
|---|---|
| Validation Accuracy | **99.1%** |
| Average Inference Confidence | **98.2%** |
| Defect Classes | 6 |
| Training Samples (crops) | 2,337 |
| Validation Samples (crops) | 585 |

### Per-Class Accuracy (on test samples)

| Defect Class | Predicted Correctly | Confidence |
|---|---|---|
| Missing Hole | ✅ Yes | 99.8% |
| Mouse Bite | ✅ Yes | 96.5% |
| Open Circuit | ✅ Yes | 94.6% |
| Short | ✅ Yes | 99.7% |
| Spur | ✅ Yes | 98.5% |
| Spurious Copper | ✅ Yes | 100.0% |

---

## Defect Classes

| Class | Description |
|---|---|
| `Missing_hole` | A drill hole is absent from the board |
| `Mouse_bite` | Small notches bitten along the board edge |
| `Open_circuit` | A copper trace is broken/disconnected |
| `Short` | Two separate traces are accidentally connected |
| `Spur` | An unwanted copper protrusion on a trace |
| `Spurious_copper` | Extra copper present where none should be |

---

## Project Architecture

```
                    PCB Image (full resolution 3034x1586)
                           |
              +------------+------------+
              |                         |
    [Subtraction Pipeline]     [Annotation Bounding Boxes]
    align_images.py                 (.xml files)
    subtraction_pipeline.py              |
              |                    Defect Crop
    Binary Mask (output_masks/)   (65x65 + padding)
                                         |
                               [EfficientNet-B0]
                               (fine-tuned classifier)
                                         |
                             Defect Class + Confidence
```

---

## Project Structure

```
PCB-Defect/
|
|-- PCB_DATASET/
|   |-- images/                  # Raw defect images (6 class folders)
|   |   |-- Missing_hole/        # 115 images
|   |   |-- Mouse_bite/          # 115 images
|   |   |-- Open_circuit/        # 116 images
|   |   |-- Short/               # 116 images
|   |   |-- Spur/                # 109 images
|   |   `-- Spurious_copper/     # 116 images
|   |-- Annotations/             # Pascal VOC XML bounding boxes (per class)
|   |-- PCB_USED/                # Golden (defect-free) reference boards
|   `-- rotation/                # Rotated reference variants
|
|-- output_masks/                # Generated binary diff masks (by run_all.py)
|
|-- align_images.py              # ORB feature matching + homography alignment
|-- subtraction_pipeline.py      # Image subtraction to detect anomaly regions
|-- run_all.py                   # Batch pipeline: process all 687 images
|-- train_model.py               # 2-phase EfficientNet-B0 training script
|-- predict_defect.py            # Single image inference with confidence scores
|-- pcb_defect_model.pth         # Trained model weights (99.1% val accuracy)
|-- requirements.txt             # Python dependencies
`-- README.md                    # This file
```

---

## How It Works

### Step 1 — Image Alignment (`align_images.py`)
Uses **ORB feature matching** and **homography transformation** to align each defect image with its golden reference board. This removes positional differences caused by camera angle or board placement.

### Step 2 — Subtraction Pipeline (`subtraction_pipeline.py`)
Subtracts the aligned defect image from the reference image to produce a **binary mask** highlighting anomalous regions. Applies:
- Gaussian blur to reduce noise
- Histogram equalization to normalize brightness
- Morphological open/close operations to clean up the mask
- Contour area filtering (50–5000 px²) to remove tiny artifacts

### Step 3 — Training (`train_model.py`)
**Key insight:** Defect regions are tiny (~65×65 px) in full 3034×1586 images. When resized to 224×224, defects shrink to ~5 pixels — invisible to a CNN. The fix is to **crop each bounding box from the XML annotations** and train on those crops directly.

Uses a **2-phase transfer learning** approach:
- **Phase 1 (5 epochs):** Backbone frozen, train only classifier head at `lr=1e-3`
- **Phase 2 (15 epochs):** Backbone unfrozen, full fine-tuning at `lr=1e-4`

### Step 4 — Inference (`predict_defect.py`)
Reads the Pascal VOC XML annotation to find bounding boxes → crops each defect region → passes through EfficientNet-B0 → returns class + confidence score for each region plus an overall averaged prediction.

---

## Setup

### Prerequisites
- Python 3.9+
- ~2 GB RAM minimum
- GPU optional (CUDA accelerates training significantly)

### Install Dependencies

```bash
pip install -r requirements.txt
```

**Dependencies:**
```
torch>=2.0.0
torchvision>=0.15.0
opencv-python>=4.7.0
numpy>=1.23.0
Pillow>=9.0.0
tqdm>=4.64.0
```

---

## Usage

### 1. Generate Difference Masks (optional preprocessing)

Runs the subtraction pipeline on all 687 images, saving binary masks to `output_masks/`.

```bash
python run_all.py
```

Expected output:
```
Missing_hole: 100%|##########| 115/115
Mouse_bite:   100%|##########| 115/115
...
Done. Processed: 687 | Skipped: 0
```

---

### 2. Train the Model

> Skip this step if `pcb_defect_model.pth` already exists.

```bash
python -u train_model.py
```

Expected output:
```
Total defect crops: 2922
Train crops: 2337 | Val crops: 585
Using device: cpu

PHASE 1 — Classifier warm-up (backbone FROZEN, lr=0.001)
Epoch [01/5]  Loss: 1.45  Train Acc: 45.9%  Val Acc: 49.4%
...
Epoch [05/5]  Loss: 0.98  Train Acc: 64.7%  Val Acc: 59.0%

PHASE 2 — Full fine-tuning (backbone UNFROZEN, lr=0.0001)
Epoch [01/15]  Loss: 0.48  Train Acc: 83.3%  Val Acc: 88.7%
Epoch [02/15]  Loss: 0.15  Train Acc: 95.4%  Val Acc: 96.8%
Epoch [03/15]  Loss: 0.09  Train Acc: 97.3%  Val Acc: 97.4%
Epoch [04/15]  Loss: 0.08  Train Acc: 98.1%  Val Acc: 99.1%  <-- Best model saved

TRAINING COMPLETE — Best Val Accuracy: 99.1%
```

> ⚠️ Training takes ~2–3 hours on CPU. Use a GPU for 10–20x speedup.

---

### 3. Predict on a Single Image

**Auto-crop using annotation XML:**
```bash
python predict_defect.py "PCB_DATASET/images/Short/01_short_01.jpg"
```

**Manual bounding box coordinates:**
```bash
python predict_defect.py "PCB_DATASET/images/Short/01_short_01.jpg" 763 1136 828 1201
```

Expected output:
```
[INFO] Found annotation: 01_short_01.xml (3 defect region(s))

Image : PCB_DATASET/images/Short/01_short_01.jpg
============================================================

Region 1  bbox=(763,1136,828,1201)
  Prediction : Short
  Confidence : 99.9%
  All classes:
    Missing_hole            0.0%
    Mouse_bite              0.0%
    Open_circuit            0.0%
    Short                  99.9%  #############################
    Spur                    0.0%
    Spurious_copper         0.0%

============================================================
OVERALL (avg of 3 regions)
  Prediction : Short
  Confidence : 99.7%
============================================================
```

---

### 4. Quick Test — All 6 Classes (PowerShell)

```powershell
@("Missing_hole","Mouse_bite","Open_circuit","Short","Spur","Spurious_copper") | ForEach-Object {
    Write-Host "`nClass: $_"
    python predict_defect.py "PCB_DATASET/images/$_/01_${_}_01.jpg" 2>&1 | Select-String "OVERALL|Prediction|Confidence"
}
```

---

## Model Details

| Property | Value |
|---|---|
| Architecture | EfficientNet-B0 |
| Pretrained On | ImageNet |
| Input Size | 224 × 224 px |
| Input Source | Annotated bounding-box crops + 32px padding |
| Output Classes | 6 |
| Phase 1 LR | 1e-3 (classifier only) |
| Phase 2 LR | 1e-4 (full backbone) |
| Optimizer | Adam |
| LR Scheduler | ReduceLROnPlateau (patience=2, factor=0.5) |
| Early Stopping | 5 epochs without improvement |
| Best Val Accuracy | **99.1%** |
| Model File Size | ~16 MB |

---

## Dataset

This project uses the **DeepPCB dataset** — a PCB defect detection dataset with:
- **687 defect images** across 6 categories
- **2,922 annotated bounding boxes** (Pascal VOC XML format)
- **Matching golden reference boards** for subtraction-based detection

---

## Important Notes for GitHub

> The following files/folders are large and should be added to `.gitignore`:

```gitignore
# Large dataset — download separately
PCB_DATASET/

# Generated outputs
output_masks/
__pycache__/
*.pyc

# Model weights (16 MB — use Git LFS or share separately)
pcb_defect_model.pth

# IDE files
.vscode/
.qodo/
```

> To share the trained model, upload `pcb_defect_model.pth` to:
> - [Google Drive](https://drive.google.com) and link in README
> - [Hugging Face Hub](https://huggingface.co) (free model hosting)
> - GitHub Releases (supports files up to 2 GB)

---

## Future Improvements

- [ ] Build a web UI (Flask / Streamlit / Gradio)
- [ ] Add real-time webcam detection
- [ ] Train a YOLO object detection model for bounding box prediction without annotations
- [ ] Export model to ONNX for faster CPU inference
- [ ] Add per-class precision, recall, F1 score evaluation script

---

## Author

**Jan Siddiqui**
B.Tech — Semester 6 | Infosys Project
