"""
main.py — FastAPI Server for PCB Defect Detection

Endpoints:
  GET  /          → Health check (is server alive?)
  GET  /classes   → List all 6 defect class names
  POST /predict   → Upload a PCB image → get defect prediction back as JSON

Run with:
  uvicorn backend.main:app --reload --port 8000

Then visit:
  http://localhost:8000/docs   ← Auto-generated Swagger UI (test your API here!)
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps
import io
from typing import Optional

# Import our ML model (loads EfficientNet at startup)
from backend.model import predict, CLASS_NAMES

# ── Create the FastAPI app ────────────────────────────────────────────────────
app = FastAPI(
    title       = "PCB Defect Detection API",
    description = "Upload a PCB image and get the defect class + confidence score.",
    version     = "1.0.0"
)

# ── CORS Middleware ───────────────────────────────────────────────────────────
# CORS = Cross-Origin Resource Sharing
# Without this, your React frontend (localhost:5173) CANNOT talk to this API
# (localhost:8000). Browsers block cross-origin requests by default for security.
# This middleware tells the browser: "It's okay, allow requests from these origins."

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # In production: replace * with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoint 1: Health Check ──────────────────────────────────────────────────
# GET /
# Why: Deployment platforms (Render, Railway) ping this to check if server is alive.
# Also useful during development to confirm the server started correctly.

@app.get("/")
def health_check():
    return {
        "status"  : "online",
        "message" : "PCB Defect Detection API is running!",
        "docs"    : "Visit /docs to test the API interactively"
    }


# ── Endpoint 2: Get All Classes ───────────────────────────────────────────────
# GET /classes
# Why: Frontend can fetch this list dynamically instead of hardcoding class names.

@app.get("/classes")
def get_classes():
    return {
        "classes" : CLASS_NAMES,
        "count"   : len(CLASS_NAMES)
    }


# ── Endpoint 3: Predict Defect ────────────────────────────────────────────────
# POST /predict
# Accepts: multipart/form-data with an image file
# Returns: JSON with predicted class, confidence, per-region results

@app.post("/predict")
async def predict_defect(
    file         : UploadFile = File(..., description="PCB image file (JPG/PNG)"),
    xmin         : Optional[int] = Form(None, description="Manual bbox xmin"),
    ymin         : Optional[int] = Form(None, description="Manual bbox ymin"),
    xmax         : Optional[int] = Form(None, description="Manual bbox xmax"),
    ymax_val     : Optional[int] = Form(None, alias="ymax", description="Manual bbox ymax"),
):
    """
    Upload a PCB image and receive the predicted defect class.

    - If the image has a matching annotation XML file, bounding boxes are
      detected automatically.
    - Optionally pass manual xmin/ymin/xmax/ymax coordinates to crop a
      specific region.

    Returns:
    ```json
    {
      "overall_class": "Short",
      "overall_confidence": 99.7,
      "has_annotation": true,
      "regions": [...],
      "all_class_probs": { "Short": 99.7, "Spur": 0.2, ... }
    }
    ```
    """

    # ── Validate file type ────────────────────────────────────────────────────
    allowed = {"image/jpeg", "image/png", "image/jpg"}
    if file.content_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Upload a JPG or PNG image."
        )

    # ── Read image bytes and convert to PIL Image ─────────────────────────────
    # UploadFile gives us raw bytes. PIL.Image.open() needs a file-like object.
    # io.BytesIO() wraps the bytes in a file-like object.
    try:
        contents = await file.read()
        image    = Image.open(io.BytesIO(contents))
        image    = ImageOps.exif_transpose(image)   # Fix mobile EXIF rotation
        image    = image.convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read image: {str(e)}")

    # ── Build manual bbox if all 4 coords provided ────────────────────────────
    manual_bbox = None
    coords = [xmin, ymin, xmax, ymax_val]
    if all(c is not None for c in coords):
        manual_bbox = tuple(coords)

    # ── Call the ML model ─────────────────────────────────────────────────────
    try:
        result = predict(image, file.filename, manual_bbox=manual_bbox)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction error: {str(e)}")

    return result
