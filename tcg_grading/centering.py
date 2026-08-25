"""Pure CV centering grader — no VLM required."""

from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

from .types import DetectedCard, CriterionGrade
from .rubric import centering_ratio_to_grade

log = logging.getLogger(__name__)


def grade_centering(card: DetectedCard) -> CriterionGrade:
    """
    Measure L/R and T/B border margins from the inner image frame vs outer card border.
    Maps worst-axis ratio to a grade using PSA 2025 tolerance table.

    Returns a CriterionGrade with error set if detection fails.
    """
    if card.inner_frame is None:
        return CriterionGrade(
            grade=1.0,  # 1-10 scale
            confidence="low",
            evidence={"error": "Inner frame not detected; centering cannot be measured"},
            annotated_crop_path=None,
            error="Inner frame not detected",
        )

    try:
        h, w = card.rgb.shape[:2]

        # Detect actual card boundary by finding non-black regions
        # Black PLA background has very low intensity (< 30 in all channels)
        gray = cv2.cvtColor(card.rgb, cv2.COLOR_RGB2GRAY)
        _, mask = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)

        # Find the bounding box of non-black pixels (the actual card)
        coords = cv2.findNonZero(mask)
        if coords is not None:
            x, y, card_w, card_h = cv2.boundingRect(coords)
            card_x_min = float(x)
            card_x_max = float(x + card_w)
            card_y_min = float(y)
            card_y_max = float(y + card_h)
        else:
            # Fallback: use full image
            card_x_min, card_y_min = 0.0, 0.0
            card_x_max, card_y_max = float(w), float(h)

        # Inner frame bounding box
        pts = np.array(card.inner_frame.points, dtype=np.float32)
        frame_x_min = float(pts[:, 0].min())
        frame_x_max = float(pts[:, 0].max())
        frame_y_min = float(pts[:, 1].min())
        frame_y_max = float(pts[:, 1].max())

        # Calculate borders between inner frame and card edge (not image edge)
        left   = frame_x_min - card_x_min
        right  = card_x_max - frame_x_max
        top    = frame_y_min - card_y_min
        bottom = card_y_max - frame_y_max

        if left + right <= 0 or top + bottom <= 0:
            raise ValueError("Degenerate frame margins")

        grade = centering_ratio_to_grade(left, right, top, bottom)

        lr_total = left + right
        tb_total = top + bottom
        lr_worse_pct = max(left, right) / lr_total * 100
        tb_worse_pct = max(top, bottom) / tb_total * 100

        # Annotate the rectified card image
        annotated = card.rgb.copy()
        pts_int = pts.astype(int)
        cv2.polylines(annotated, [pts_int.reshape(-1, 1, 2)], True, (0, 255, 0), 2)

        evidence = {
            "left_px": round(left, 1),
            "right_px": round(right, 1),
            "top_px": round(top, 1),
            "bottom_px": round(bottom, 1),
            "lr_worse_pct": round(lr_worse_pct, 1),
            "tb_worse_pct": round(tb_worse_pct, 1),
            "worst_axis": "LR" if lr_worse_pct >= tb_worse_pct else "TB",
        }

        confidence: str
        worst = max(lr_worse_pct, tb_worse_pct)
        if worst <= 65:
            confidence = "high"
        elif worst <= 80:
            confidence = "medium"
        else:
            confidence = "low"

        return CriterionGrade(
            grade=grade,
            confidence=confidence,  # type: ignore[arg-type]
            evidence=evidence,
            annotated_crop_path=None,
        )

    except Exception as exc:
        log.exception("Centering grading failed")
        return CriterionGrade(
            grade=1.0,  # 1-10 scale
            confidence="low",
            evidence={"exception": str(exc)},
            annotated_crop_path=None,
            error=str(exc),
        )
