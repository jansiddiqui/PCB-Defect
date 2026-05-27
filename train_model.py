"""
train_model.py  —  PCB Defect Classifier (annotation-crop approach)

ROOT CAUSE OF PREVIOUS FAILURE:
  The defect regions in PCB images are tiny (~65×65 px) inside full images
  that are ~3034×1586 px. When the full image was resized to 224×224, each
  defect shrank to ≈5 pixels — completely invisible to EfficientNet.

FIX:
  Read Pascal-VOC XML annotations → crop each bounding box (+ padding) →
  train the classifier on the defect crops directly.
  Each full image has several bounding boxes, so we go from 687 images to
  ~2000+ crops, and each crop ONLY shows the defect — no background noise.
"""

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image
import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import transforms, models
from torch.utils.data import Dataset, DataLoader, random_split, Subset

# =============================================================================
# PATHS
# =============================================================================
ANNOTATIONS_PATH = "PCB_DATASET/Annotations"
IMAGES_PATH      = "PCB_DATASET/images"
CROP_PADDING     = 32   # pixels of context added around each bounding box

# Class order must match what ImageFolder would use (alphabetical)
CLASS_NAMES = [
    "Missing_hole",
    "Mouse_bite",
    "Open_circuit",
    "Short",
    "Spur",
    "Spurious_copper",
]
CLASS_TO_IDX = {name: i for i, name in enumerate(CLASS_NAMES)}

# =============================================================================
# ANNOTATION PARSER — returns list of (image_path, xmin, ymin, xmax, ymax, label)
# =============================================================================
def parse_annotations(annotations_root, images_root):
    samples = []
    ann_root = Path(annotations_root)
    img_root = Path(images_root)

    for class_dir in sorted(ann_root.iterdir()):
        if not class_dir.is_dir():
            continue
        class_name = class_dir.name
        if class_name not in CLASS_TO_IDX:
            continue
        label = CLASS_TO_IDX[class_name]

        for xml_file in class_dir.glob("*.xml"):
            try:
                tree = ET.parse(xml_file)
                root = tree.getroot()
                filename = root.findtext("filename")
                img_path = img_root / class_name / filename

                if not img_path.exists():
                    continue

                for obj in root.findall("object"):
                    bbox = obj.find("bndbox")
                    xmin = int(float(bbox.findtext("xmin")))
                    ymin = int(float(bbox.findtext("ymin")))
                    xmax = int(float(bbox.findtext("xmax")))
                    ymax = int(float(bbox.findtext("ymax")))
                    samples.append((str(img_path), xmin, ymin, xmax, ymax, label))
            except Exception as e:
                print(f"  [WARN] Skipping {xml_file.name}: {e}", flush=True)

    return samples


# =============================================================================
# CUSTOM DATASET — crops defect regions on-the-fly
# =============================================================================
class PCBCropDataset(Dataset):
    def __init__(self, samples, transform=None, padding=CROP_PADDING):
        self.samples   = samples
        self.transform = transform
        self.padding   = padding

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        img_path, xmin, ymin, xmax, ymax, label = self.samples[idx]
        img = Image.open(img_path).convert("RGB")
        w, h = img.size

        # Add padding around the bounding box; clamp to image bounds
        x1 = max(0, xmin - self.padding)
        y1 = max(0, ymin - self.padding)
        x2 = min(w, xmax + self.padding)
        y2 = min(h, ymax + self.padding)

        crop = img.crop((x1, y1, x2, y2))

        if self.transform:
            crop = self.transform(crop)

        return crop, label


# =============================================================================
# TRANSFORMS
# =============================================================================
train_transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.RandomHorizontalFlip(),
    transforms.RandomVerticalFlip(),
    transforms.RandomRotation(20),
    transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.2),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225])
])

val_transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225])
])

# =============================================================================
# LOAD ALL ANNOTATION CROPS
# =============================================================================
print("Parsing annotations and collecting defect crops...", flush=True)
all_samples = parse_annotations(ANNOTATIONS_PATH, IMAGES_PATH)
print(f"Total defect crops: {len(all_samples)}", flush=True)

# Print per-class count
from collections import Counter
counts = Counter(CLASS_NAMES[s[5]] for s in all_samples)
for name, cnt in sorted(counts.items()):
    print(f"  {name:<22} {cnt} crops", flush=True)

