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
    Pre-detect candidate surface defects using morphological ops + Hough lines.
    Returns annotated image copy and evidence dict.

    NOTE: For holographic cards, these metrics will have many false positives.
    Thresholds are relaxed to reduce sensitivity to holo patterns.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    annotated = rgb.copy()
    evidence: dict = {}

    # --- Scratch detection via top-hat morphology ---
    # Use larger kernel and higher threshold to reduce holo pattern false positives
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
    # Increased threshold from 30 to 50 to reduce holo pattern sensitivity
    _, scratch_mask = cv2.threshold(tophat, 50, 255, cv2.THRESH_BINARY)
    scratch_pixel_count = int(np.sum(scratch_mask > 0))
    evidence["scratch_candidate_pixels"] = scratch_pixel_count

    # Overlay scratch candidates in red
    annotated[scratch_mask > 0] = [255, 80, 80]

    # --- Print line / refractor detection via Hough ---
    # Increased Canny thresholds and Hough threshold to reduce false positives
    edges = cv2.Canny(gray, 50, 150)  # Was 30, 100 - too sensitive
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=120, minLineLength=60, maxLineGap=15)
    # threshold: 80 → 120 (more strict)
    # minLineLength: 40 → 60 (only longer lines)
    # maxLineGap: 10 → 15 (allow more gap)

    line_count = 0
    if lines is not None:
        line_count = len(lines)
        for line in lines[:20]:  # annotate first 20
            x1, y1, x2, y2 = line[0]
            cv2.line(annotated, (x1, y1), (x2, y2), (80, 80, 255), 1)
    evidence["hough_line_count"] = line_count

    # Derive a simple severity estimate for the evidence panel
    total_px = gray.shape[0] * gray.shape[1]
    scratch_pct = scratch_pixel_count / total_px * 100
    evidence["scratch_coverage_pct"] = round(scratch_pct, 3)

    return annotated, evidence


def _compute_cv_base_score(cv_evidence: dict) -> Optional[float]:
    """
    Compute base surface grade from CV measurements.
    Maps scratch_coverage_pct and hough_line_count to 1-10 scale.
    Returns None if insufficient data.

    NOTE: Scoring is relaxed for holographic cards which naturally trigger
    more false positives due to their reflective patterns.
    """
    scratch_pct = cv_evidence.get("scratch_coverage_pct", 0)
    line_count = cv_evidence.get("hough_line_count", 0)

    # Score scratch coverage: adjusted for holographic cards
    # 0-2%=10.0, 2-5%=9.0, 5-10%=8.0, 10-15%=7.0, 15-20%=6.0, 20-30%=5.0, >30%=lower
    if scratch_pct <= 2.0:
        scratch_score = 10.0
    elif scratch_pct <= 5.0:
        scratch_score = 9.0 + (5.0 - scratch_pct) / 3.0 * 1.0
    elif scratch_pct <= 10.0:
        scratch_score = 8.0 + (10.0 - scratch_pct) / 5.0 * 1.0
    elif scratch_pct <= 15.0:
        scratch_score = 7.0 + (15.0 - scratch_pct) / 5.0 * 1.0
    elif scratch_pct <= 20.0:
        scratch_score = 6.0 + (20.0 - scratch_pct) / 5.0 * 1.0
    elif scratch_pct <= 30.0:
        scratch_score = 5.0 + (30.0 - scratch_pct) / 10.0 * 1.0
    else:
        scratch_score = max(1.0, 5.0 - (scratch_pct - 30.0) * 0.12)

    # Score line count: adjusted for holographic cards
    # 0-150=10.0, 150-400=9.0, 400-700=8.0, 700-1200=7.0, 1200-2000=6.0, 2000-3000=5.0, >3000=lower
    if line_count <= 150:
        line_score = 10.0
    elif line_count <= 400:
        line_score = 9.0 + (400 - line_count) / 250.0 * 1.0
    elif line_count <= 700:
        line_score = 8.0 + (700 - line_count) / 300.0 * 1.0
    elif line_count <= 1200:
        line_score = 7.0 + (1200 - line_count) / 500.0 * 1.0
    elif line_count <= 2000:
        line_score = 6.0 + (2000 - line_count) / 800.0 * 1.0
    elif line_count <= 3000:
        line_score = 5.0 + (3000 - line_count) / 1000.0 * 1.0
    else:
        line_score = max(1.0, 5.0 - (line_count - 3000) * 0.008)

    # Take worse of the two metrics
    base_score = min(scratch_score, line_score)
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

