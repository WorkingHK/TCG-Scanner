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
# NO inset - capture from absolute edge to get the real border
EDGE_INSET_PX = 0


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
    Measure edge quality metrics for one edge strip.
    Returns: rms_deviation, chip_count, max_notch_depth
    orientation: 'horizontal' or 'vertical'
    """
    try:
        gray = cv2.cvtColor(strip, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape

        # Find the card border edge using Canny + contour
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 30, 100)

        if orientation == "horizontal":
            # For top/bottom strips, find the horizontal edge
            # Sum edge pixels column by column, find row of maximum response
            edge_rows = []
            for col in range(0, w, 5):
                col_slice = edges[:, col]
                if col_slice.max() > 0:
                    edge_rows.append(np.argmax(col_slice))
            if len(edge_rows) < 3:
                return {"rms_deviation": None, "chip_count": None, "max_notch_depth": None,
                        "error": "insufficient edge points detected"}
            edge_arr = np.array(edge_rows, dtype=float)
        else:
            # For left/right strips, find the vertical edge
            edge_cols = []
            for row in range(0, h, 5):
                row_slice = edges[row, :]
                if row_slice.max() > 0:
                    edge_cols.append(np.argmax(row_slice))
            if len(edge_cols) < 3:
                return {"rms_deviation": None, "chip_count": None, "max_notch_depth": None,
                        "error": "insufficient edge points detected"}
            edge_arr = np.array(edge_cols, dtype=float)

        # Fit line and compute RMS deviation
        ideal = np.linspace(edge_arr[0], edge_arr[-1], len(edge_arr))
        deviations = edge_arr - ideal
        rms = float(np.sqrt(np.mean(deviations ** 2)))

        # Count chips: deviations > 3px from median
        median_pos = float(np.median(edge_arr))
        chip_threshold = 3.0
        chips = np.sum(np.abs(edge_arr - median_pos) > chip_threshold)
        max_notch = float(np.max(np.abs(edge_arr - median_pos)))

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
            vlm_grade_1000 = cv_base_score
            adjustment = 0
        else:
            # Fallback: no CV metrics, use default
            final_grade = 500.0
            vlm_grade_1000 = 500.0
            adjustment = 0

        # Grade is 0-1000 (TAG scale)
        confidence = "medium"

        evidence = {
            "cv_metrics": metrics,
            "cv_available": cv_ok,
            "cv_base_score_1000": cv_base_score,
            "vlm_raw_grade_1000": vlm_grade_1000,
            "vlm_adjustment": adjustment,
            "final_grade_1000": round(final_grade, 0),
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
            grade=final_grade,  # 0-1000 scale
            confidence=confidence,
            evidence=evidence,
            annotated_crop_path=annotated_path,
        )

    except Exception as e:
        logger.error(f"Edge grading failed: {e}")
        return CriterionGrade(
            grade=100.0,  # 0-1000 scale
            confidence="low",
            evidence={"cv_metrics": metrics, "cv_available": cv_ok},
            annotated_crop_path=None,
            error=str(e),
        )


def _compute_cv_base_score(metrics: dict[str, dict]) -> Optional[float]:
    """
    Compute base edge grade from CV measurements.
    Maps rms_deviation, chip_count, and max_notch_depth to 0-1000 scale.
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

        # Score RMS deviation (straightness): 0-1px=1000, 1-2px=900, 2-3px=800, 3-5px=600, >5px=lower
        if rms <= 1.0:
            rms_score = 1000.0
        elif rms <= 2.0:
            rms_score = 900.0
        elif rms <= 3.0:
            rms_score = 800.0
        elif rms <= 5.0:
            rms_score = 600.0 + (5.0 - rms) / 2.0 * 200.0  # 600-800 linear
        else:
            rms_score = max(100.0, 600.0 - (rms - 5.0) * 50.0)

        # Score chip count: 0=1000, 1-2=850, 3-5=700, 6-10=500, >10=lower
        if chips == 0:
            chip_score = 1000.0
        elif chips <= 2:
            chip_score = 850.0
        elif chips <= 5:
            chip_score = 700.0
        elif chips <= 10:
            chip_score = 500.0
        else:
            chip_score = max(100.0, 500.0 - (chips - 10) * 20.0)

        # Score max notch depth: 0-2px=1000, 2-5px=800, 5-10px=600, >10px=lower
        if notch <= 2.0:
            notch_score = 1000.0
        elif notch <= 5.0:
            notch_score = 800.0
        elif notch <= 10.0:
            notch_score = 600.0
        else:
            notch_score = max(100.0, 600.0 - (notch - 10.0) * 30.0)

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
