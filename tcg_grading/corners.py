"""Corner grading: CV metrics + Claude Vision."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Optional

import anthropic
import cv2
import numpy as np

from .rubric import CORNERS_RUBRIC
from .types import CriterionGrade, DetectedCard

log = logging.getLogger(__name__)

# Corner crop size (pixels) in rectified image
# Focus on the actual corner radius area (3mm = 30px, plus margin)
# Smaller crop = captures only the corner point, not entire border edges
CORNER_CROP_PX = 60  # Reduced from 120 to focus on corner radius only
# NO inset - capture from absolute edge [0,0] to get the real corner
CORNER_INSET_PX = 0
# Max image dimension for API upload
MAX_DIM = 2048


def _crop_corners(rgb: np.ndarray, size: int = CORNER_CROP_PX, inset: int = CORNER_INSET_PX) -> dict[str, np.ndarray]:
    """
    Extract four corner ROIs from the rectified card image.
    Captures from the absolute edge - the side touching the black frame.
    This is the TRUE corner for radius measurement.

    For a 630×880px card:
    - NO inset (starts at pixel 0)
    - Capture 120×120px region from absolute corner
    - This captures the edge that touches the frame - the most accurate corner
    """
    h, w = rgb.shape[:2]
    s = size
    i = inset
    return {
        "top_left":     rgb[i:i+s, i:i+s],              # [0:120, 0:120]
        "top_right":    rgb[i:i+s, w-i-s:w-i],          # [0:120, 510:630]
        "bottom_left":  rgb[h-i-s:h-i, i:i+s],          # [760:880, 0:120]
        "bottom_right": rgb[h-i-s:h-i, w-i-s:w-i],      # [760:880, 510:630]
    }


def _measure_corner(crop: np.ndarray) -> dict:
    """
    Measure corner radius quality - how close to the ideal 3mm radius.

    Pokemon cards should have 3mm corner radius.
    For a 630×880px rectified card (63×88mm), 3mm = 30px radius.

    Returns:
    - radius_px: Measured corner radius in pixels
    - radius_mm: Measured corner radius in mm (assuming 10px/mm)
    - deviation_from_ideal_mm: How far from ideal 3mm radius
    - radius_quality: Quality score (0-10, 10=perfect 3mm radius)
    - defect_pixel_area: Area of damage/imperfection
    """
    try:
        h, w = crop.shape[:2]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)

        # Threshold to get card edge
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Find the card edge contour
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            return {}

        contour = max(contours, key=cv2.contourArea)

        # The corner should be at the crop corner (top-left pixel of crop)
        # We need to find the corner radius by fitting a circle to the contour curve

        # Extract points near the corner (first ~50 points of contour near [0,0])
        pts = contour.reshape(-1, 2)

        # Find points close to the corner (within 40px of [0,0])
        dists_to_corner = np.sqrt(pts[:, 0]**2 + pts[:, 1]**2)
        corner_region_mask = dists_to_corner < 40
        corner_pts = pts[corner_region_mask]

        if len(corner_pts) < 5:
            return {}

        # Fit a circle to these corner points using least squares
        # Circle equation: (x-cx)^2 + (y-cy)^2 = r^2
        # For corner at origin, expect cx ≈ r, cy ≈ r

        try:
            # Use minEnclosingCircle for robust radius estimation
            (cx, cy), radius_px = cv2.minEnclosingCircle(corner_pts)

            # Ideal radius for Pokemon card: 3mm = 30px (at 10px/mm scale)
            IDEAL_RADIUS_MM = 3.0
            PIXELS_PER_MM = 10.0  # 630px / 63mm
            ideal_radius_px = IDEAL_RADIUS_MM * PIXELS_PER_MM

            # Convert measured radius to mm
            radius_mm = radius_px / PIXELS_PER_MM

            # Deviation from ideal
            deviation_mm = abs(radius_mm - IDEAL_RADIUS_MM)

            # Quality score: 10 = perfect, 0 = >2mm deviation
            # Allow ±0.3mm tolerance for perfect score
            if deviation_mm <= 0.3:
                quality = 10.0
            elif deviation_mm <= 0.5:
                quality = 9.0
            elif deviation_mm <= 1.0:
                quality = 8.0 - (deviation_mm - 0.5) * 2  # 8.0 to 7.0
            elif deviation_mm <= 2.0:
                quality = 7.0 - (deviation_mm - 1.0) * 3  # 7.0 to 4.0
            else:
                quality = max(1.0, 4.0 - (deviation_mm - 2.0))  # <4.0

            # Calculate defect area (difference between ideal and actual shape)
            hull = cv2.convexHull(contour)
            hull_area = cv2.contourArea(hull)
            contour_area = cv2.contourArea(contour)
            defect_pixel_area = max(0.0, float(hull_area - contour_area))

            return {
                "radius_px": round(radius_px, 2),
                "radius_mm": round(radius_mm, 3),
                "ideal_radius_mm": IDEAL_RADIUS_MM,
                "deviation_from_ideal_mm": round(deviation_mm, 3),
                "radius_quality_score": round(quality, 1),
                "defect_pixel_area_px2": round(defect_pixel_area, 1),
                "corner_center": (round(cx, 1), round(cy, 1)),
            }

        except Exception as e:
            log.warning(f"Circle fitting failed: {e}")
            return {}

    except Exception as exc:
        log.warning("Corner CV measurement failed: %s", exc)
        return {}


def _encode_image(rgb: np.ndarray) -> str:
    """Encode RGB numpy array to base64 JPEG string."""
    h, w = rgb.shape[:2]
    scale = min(1.0, MAX_DIM / max(h, w))
    if scale < 1.0:
        rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    _, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return base64.b64encode(buf.tobytes()).decode()


def grade_corners(
    card: DetectedCard,
    client: anthropic.Anthropic,
    save_dir: Optional[Path] = None,
) -> CriterionGrade:
    """
    Grade card corners using CV metrics only (VLM disabled for tuning).
    Returns CriterionGrade with error set if grading fails.
    """
    try:
        crops = _crop_corners(card.rgb)
        metrics = {name: _measure_corner(crop) for name, crop in crops.items()}
        cv_available = any(bool(m) for m in metrics.values())

        # Save annotated crop (composite of 4 corners)
        annotated_path: Optional[Path] = None
        if save_dir:
            annotated_path = _save_composite(crops, save_dir, "corners_composite.jpg")
            # Save individual corner crops for detailed report display
            _save_individual_corners(crops, save_dir)

        # CV-driven scoring: use CV metrics as base (0-1000), VLM adjusts ±50
        cv_base_score = _compute_cv_base_score(metrics)

        # TEMPORARY: VLM disabled for CV tuning - use CV base score directly
        if cv_base_score is not None:
            final_grade = cv_base_score
            vlm_grade_1000 = cv_base_score
            adjustment = 0
        else:
            # Fallback: no CV metrics, use default
            final_grade = 500.0
            vlm_grade_1000 = 500.0
            adjustment = 0

        # Grade is now 0-1000 (TAG scale)
        evidence = {
            "cv_metrics": metrics,
            "cv_available": cv_available,
            "cv_base_score_1000": cv_base_score,
            "vlm_raw_grade_1000": vlm_grade_1000,
            "vlm_adjustment": adjustment,
            "final_grade_1000": round(final_grade, 0),
            "vlm_disabled": True,
            "vlm_response": {"note": "VLM disabled for CV tuning"},
        }

        return CriterionGrade(
            grade=final_grade,  # 0-1000 scale
            confidence="medium",
            evidence=evidence,
            annotated_crop_path=annotated_path,
        )

    except Exception as exc:
        log.exception("Corner grading failed")
        return CriterionGrade(
            grade=1.0,
            confidence="low",
            evidence={},
            annotated_crop_path=None,
            error=str(exc),
        )


def _call_vlm_with_retry(
    client: anthropic.Anthropic,
    system_prompt: str,
    content: list,
    retries: int = 1,
) -> dict:
    """Call Claude Vision and parse JSON response; retry once on bad JSON."""
    for attempt in range(retries + 1):
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": content}],
        )
        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
            text = text.rstrip("`").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if attempt < retries:
                log.warning("VLM returned bad JSON, retrying...")
                continue
            raise ValueError(f"VLM response not valid JSON after {retries + 1} attempts: {text[:200]}")


def _save_composite(
    crops: dict[str, np.ndarray],
    save_dir: Path,
    filename: str,
) -> Optional[Path]:
    """Save a 2x2 composite of corner crops."""
    try:
        save_dir.mkdir(parents=True, exist_ok=True)
        tl = crops["top_left"]
        tr = crops["top_right"]
        bl = crops["bottom_left"]
        br = crops["bottom_right"]
        top = np.concatenate([tl, tr], axis=1)
        bot = np.concatenate([bl, br], axis=1)
        composite = np.concatenate([top, bot], axis=0)
        out = save_dir / filename
        bgr = cv2.cvtColor(composite, cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(out), bgr)
        return out
    except Exception as exc:
        log.warning("Failed to save corner composite: %s", exc)
        return None


def _compute_cv_base_score(metrics: dict[str, dict]) -> Optional[float]:
    """
    Compute base corner grade from CV radius quality measurements.
    Returns score on 0-1000 scale (TAG Portal scale).
    Returns None if no valid measurements available.
    """
    scores = []
    for corner_name, m in metrics.items():
        if m and "radius_quality_score" in m:
            # radius_quality_score is 0-10, convert to 0-1000
            score_1000 = m["radius_quality_score"] * 100.0
            scores.append(score_1000)

    if not scores:
        return None

    # Use worst corner as base (most conservative approach)
    return min(scores)


def _save_individual_corners(crops: dict[str, np.ndarray], save_dir: Path) -> None:
    """Save individual corner crops as corner_0.jpg through corner_3.jpg."""
    try:
        save_dir.mkdir(parents=True, exist_ok=True)
        corner_order = ["top_left", "top_right", "bottom_left", "bottom_right"]
        for i, corner_key in enumerate(corner_order):
            crop = crops[corner_key]
            out_path = save_dir / f"corner_{i}.jpg"
            bgr = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
            cv2.imwrite(str(out_path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
            log.debug(f"Saved {corner_key} to {out_path}")
    except Exception as exc:
        log.warning("Failed to save individual corner crops: %s", exc)
