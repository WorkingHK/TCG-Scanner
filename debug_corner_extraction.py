#!/usr/bin/env python3
"""Debug script to test corner extraction from original image."""

import cv2
import numpy as np
from pathlib import Path
from tcg_grading.corners import _crop_corners_from_original, _measure_corner
import json

# Load the latest capture
capture_dir = Path("captures/2026-08-26/105313")
raw_img_path = capture_dir / "raw_capture.jpg"
report_path = capture_dir / "grade_report.json"

# Load raw image
rgb = cv2.imread(str(raw_img_path))
rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)

# Load the quad corners from detect.py (we need to re-detect or load from saved data)
# For now, let's manually test with a simple quad
# We'll need the actual quad corners from the detection step

print(f"Raw image shape: {rgb.shape}")
print(f"Image loaded from: {raw_img_path}")

# Read the report to understand what happened
with open(report_path) as f:
    report = json.load(f)

print("\nCorner metrics from report:")
print(json.dumps(report["corners"]["evidence"]["cv_metrics"], indent=2))

# To properly test this, we need to re-run detection and capture the quad corners
print("\nTo fix this, we need to:")
print("1. Re-run detect_card() and capture outer_corners_ordered")
print("2. Test _crop_corners_from_original() with those corners")
print("3. Debug why top-right corner search fails")
