"""Surface grading: CV pre-detection + VLM assessment."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .types import DetectedCard, CriterionGrade
from .rubric import SURFACE_RUBRIC

logger = logging.getLogger(__name__)

CARD_MAX_PX = 2048  # max long side before upload
TILE_MAX_PX = 1024  # high-res tile crops


def _encode_image(img: np.ndarray, max_px: int = CARD_MAX_PX) -> str:
    """Resize if needed and base64-encode as JPEG."""
    h, w = img.shape[:2]
    if max(h, w) > max_px:
        scale = max_px / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return base64.b64encode(buf.tobytes()).decode()


def _detect_surface_defects(rgb: np.ndarray) -> tuple[np.ndarray, dict]:
    """
    Smart scratch detection with background suppression and characteristic filtering.

    Reduces false positives from:
    - Complex artwork and printed details
    - Holographic patterns
    - Card edges and borders

    Improves detection of:
    - Fine scratches on complex backgrounds
    - Linear surface defects

    Returns annotated image copy and evidence dict.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    annotated = rgb.copy()
    evidence: dict = {}

    # Step 1: CLAHE enhancement for subtle scratch visibility
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)

    # Step 2: Background suppression to isolate scratches from artwork
    # Create "clean" background by closing with large kernel
    bg_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    background = cv2.morphologyEx(blurred, cv2.MORPH_CLOSE, bg_kernel)

    # Subtract background to isolate scratch signal
    scratch_isolated = cv2.absdiff(blurred, background)

    # Step 3: Multi-directional scratch detection (horizontal + vertical)
    scratch_combined = np.zeros_like(gray, dtype=np.float32)

    for angle in [0, 90]:  # Horizontal and vertical scratches
        kernel_len = 20
        if angle == 0:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_len, 1))
        else:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_len))

        tophat = cv2.morphologyEx(scratch_isolated, cv2.MORPH_TOPHAT, kernel)
        scratch_combined = np.maximum(scratch_combined, tophat.astype(np.float32))

    # Step 4: Adaptive thresholding using Otsu's method
    _, scratch_mask_otsu = cv2.threshold(
        scratch_combined.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    # Step 5: Filter by scratch characteristics
    # Real scratches are: linear, small to medium, not touching borders
    contours, _ = cv2.findContours(scratch_mask_otsu, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    scratch_mask_filtered = np.zeros_like(scratch_mask_otsu)

    real_scratch_count = 0
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 10:  # Too small, likely noise
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)

        # Exclude contours touching borders (likely card edges or artifacts)
        margin = 5
        if x < margin or y < margin or (x + bw) > (w - margin) or (y + bh) > (h - margin):
            continue

        # Check aspect ratio (scratches are elongated)
        aspect = max(bw, bh) / max(min(bw, bh), 1)
        if aspect < 3:  # Not linear enough
            continue

        # Exclude very large regions (likely holographic patterns)
        if area > 2000:
            continue

        # This is likely a real scratch
        cv2.drawContours(scratch_mask_filtered, [cnt], -1, 255, -1)
        real_scratch_count += 1

    # Overlay filtered scratches in red
    annotated[scratch_mask_filtered > 0] = [255, 80, 80]

    scratch_pixel_count = int(np.sum(scratch_mask_filtered > 0))
    evidence["scratch_candidate_pixels"] = scratch_pixel_count
    evidence["scratch_count"] = real_scratch_count

    # Step 6: Hough lines on isolated scratch image (reduces false positives)
    edges_isolated = cv2.Canny(scratch_isolated, 30, 90)
    lines = cv2.HoughLinesP(edges_isolated, 1, np.pi / 180, threshold=50, minLineLength=40, maxLineGap=10)

    line_count = 0
    if lines is not None:
        line_count = len(lines)
        # Annotate first 20 lines
        # OpenCV 4.x returns shape (N, 1, 4); OpenCV 5.x returns flat (N, 4).
        # Reshape defensively so unpacking works regardless of version.
        for line in lines[:20].reshape(-1, 4):
            x1, y1, x2, y2 = line
            cv2.line(annotated, (int(x1), int(y1)), (int(x2), int(y2)), (80, 80, 255), 1)

    evidence["hough_line_count"] = line_count

    # Calculate coverage percentage
    total_px = h * w
    scratch_pct = scratch_pixel_count / total_px * 100
    evidence["scratch_coverage_pct"] = round(scratch_pct, 3)

    return annotated, evidence


def _compute_cv_base_score(cv_evidence: dict) -> Optional[float]:
    """
    Compute base surface grade from CV measurements.
    Uses filtered scratch count and coverage percentage.

    The new smart detection filters out false positives from artwork and holographic patterns,
    so scoring is based on actual detected scratches rather than raw pixel coverage.

    Returns None if insufficient data.
    """
    scratch_pct = cv_evidence.get("scratch_coverage_pct", 0)
    scratch_count = cv_evidence.get("scratch_count", 0)
    line_count = cv_evidence.get("hough_line_count", 0)

    # Score based on filtered scratch count (more accurate than raw coverage)
    # 0-5 scratches = pristine (10-9)
    # 5-15 scratches = near mint (9-8)
    # 15-30 scratches = excellent (8-7)
    # 30-60 scratches = good (7-5)
    # 60+ scratches = fair/poor (5-1)
    if scratch_count <= 5:
        scratch_score = 10.0 - (scratch_count / 5.0) * 1.0  # 10.0 to 9.0
    elif scratch_count <= 15:
        scratch_score = 9.0 - ((scratch_count - 5) / 10.0) * 1.0  # 9.0 to 8.0
    elif scratch_count <= 30:
        scratch_score = 8.0 - ((scratch_count - 15) / 15.0) * 1.0  # 8.0 to 7.0
    elif scratch_count <= 60:
        scratch_score = 7.0 - ((scratch_count - 30) / 30.0) * 2.0  # 7.0 to 5.0
    else:
        scratch_score = max(1.0, 5.0 - ((scratch_count - 60) / 40.0) * 4.0)  # 5.0 to 1.0

    # Secondary check: coverage percentage (catches dense scratch clusters)
    # 0-2% = 10, 2-5% = 9, 5-10% = 7, >10% = lower
    if scratch_pct <= 2.0:
        coverage_score = 10.0
    elif scratch_pct <= 5.0:
        coverage_score = 9.0 - ((scratch_pct - 2.0) / 3.0) * 1.0
    elif scratch_pct <= 10.0:
        coverage_score = 8.0 - ((scratch_pct - 5.0) / 5.0) * 1.0
    else:
        coverage_score = max(1.0, 7.0 - ((scratch_pct - 10.0) / 5.0) * 1.0)

    # Take the worse of count and coverage scores
    base_score = min(scratch_score, coverage_score)
    return base_score


def _select_tiles(rgb: np.ndarray, n: int = 2) -> list[np.ndarray]:
    """Select n high-res tile crops from areas with most defect candidates."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)

    h, w = rgb.shape[:2]
    tile_h, tile_w = h // 3, w // 3
    tiles_scored: list[tuple[float, np.ndarray]] = []

    for row in range(3):
        for col in range(3):
            y0, y1 = row * tile_h, (row + 1) * tile_h
            x0, x1 = col * tile_w, (col + 1) * tile_w
            score = float(np.sum(tophat[y0:y1, x0:x1]))
            tiles_scored.append((score, rgb[y0:y1, x0:x1]))

    tiles_scored.sort(key=lambda t: t[0], reverse=True)
    return [t[1] for t in tiles_scored[:n]]


def grade_surface(
    card: DetectedCard,
    client,  # anthropic.Anthropic
    output_dir: Optional[Path] = None,
) -> CriterionGrade:
    """Grade card surface using CV metrics only (VLM disabled)."""
    try:
        annotated, cv_evidence = _detect_surface_defects(card.rgb)

        # Save annotated image
        annotated_path: Optional[Path] = None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            annotated_path = output_dir / "surface_annotated.jpg"
            cv2.imwrite(str(annotated_path), cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR))

        # Compute CV-based score (1-10 scale)
        cv_base_score = _compute_cv_base_score(cv_evidence)

        if cv_base_score is not None:
            final_grade = cv_base_score
        else:
            # Fallback: no CV metrics, use default
            final_grade = 5.0

        # Grade is 1-10 scale (PSA style)
        confidence = "medium"

        evidence = {
            "cv": cv_evidence,
            "cv_base_score": cv_base_score,
            "final_grade": round(final_grade, 1),
            "vlm_disabled": True,
            "reasoning": "Using CV metrics only (VLM disabled)",
        }

        return CriterionGrade(
            grade=final_grade,  # 1-10 scale
            confidence=confidence,
            evidence=evidence,
            annotated_crop_path=annotated_path,
        )

    except Exception as e:
        logger.error(f"Surface grading failed: {e}")
        return CriterionGrade(
            grade=1.0,  # 1-10 scale
            confidence="low",
            evidence={"cv": cv_evidence if 'cv_evidence' in locals() else {}},
            annotated_crop_path=None,
            error=str(e),
        )