# Split 80/20
train_size = int(0.8 * len(all_samples))
val_size   = len(all_samples) - train_size
generator  = torch.Generator().manual_seed(42)
train_idx, val_idx = random_split(range(len(all_samples)),
                                  [train_size, val_size], generator=generator)

train_dataset = PCBCropDataset([all_samples[i] for i in train_idx.indices], transform=train_transform)
val_dataset   = PCBCropDataset([all_samples[i] for i in val_idx.indices],   transform=val_transform)

train_loader    = DataLoader(train_dataset, batch_size=16, shuffle=True,  num_workers=0)
val_loader      = DataLoader(val_dataset,   batch_size=16, shuffle=False, num_workers=0)

# Smaller batches for Phase 2 (full backbone unfrozen needs more RAM per batch)
train_loader_p2 = DataLoader(train_dataset, batch_size=8, shuffle=True,  num_workers=0)
val_loader_p2   = DataLoader(val_dataset,   batch_size=8, shuffle=False, num_workers=0)

print(f"\nTrain crops: {len(train_dataset)} | Val crops: {len(val_dataset)}", flush=True)

# =============================================================================
# MODEL
# =============================================================================
num_classes = len(CLASS_NAMES)
model = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT)
model.classifier[1] = nn.Linear(model.classifier[1].in_features, num_classes)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}", flush=True)
model = model.to(device)

criterion = nn.CrossEntropyLoss()
optimizer = None   # set per phase


# =============================================================================
# TRAINING HELPER
# =============================================================================
def run_epoch(loader, training=True):
    model.train() if training else model.eval()
    total_loss, correct, total = 0.0, 0, 0
    ctx = torch.enable_grad() if training else torch.no_grad()
    with ctx:
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            if training:
                optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            if training:
                loss.backward()
                optimizer.step()
            total_loss += loss.item()
            _, predicted = torch.max(outputs, 1)
            correct += (predicted == labels).sum().item()
            total   += labels.size(0)
    return total_loss / len(loader), 100 * correct / total


def train_phase(phase_name, epochs, lr, freeze_backbone, t_loader=None, v_loader=None):
    global optimizer

    t_loader = t_loader or train_loader
    v_loader = v_loader or val_loader

    for param in model.features.parameters():
        param.requires_grad = not freeze_backbone

    trainable = [p for p in model.parameters() if p.requires_grad]
    optimizer = optim.Adam(trainable, lr=lr)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max',
                                                     patience=2, factor=0.5)

    print(f"\n{'='*60}", flush=True)
    print(f"{phase_name}  (backbone {'FROZEN' if freeze_backbone else 'UNFROZEN'}, lr={lr}, batch={t_loader.batch_size})", flush=True)
    print(f"{'='*60}", flush=True)

    best_val_acc, patience_counter, EARLY_STOP = 0.0, 0, 5

    for epoch in range(epochs):
        train_loss, train_acc = run_epoch(t_loader, training=True)
        _,          val_acc   = run_epoch(v_loader, training=False)

        print(f"Epoch [{epoch+1:02d}/{epochs}]  "
              f"Loss: {train_loss:.4f}  "
              f"Train Acc: {train_acc:.1f}%  "
              f"Val Acc: {val_acc:.1f}%", flush=True)

        scheduler.step(val_acc)

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save(model.state_dict(), "pcb_defect_model.pth")
            print(f"  --> Best model saved! (Val Acc: {val_acc:.1f}%)", flush=True)
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= EARLY_STOP:
                print(f"\nEarly stopping — no improvement for {EARLY_STOP} epochs.", flush=True)
                break

    return best_val_acc


# =============================================================================
# PHASE 1: Freeze backbone — warm up the classifier head (5 epochs, lr=1e-3)
# =============================================================================
best1 = train_phase("PHASE 1 — Classifier warm-up", epochs=5, lr=1e-3, freeze_backbone=True)

# =============================================================================
# PHASE 2: Unfreeze backbone — fine-tune everything (15 epochs, lr=1e-4)
# =============================================================================
best2 = train_phase("PHASE 2 — Full fine-tuning",   epochs=15, lr=1e-4, freeze_backbone=False,
                    t_loader=train_loader_p2, v_loader=val_loader_p2)

best_overall = max(best1, best2)
print(f"\n{'='*60}", flush=True)
print(f"TRAINING COMPLETE — Best Val Accuracy: {best_overall:.1f}%", flush=True)
print("Model saved to: pcb_defect_model.pth", flush=True)
print(f"{'='*60}", flush=True)