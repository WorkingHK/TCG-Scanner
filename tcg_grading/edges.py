"""Edge grading: CV measurements + VLM assessment."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .types import DetectedCard, CriterionGrade
from .rubric import EDGES_RUBRIC

logger = logging.getLogger(__name__)

# Edge strip height in pixels (from the rectified card image)
# Captures the actual card edge including the side touching the frame
EDGE_STRIP_HEIGHT = 70
# Inset from absolute edge to avoid black background artifacts in rectified image
EDGE_INSET_PX = 15  # Start 15px inward from edge to avoid black frame artifacts


def _crop_edge_strips_from_original(
    original_rgb: np.ndarray,
    quad_corners: np.ndarray,
    strip_width: int = 100
) -> dict[str, np.ndarray]:
    """
    Extract edge strips directly from the ORIGINAL image along the detected quad edges.
    This captures the true card edge without black background interference.

    Args:
        original_rgb: Original captured image (before rectification)
        quad_corners: 4 corners of detected card quad in [tl, tr, br, bl] order
        strip_width: Width of strip perpendicular to edge (pixels)

    Returns:
        Dict of edge strips {name: rgb_array}
    """
    strips = {}

    # Define edges as pairs of corners
    edges = {
        "top": (quad_corners[0], quad_corners[1]),      # tl → tr
        "right": (quad_corners[1], quad_corners[2]),    # tr → br
        "bottom": (quad_corners[2], quad_corners[3]),   # br → bl
        "left": (quad_corners[3], quad_corners[0]),     # bl → tl
    }

    h, w = original_rgb.shape[:2]

    for edge_name, (p1, p2) in edges.items():
        # Vector along the edge
        edge_vec = p2 - p1
        edge_len = np.linalg.norm(edge_vec)
        edge_unit = edge_vec / (edge_len + 1e-6)

        # Perpendicular vector pointing inward (toward card center)
        perp_unit = np.array([-edge_unit[1], edge_unit[0]])

        # Sample points along the edge
        num_samples = int(edge_len)
        sample_points = []

        for i in range(num_samples):
            t = i / max(1, num_samples - 1)
            edge_point = p1 + t * edge_vec

            # Extract strip_width pixels perpendicular to edge (going inward)
            strip_pixels = []
            for d in range(strip_width):
                sample_pt = edge_point + perp_unit * d
                x, y = int(sample_pt[0]), int(sample_pt[1])

                if 0 <= x < w and 0 <= y < h:
                    strip_pixels.append(original_rgb[y, x])
                else:
                    # Out of bounds - use black
                    strip_pixels.append([0, 0, 0])

            sample_points.append(strip_pixels)

        # Convert to numpy array: [edge_length, strip_width, 3]
        if sample_points:
            strip_array = np.array(sample_points, dtype=np.uint8)
            strips[edge_name] = strip_array
        else:
            # Fallback empty strip
            strips[edge_name] = np.zeros((100, strip_width, 3), dtype=np.uint8)

    return strips


def _crop_edge_strips(rgb: np.ndarray) -> dict[str, np.ndarray]:
    """
    Crop four edge strips from the rectified card image.
    Captures from the absolute edge - the side touching the black frame.
    This is the TRUE edge for border/edge measurement.

    For a 630×880px card:
    - NO inset (starts at pixel 0)
    - Capture 70px strips from absolute edge
    - This captures the edge that touches the frame - the most accurate border
    """
    h, w = rgb.shape[:2]
    s = EDGE_STRIP_HEIGHT
    i = EDGE_INSET_PX
    return {
        "top":    rgb[i:i+s,      :,         :],  # [0:70, :, :]
        "bottom": rgb[h-i-s:h-i,  :,         :],  # [810:880, :, :]
        "left":   rgb[:,           i:i+s,    :],  # [:, 0:70, :]
        "right":  rgb[:,           w-i-s:w-i, :],  # [:, 560:630, :]
    }


def _measure_edge(strip: np.ndarray, orientation: str) -> dict:
    """
    Measure edge quality by finding the card's outer border boundary.

    Strategy:
    - Find the transition from card border (light) to card interior/background
    - Measure straightness of this boundary line
    - Avoid using Canny which is too sensitive to holographic texture

    Returns: rms_deviation, chip_count, max_notch_depth
    orientation: 'horizontal' or 'vertical'
    """
    try:
        gray = cv2.cvtColor(strip, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape

        # Smooth to reduce holographic pattern noise
        smoothed = cv2.GaussianBlur(gray, (9, 9), 3.0)

        if orientation == "horizontal":
            # For top/bottom strips: find the edge row for each column
            # The edge is where brightness drops significantly (border → interior)
            edge_positions = []

            for col in range(0, w, 5):  # Sample every 5 pixels
                col_slice = smoothed[:, col]

                # Find the gradient (rate of brightness change)
                gradient = np.diff(col_slice.astype(float))

                # Look for the largest negative gradient (bright → dark transition)
                if len(gradient) > 0:
                    max_drop_idx = np.argmin(gradient)

                    # Only count if the drop is significant (>10 brightness units)
                    if gradient[max_drop_idx] < -10:
                        edge_positions.append(max_drop_idx)

            if len(edge_positions) < 20:
                return {"rms_deviation": None, "chip_count": None, "max_notch_depth": None,
                        "error": "insufficient edge points detected"}

            edge_arr = np.array(edge_positions, dtype=float)

        else:
            # For left/right strips: find the edge column for each row
            edge_positions = []

            for row in range(0, h, 5):  # Sample every 5 pixels
                row_slice = smoothed[row, :]

                # Find the gradient
                gradient = np.diff(row_slice.astype(float))

                # Look for the largest negative gradient (bright → dark transition)
                if len(gradient) > 0:
                    max_drop_idx = np.argmin(gradient)

                    # Only count if the drop is significant
                    if gradient[max_drop_idx] < -10:
                        edge_positions.append(max_drop_idx)

            if len(edge_positions) < 20:
                return {"rms_deviation": None, "chip_count": None, "max_notch_depth": None,
                        "error": "insufficient edge points detected"}

            edge_arr = np.array(edge_positions, dtype=float)

        # Fit line and compute RMS deviation
        ideal = np.linspace(edge_arr[0], edge_arr[-1], len(edge_arr))
        deviations = edge_arr - ideal

        # Filter outliers using IQR method to avoid extreme false positives
        q1 = np.percentile(np.abs(deviations), 25)
        q3 = np.percentile(np.abs(deviations), 75)
        iqr = q3 - q1
        outlier_threshold = q3 + 1.5 * iqr

        # Filter deviations to remove outliers for notch calculation
        filtered_deviations = deviations[np.abs(deviations) <= outlier_threshold]

        if len(filtered_deviations) < len(deviations) * 0.5:
            # Too many outliers filtered - use original
            filtered_deviations = deviations

        rms = float(np.sqrt(np.mean(deviations ** 2)))

        # Count chips: significant deviations from the ideal line
        # Use more lenient threshold for high-res images to avoid false positives
        # For a ~630px wide card from 6000×8000px source, 15px tolerance is reasonable for near-mint
        chip_threshold = 15.0  # Was 8.0 - still too strict for natural edge variation
        chips = np.sum(np.abs(deviations) > chip_threshold)

        # Max notch depth: maximum deviation from ideal line (after outlier filtering)
        max_notch = float(np.max(np.abs(filtered_deviations)))

        return {
            "rms_deviation": round(rms, 2),
            "chip_count": int(chips),
            "max_notch_depth": round(max_notch, 2),
        }
    except Exception as e:
        return {"rms_deviation": None, "chip_count": None, "max_notch_depth": None,
                "error": str(e)}


def _encode_image(rgb: np.ndarray, max_side: int = 1024) -> str:
    """Encode numpy RGB array as base64 JPEG, resizing if needed."""
    h, w = rgb.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        rgb = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    _, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def _call_vlm(strips: dict[str, np.ndarray], metrics: dict[str, dict],
              client, output_dir: Optional[Path]) -> dict:
    """Call Claude Vision API to grade edges."""
    content = []

    # Add metrics summary as text
    metrics_text = "CV Edge Measurements:\n"
    for edge_name, m in metrics.items():
        if m.get("error"):
            metrics_text += f"  {edge_name}: CV metrics unavailable ({m['error']})\n"
        else:
            metrics_text += (
                f"  {edge_name}: RMS deviation={m.get('rms_deviation')}px, "
                f"chips={m.get('chip_count')}, max notch={m.get('max_notch_depth')}px\n"
            )
    content.append({"type": "text", "text": metrics_text})

    # Add edge strip images
    for edge_name, strip in strips.items():
        content.append({"type": "text", "text": f"Edge strip — {edge_name}:"})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": _encode_image(strip),
            }
        })

    content.append({"type": "text", "text": "Please grade these edges. Respond ONLY with valid JSON."})

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": EDGES_RUBRIC,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": content}],
    )

    raw = response.content[0].text if response.content else ""

    # Parse JSON, retry once if malformed
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Try stripping markdown fences
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            # Retry
            retry_response = client.messages.create(
                model="claude-opus-4-7",
                max_tokens=1024,
                system=[{
                    "type": "text",
                    "text": EDGES_RUBRIC,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[
                    {"role": "user", "content": content},
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": "Your response was not valid JSON. Please respond ONLY with the JSON object, no other text."},
                ],
            )
            retry_raw = retry_response.content[0].text if retry_response.content else "{}"
            result = json.loads(retry_raw)

    return result


def grade_edges(card: DetectedCard, client, output_dir: Optional[Path] = None) -> CriterionGrade:
    """
    Grade card edges using CV measurements only (VLM disabled for tuning).
    """
    # Use rectified image, but filter out black background in measurements
    strips = _crop_edge_strips(card.rgb)

    orientations = {
        "top": "horizontal",
        "bottom": "horizontal",
        "left": "vertical",
        "right": "vertical",
    }

    metrics: dict[str, dict] = {}
    for edge_name, strip in strips.items():
        metrics[edge_name] = _measure_edge(strip, orientations[edge_name])

    cv_ok = any(not m.get("error") for m in metrics.values())

    try:
        # CV-driven scoring: use CV metrics only (VLM disabled)
        cv_base_score = _compute_cv_base_score(metrics)

        if cv_base_score is not None:
            final_grade = cv_base_score
            vlm_grade = cv_base_score
            adjustment = 0
        else:
            # Fallback: no CV metrics, use default
            final_grade = 5.0
            vlm_grade = 5.0
            adjustment = 0

        # Grade is 1-10 scale (PSA style)
        confidence = "medium"

        evidence = {
            "cv_metrics": metrics,
            "cv_available": cv_ok,
            "cv_base_score": cv_base_score,
            "vlm_raw_grade": vlm_grade,
            "vlm_adjustment": adjustment,
            "final_grade": round(final_grade, 1),
            "vlm_disabled": True,
            "per_edge": {},
            "worst_edge": None,
            "worst_edge_observation": "VLM disabled for CV tuning",
            "reasoning": "Using CV metrics only",
        }

        # Save annotated strip if output_dir provided
        annotated_path = None
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            # Save individual edge strips for detailed report display
            _save_individual_edges(strips, output_dir)
            # Create a composite image of all strips
            resized = []
            target_w = 400
            for name, strip in strips.items():
                h, w = strip.shape[:2]
                scale = target_w / w if w > 0 else 1.0
                resized_strip = cv2.resize(
                    cv2.cvtColor(strip, cv2.COLOR_RGB2BGR),
                    (target_w, max(1, int(h * scale)))
                )
                cv2.putText(resized_strip, name, (10, 20), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (0, 255, 0), 1)
                resized.append(resized_strip)
            composite = np.vstack(resized)
            annotated_path = output_dir / "edges_annotated.jpg"
            cv2.imwrite(str(annotated_path), composite)

        return CriterionGrade(
            grade=final_grade,  # 1-10 scale
            confidence=confidence,
            evidence=evidence,
            annotated_crop_path=annotated_path,
        )

    except Exception as e:
        logger.error(f"Edge grading failed: {e}")
        return CriterionGrade(
            grade=1.0,  # 1-10 scale
            confidence="low",
            evidence={"cv_metrics": metrics, "cv_available": cv_ok},
            annotated_crop_path=None,
            error=str(e),
        )


def _compute_cv_base_score(metrics: dict[str, dict]) -> Optional[float]:
    """
    Compute base edge grade from CV measurements.
    Maps rms_deviation, chip_count, and max_notch_depth to 1-10 scale.
    Returns the worst edge score (most conservative).
    Returns None if no valid measurements available.
    """
    edge_scores = []

    for edge_name, m in metrics.items():
        if m.get("error"):
            continue

        # Extract metrics
        rms = m.get("rms_deviation")
        chips = m.get("chip_count")
        notch = m.get("max_notch_depth")

        if rms is None or chips is None or notch is None:
            continue

        # Score RMS deviation (straightness): adjusted for high-res images
        # For 630px card, allow larger absolute deviation
        # 0-3px=10.0, 3-8px=9.0, 8-15px=8.0, 15-25px=7.0, 25-40px=5.0, >40px=lower
        if rms <= 3.0:
            rms_score = 10.0
        elif rms <= 8.0:
            rms_score = 9.0 + (8.0 - rms) / 5.0 * 1.0  # 9.0-10.0 linear
        elif rms <= 15.0:
            rms_score = 8.0 + (15.0 - rms) / 7.0 * 1.0  # 8.0-9.0 linear
        elif rms <= 25.0:
            rms_score = 7.0 + (25.0 - rms) / 10.0 * 1.0  # 7.0-8.0 linear
        elif rms <= 40.0:
            rms_score = 5.0 + (40.0 - rms) / 15.0 * 2.0  # 5.0-7.0 linear
        else:
            rms_score = max(1.0, 5.0 - (rms - 40.0) * 0.2)

        # Score chip count: more lenient for near-mint cards with natural variation
        # 0=10.0, 1-5=9.5, 6-15=9.0, 16-30=8.5, 31-50=7.5, 51-80=6.0, >80=lower
        if chips == 0:
            chip_score = 10.0
        elif chips <= 5:
            chip_score = 9.5
        elif chips <= 15:
            chip_score = 9.0
        elif chips <= 30:
            chip_score = 8.5
        elif chips <= 50:
            chip_score = 7.5  # Was 600 - too harsh for near-mint
        elif chips <= 80:
            chip_score = 6.0
        else:
            chip_score = max(1.0, 6.0 - (chips - 80) * 0.08)

        # Score max notch depth: adjusted for high-res images
        # For 630px card width, allow larger absolute deviation for near-mint cards
        # 0-5px=10.0, 5-15px=9.0, 15-25px=8.0, 25-40px=7.0, 40-60px=5.0, >60px=lower
        if notch <= 5.0:
            notch_score = 10.0
        elif notch <= 15.0:
            notch_score = 9.0 + (15.0 - notch) / 10.0 * 1.0  # 9.0-10.0 linear
        elif notch <= 25.0:
            notch_score = 8.0 + (25.0 - notch) / 10.0 * 1.0  # 8.0-9.0 linear
        elif notch <= 40.0:
            notch_score = 7.0 + (40.0 - notch) / 15.0 * 1.0  # 7.0-8.0 linear
        elif notch <= 60.0:
            notch_score = 5.0 + (60.0 - notch) / 20.0 * 2.0  # 5.0-7.0 linear
        else:
            notch_score = max(1.0, 5.0 - (notch - 60.0) * 0.15)

        # Take worst of the three metrics for this edge
        edge_score = min(rms_score, chip_score, notch_score)
        edge_scores.append(edge_score)

    if not edge_scores:
        return None

    # Return worst edge score (most conservative)
    return min(edge_scores)


def _save_individual_edges(strips: dict[str, np.ndarray], output_dir: Path) -> None:
    """Save individual edge strips as edge_0.jpg through edge_3.jpg."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        edge_order = ["top", "bottom", "left", "right"]
        for i, edge_key in enumerate(edge_order):
            strip = strips[edge_key]
            out_path = output_dir / f"edge_{i}.jpg"
            bgr = cv2.cvtColor(strip, cv2.COLOR_RGB2BGR)
            cv2.imwrite(str(out_path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
            logger.debug(f"Saved {edge_key} edge to {out_path}")
    except Exception as exc:
        logger.warning(f"Failed to save individual edge crops: {exc}")
