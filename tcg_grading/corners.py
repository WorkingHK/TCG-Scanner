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
# Crop size should be large enough to capture corner radius (~3mm) plus surrounding context
# With ~10 pixels/mm, 3mm radius needs ~30px, so 500px crop gives extensive context
CORNER_CROP_PX = 500  # Increased to 500px to capture much more corner detail and context
# NO inset - capture from absolute edge [0,0] to get the real corner
CORNER_INSET_PX = 0
# Max image dimension for API upload
MAX_DIM = 2048


def _find_true_corner_edge(
    original_rgb: np.ndarray,
    detected_corner: np.ndarray,
    card_center: np.ndarray,
    search_distance: int = 100
) -> tuple[int, int]:
    """
    Find the TRUE physical corner edge by searching outward from detected corner.

    The detected quad often lands inside the card border. This function walks
    outward along the center→corner direction until it finds the transition
    to black background (the actual card edge).

    Args:
        original_rgb: Original captured image
        detected_corner: [x, y] of detected quad vertex
        card_center: [x, y] of card center
        search_distance: How far to search outward (pixels)

    Returns:
        (x, y) of true physical corner edge
    """
    h, w = original_rgb.shape[:2]

    # Direction from center to corner (normalized)
    direction = detected_corner - card_center
    direction_norm = direction / (np.linalg.norm(direction) + 1e-6)

    # Search outward along this direction
    # Look for transition from card (lighter) to black background (darker)
    best_corner = detected_corner.copy()
    found_edge = False

    for step in range(0, search_distance, 2):
        test_point = detected_corner + direction_norm * step
        tx, ty = int(test_point[0]), int(test_point[1])

        # Stay within image bounds
        if tx < 5 or ty < 5 or tx >= w-5 or ty >= h-5:
            break

        # Sample a small region around this point
        sample_region = original_rgb[ty-2:ty+3, tx-2:tx+3]
        if sample_region.size == 0:
            break

        # Check if this region is dark (black background)
        mean_brightness = sample_region.mean()

        # Black background threshold (adjust based on your setup)
        if mean_brightness < 50:  # Very dark = black frame
            # Found the transition! Step back slightly to be ON the edge
            best_corner = detected_corner + direction_norm * max(0, step - 5)
            found_edge = True
            break

    # If we didn't find edge (already on black?), search INWARD instead
    if not found_edge:
        for step in range(0, search_distance, 2):
            test_point = detected_corner - direction_norm * step  # Search inward
            tx, ty = int(test_point[0]), int(test_point[1])

            if tx < 5 or ty < 5 or tx >= w-5 or ty >= h-5:
                break

            sample_region = original_rgb[ty-2:ty+3, tx-2:tx+3]
            if sample_region.size == 0:
                break

            mean_brightness = sample_region.mean()

            # Look for transition from black to card (brighter)
            if mean_brightness >= 50:  # Found card
                # Move back outward to the edge
                best_corner = test_point + direction_norm * 5
                break

    return int(best_corner[0]), int(best_corner[1])


def _crop_corners_from_original(
    original_rgb: np.ndarray,
    quad_corners: np.ndarray,
    crop_size: int = CORNER_CROP_PX  # Use global constant instead of hardcoded 150
) -> dict[str, np.ndarray]:
    """
    Extract corner crops directly from the ORIGINAL image at the TRUE physical corners.

    Searches outward from detected quad vertices to find where card meets black frame.
    This captures the actual physical corner for accurate radius measurement.

    Args:
        original_rgb: Original captured image (before rectification)
        quad_corners: 4 corners of detected card quad in [tl, tr, br, bl] order
        crop_size: Size of square crop around each corner (pixels)

    Returns:
        Dict of corner crops {name: rgb_array}
    """
    crops = {}
    corner_names = ["top_left", "top_right", "bottom_right", "bottom_left"]

    h, w = original_rgb.shape[:2]
    half = crop_size // 2

    # Calculate card center
    card_center = quad_corners.mean(axis=0)

    for i, name in enumerate(corner_names):
        # Find TRUE corner edge (not just detected quad vertex)
        true_cx, true_cy = _find_true_corner_edge(
            original_rgb,
            quad_corners[i],
            card_center,
            search_distance=200  # Increased from 100 to handle larger images
        )

        # Extract crop_size × crop_size region centered on TRUE corner
        x1 = max(0, true_cx - half)
        y1 = max(0, true_cy - half)
        x2 = min(w, true_cx + half)
        y2 = min(h, true_cy + half)

        crop = original_rgb[y1:y2, x1:x2].copy()

        # If we hit image boundary, pad with black (background color)
        if crop.shape[0] < crop_size or crop.shape[1] < crop_size:
            padded = np.zeros((crop_size, crop_size, 3), dtype=np.uint8)
            padded[:crop.shape[0], :crop.shape[1]] = crop
            crop = padded

        crops[name] = crop

    return crops


def _crop_corners(rgb: np.ndarray, size: int = CORNER_CROP_PX, inset: int = CORNER_INSET_PX) -> dict[str, np.ndarray]:
    """
    LEGACY: Extract four corner ROIs from the rectified card image.
    Now replaced by _crop_corners_from_original() which captures true physical corners.

    Kept for backward compatibility but should not be used for grading.
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
        # TEMPORARY: Force use rectified image until original image corner detection is fixed
        # Corner 1 (top-right) consistently fails with _crop_corners_from_original
        if False and hasattr(card, 'original_rgb') and hasattr(card, 'outer_corners_ordered'):
            crops = _crop_corners_from_original(
                card.original_rgb,
                card.outer_corners_ordered,
                crop_size=CORNER_CROP_PX  # Use global constant instead of hardcoded 150
            )
        else:
            # Use rectified image (all 4 corners work reliably)
            # For rectified image (630x880), use 150px crop size for good detail without overlap
            rect_crop_size = 150
            crops = _crop_corners(card.rgb, size=rect_crop_size, inset=0)

        metrics = {name: _measure_corner(crop) for name, crop in crops.items()}
        cv_available = any(bool(m) for m in metrics.values())

        # Save annotated crop (composite of 4 corners)
        annotated_path: Optional[Path] = None
        if save_dir:
            annotated_path = _save_composite(crops, save_dir, "corners_composite.jpg")
            # Save individual corner crops for detailed report display
            _save_individual_corners(crops, save_dir)

        # CV-driven scoring: use CV metrics as base (1-10 scale), VLM adjusts ±0.5
        cv_base_score = _compute_cv_base_score(metrics)

        # TEMPORARY: VLM disabled for CV tuning - use CV base score directly
        if cv_base_score is not None:
            final_grade = cv_base_score
            vlm_grade = cv_base_score
            adjustment = 0
        else:
            # Fallback: no CV metrics, use default
            final_grade = 5.0
            vlm_grade = 5.0
            adjustment = 0

        # Grade is now 1-10 scale (PSA style)
        evidence = {
            "cv_metrics": metrics,
            "cv_available": cv_available,
            "cv_base_score": cv_base_score,
            "vlm_raw_grade": vlm_grade,
            "vlm_adjustment": adjustment,
            "final_grade": round(final_grade, 1),
            "vlm_disabled": True,
            "vlm_response": {"note": "VLM disabled for CV tuning"},
        }

        return CriterionGrade(
            grade=final_grade,  # 1-10 scale
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
    Returns score on 1-10 scale (PSA style).
    Returns None if no valid measurements available.
    """
    scores = []
    for corner_name, m in metrics.items():
        if m and "radius_quality_score" in m:
            # radius_quality_score is already 0-10 scale
            scores.append(m["radius_quality_score"])

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
