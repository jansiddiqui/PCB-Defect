r"""
predict_defect.py  -  PCB Defect Classifier (annotation-crop inference)

The model was trained on bounding-box crops of defect regions, NOT on full
images. This script therefore crops the defect region before classifying.

Usage (auto-crop via annotation XML):
    python predict_defect.py <image_path>

Usage (manual crop coordinates):
    python predict_defect.py <image_path> <xmin> <ymin> <xmax> <ymax>

Examples:
    python predict_defect.py "PCB_DATASET/images/Short/01_short_01.jpg"
    python predict_defect.py "PCB_DATASET/images/Short/01_short_01.jpg" 763 1136 828 1201
"""

import sys
import os
import xml.etree.ElementTree as ET
from pathlib import Path
import torch
import torch.nn as nn
from torchvision import transforms, models
from PIL import Image

# =============================================================================
# CLASS NAMES (must match training order — alphabetical)
# =============================================================================
CLASS_NAMES = [
    "Missing_hole",
    "Mouse_bite",
    "Open_circuit",
    "Short",
    "Spur",
    "Spurious_copper",
]

ANNOTATIONS_ROOT = "PCB_DATASET/Annotations"
CROP_PADDING     = 32   # match training padding

# =============================================================================
# PARSE ARGUMENTS
# =============================================================================
if len(sys.argv) < 2:
    print("Usage: python predict_defect.py <image_path> [xmin ymin xmax ymax]")
    print("Example: python predict_defect.py PCB_DATASET/images/Short/01_short_01.jpg")
    sys.exit(1)

img_path = sys.argv[1]

manual_coords = None
if len(sys.argv) == 6:
    try:
        manual_coords = tuple(int(x) for x in sys.argv[2:6])
    except ValueError:
        print("[ERROR] Coordinates must be integers: xmin ymin xmax ymax")
        sys.exit(1)

# =============================================================================
# LOAD IMAGE
# =============================================================================
try:
    image = Image.open(img_path).convert("RGB")
except FileNotFoundError:
    print(f"[ERROR] Image not found: {img_path}")
    sys.exit(1)

img_w, img_h = image.size

# =============================================================================
# FIND BOUNDING BOXES
# =============================================================================
def find_annotation_file(img_path, annotations_root):
    """Search for a matching XML annotation file based on image filename."""
    img_name   = Path(img_path).stem        # e.g. "01_short_01"
    ann_root   = Path(annotations_root)

    # Search all class subfolders
    for class_dir in ann_root.iterdir():
        xml_path = class_dir / (img_name + ".xml")
        if xml_path.exists():
            return xml_path
    return None

def parse_bboxes(xml_path):
    """Parse all bounding boxes from a Pascal VOC XML file."""
    tree  = ET.parse(xml_path)
    root  = tree.getroot()
    boxes = []
    for obj in root.findall("object"):
        bbox = obj.find("bndbox")
        xmin = int(float(bbox.findtext("xmin")))
        ymin = int(float(bbox.findtext("ymin")))
        xmax = int(float(bbox.findtext("xmax")))
        ymax = int(float(bbox.findtext("ymax")))
        boxes.append((xmin, ymin, xmax, ymax))
    return boxes

# Determine bounding boxes to use
if manual_coords:
    bboxes = [manual_coords]
    print(f"[INFO] Using manual coordinates: {manual_coords}")
else:
    ann_file = find_annotation_file(img_path, ANNOTATIONS_ROOT)
    if ann_file:
        bboxes = parse_bboxes(ann_file)
        print(f"[INFO] Found annotation: {ann_file.name} ({len(bboxes)} defect region(s))")
    else:
        # Fallback: use centre-crop of the full image (lower accuracy)
        cx, cy = img_w // 2, img_h // 2
        size   = min(img_w, img_h) // 4
        bboxes = [(cx - size, cy - size, cx + size, cy + size)]
        print("[WARN] No annotation found — using centre crop (accuracy may be lower).")
        print("[HINT] Pass manual coordinates: python predict_defect.py <img> xmin ymin xmax ymax")

# =============================================================================
# LOAD MODEL
# =============================================================================
model = models.efficientnet_b0(weights=None)
model.classifier[1] = nn.Linear(model.classifier[1].in_features, len(CLASS_NAMES))

if not os.path.exists("pcb_defect_model.pth"):
    print("[ERROR] Model file 'pcb_defect_model.pth' not found. Run train_model.py first.")
    sys.exit(1)

model.load_state_dict(torch.load("pcb_defect_model.pth", map_location=torch.device("cpu")))
model.eval()

# =============================================================================
# TRANSFORM (must match training val_transform exactly)
# =============================================================================
transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225])
])

# =============================================================================
# PREDICT EACH BOUNDING BOX
# =============================================================================
print(f"\nImage : {img_path}")
print("=" * 60)

all_probs = []

for i, (xmin, ymin, xmax, ymax) in enumerate(bboxes):
    # Crop with padding
    x1 = max(0, xmin - CROP_PADDING)
    y1 = max(0, ymin - CROP_PADDING)
    x2 = min(img_w, xmax + CROP_PADDING)
    y2 = min(img_h, ymax + CROP_PADDING)

    crop        = image.crop((x1, y1, x2, y2))
    crop_tensor = transform(crop).unsqueeze(0)

    with torch.no_grad():
        outputs = model(crop_tensor)
        probs   = torch.softmax(outputs, dim=1)[0]

    conf, pred = torch.max(probs, 0)
    all_probs.append(probs)

    print(f"\nRegion {i+1}  bbox=({xmin},{ymin},{xmax},{ymax})")
    print(f"  Prediction : {CLASS_NAMES[pred.item()]}")
    print(f"  Confidence : {conf.item()*100:.1f}%")
    print("  All classes:")
    for j, name in enumerate(CLASS_NAMES):
        bar = "#" * int(probs[j].item() * 30)
        print(f"    {name:<22} {probs[j].item()*100:5.1f}%  {bar}")

# =============================================================================
# OVERALL VERDICT (average probs across all regions)
# =============================================================================
if len(all_probs) > 1:
    avg_probs  = torch.stack(all_probs).mean(dim=0)
    avg_conf, avg_pred = torch.max(avg_probs, 0)
    print("\n" + "=" * 60)
    print(f"OVERALL (avg of {len(bboxes)} regions)")
    print(f"  Prediction : {CLASS_NAMES[avg_pred.item()]}")
    print(f"  Confidence : {avg_conf.item()*100:.1f}%")
    print("=" * 60)