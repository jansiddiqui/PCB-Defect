"""
model.py — ML Model Loader & Predictor

This file has ONE job: load the trained EfficientNet-B0 model and
expose a predict() function that takes a PIL Image and returns results.

Why separate from main.py?
- Model loads ONCE at startup (not on every request — that would be slow)
- main.py stays clean and only handles HTTP logic
- Easy to swap the model later without touching the API code
"""

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import torch
import torch.nn as nn
from torchvision import transforms, models
from PIL import Image

# ── Constants ────────────────────────────────────────────────────────────────

CLASS_NAMES = [
    "Missing_hole",
    "Mouse_bite",
    "Open_circuit",
    "Short",
    "Spur",
    "Spurious_copper",
]

CROP_PADDING = 32
ANNOTATIONS_ROOT = os.path.join(os.path.dirname(__file__), "..", "PCB_DATASET", "Annotations")

# ── Model Path — local file OR download from Hugging Face Hub ─────────────────
# In development : uses pcb_defect_model.pth from the project root
# In production  : downloads from Hugging Face Hub automatically
#   Set env var HF_REPO=your-username/PCB-Defect before deploying

LOCAL_MODEL = os.path.join(os.path.dirname(__file__), "..", "pcb_defect_model.pth")
HF_REPO     = os.environ.get("HF_REPO", "")   # e.g. "jansiddiqui/PCB-Defect"

def get_model_path():
    if os.path.exists(LOCAL_MODEL):
        print("Using local model weights.", flush=True)
        return LOCAL_MODEL
    if HF_REPO:
        print(f"Downloading model from HuggingFace Hub: {HF_REPO}", flush=True)
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(repo_id=HF_REPO, filename="pcb_defect_model.pth")
        print("Model downloaded.", flush=True)
        return path
    raise FileNotFoundError(
        "pcb_defect_model.pth not found locally and HF_REPO env var not set."
    )

MODEL_PATH = get_model_path()



# ── Load Model Once at Startup ────────────────────────────────────────────────
# This runs when the server starts — NOT on every request.
# Loading a model takes ~1 second. Doing it per-request would make the API very slow.

print("Loading PCB defect model...", flush=True)

model = models.efficientnet_b0(weights=None)
model.classifier[1] = nn.Linear(model.classifier[1].in_features, len(CLASS_NAMES))
model.load_state_dict(
    torch.load(MODEL_PATH, map_location=torch.device("cpu"))
)
model.eval()   # Put in evaluation mode (disables dropout, batchnorm variance updates)

print(f"Model loaded! Classes: {CLASS_NAMES}", flush=True)


# ── Image Transform ───────────────────────────────────────────────────────────
# Must EXACTLY match the val_transform used during training.

transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225])
])


# ── Helper: Find Annotation File ─────────────────────────────────────────────

def find_annotation(image_filename: str):
    """
    Search all class subfolders in Annotations/ for a matching XML file.
    Returns the Path if found, else None.
    """
    stem = Path(image_filename).stem   # e.g. "01_short_01"
    ann_root = Path(ANNOTATIONS_ROOT)

    if not ann_root.exists():
        return None

    for class_dir in ann_root.iterdir():
        xml_path = class_dir / (stem + ".xml")
        if xml_path.exists():
            return xml_path
    return None


def parse_bboxes(xml_path: Path):
    """Parse all bounding boxes from a Pascal VOC XML annotation file."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    boxes = []
    for obj in root.findall("object"):
        bbox = obj.find("bndbox")
        xmin = int(float(bbox.findtext("xmin")))
        ymin = int(float(bbox.findtext("ymin")))
        xmax = int(float(bbox.findtext("xmax")))
        ymax = int(float(bbox.findtext("ymax")))
        boxes.append((xmin, ymin, xmax, ymax))
    return boxes


# ── Main Predict Function ─────────────────────────────────────────────────────

def predict(image: Image.Image, filename: str, manual_bbox=None):
    """
    Predict defect class for a PCB image.

    Args:
        image       : PIL Image (RGB)
        filename    : original filename (used to find annotation XML)
        manual_bbox : optional (xmin, ymin, xmax, ymax) tuple

    Returns:
        dict with keys:
            - overall_class      : str
            - overall_confidence : float (0-100)
            - regions            : list of per-region results
            - has_annotation     : bool
    """
    img_w, img_h = image.size

    # ── Step 1: Determine bounding boxes ──────────────────────────────────────
    if manual_bbox:
        bboxes = [manual_bbox]
        has_annotation = False
        source = "manual"
    else:
        ann_file = find_annotation(filename)
        if ann_file:
            bboxes = parse_bboxes(ann_file)
            has_annotation = True
            source = f"annotation ({len(bboxes)} region(s))"
        else:
            # Fallback: centre crop
            cx, cy = img_w // 2, img_h // 2
            size   = min(img_w, img_h) // 4
            bboxes = [(cx - size, cy - size, cx + size, cy + size)]
            has_annotation = False
            source = "centre crop (no annotation found)"

    print(f"Predicting: {filename} | Source: {source}", flush=True)

    # ── Step 2: Classify each bounding box ────────────────────────────────────
    regions = []
    all_probs = []

    for xmin, ymin, xmax, ymax in bboxes:
        # Crop with padding
        x1 = max(0, xmin - CROP_PADDING)
        y1 = max(0, ymin - CROP_PADDING)
        x2 = min(img_w, xmax + CROP_PADDING)
        y2 = min(img_h, ymax + CROP_PADDING)

        crop        = image.crop((x1, y1, x2, y2))
        crop_tensor = transform(crop).unsqueeze(0)   # add batch dim

        with torch.no_grad():
            outputs = model(crop_tensor)
            probs   = torch.softmax(outputs, dim=1)[0]

        conf, pred = torch.max(probs, 0)

        regions.append({
            "bbox"        : [xmin, ymin, xmax, ymax],
            "class"       : CLASS_NAMES[pred.item()],
            "confidence"  : round(conf.item() * 100, 2),
            "all_probs"   : {
                name: round(probs[i].item() * 100, 2)
                for i, name in enumerate(CLASS_NAMES)
            }
        })
        all_probs.append(probs)

    # ── Step 3: Overall verdict (average across all regions) ──────────────────
    avg_probs        = torch.stack(all_probs).mean(dim=0)
    avg_conf, avg_pred = torch.max(avg_probs, 0)

    return {
        "overall_class"      : CLASS_NAMES[avg_pred.item()],
        "overall_confidence" : round(avg_conf.item() * 100, 2),
        "has_annotation"     : has_annotation,
        "regions"            : regions,
        "all_class_probs"    : {
            name: round(avg_probs[i].item() * 100, 2)
            for i, name in enumerate(CLASS_NAMES)
        }
    }
