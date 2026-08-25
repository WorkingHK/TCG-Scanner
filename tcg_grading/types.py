"""Shared dataclasses for the TCG grading pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import numpy as np


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

@dataclass
class CardImage:
    """Raw image as captured from camera or loaded from disk."""
    path: Path
    rgb: np.ndarray
    captured_at: datetime
    camera_settings: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Intermediate types
# ---------------------------------------------------------------------------

Point = tuple[int, int]

@dataclass
class Polygon:
    """A polygon defined by a list of (x, y) points in image coordinates."""
    points: list[Point]


@dataclass
class DetectedCard:
    """Perspective-corrected card at canonical aspect ratio."""
    rgb: np.ndarray                  # rectified, canonical size
    pixels_per_mm: float             # from jig calibration (or estimate)
    outer_corners: list[Point]       # four corners in rectified-image coords
    inner_frame: Optional[Polygon]   # printed image frame, for centering (None if undetected)
    original_rgb: Optional[np.ndarray] = None           # original captured image (before rectification)
    outer_corners_ordered: Optional[np.ndarray] = None  # quad corners in original image [tl, tr, br, bl]


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

Confidence = Literal["high", "medium", "low"]

@dataclass
class CriterionGrade:
    """Result from one grading criterion."""
    grade: float                         # 1.0–10.0; 10.5 represents Pristine/10P
    confidence: Confidence
    evidence: dict                       # criterion-specific measurements + VLM text
    annotated_crop_path: Optional[Path]  # saved annotated image for UI display
    error: Optional[str] = None          # if non-None, grading failed; grade is meaningless


@dataclass
class GradeReport:
    """Final output of the grading pipeline."""
    centering: Optional[CriterionGrade]
    corners: Optional[CriterionGrade]
    edges: Optional[CriterionGrade]
    surface: Optional[CriterionGrade]
    overall: Optional[float]             # None if any criterion failed
    timestamp: datetime = field(default_factory=datetime.now)
    capture_path: Optional[Path] = None  # directory where crops/report are saved

    @property
    def all_criteria_ok(self) -> bool:
        return all(
            c is not None and c.error is None
            for c in [self.centering, self.corners, self.edges, self.surface]
        )

    def summary(self) -> str:
        lines = ["=== TCG Grade Report ==="]
        for name, criterion in [
            ("Centering", self.centering),
            ("Corners", self.corners),
            ("Edges", self.edges),
            ("Surface", self.surface),
        ]:
            if criterion is None:
                lines.append(f"  {name}: NOT RUN")
            elif criterion.error:
                lines.append(f"  {name}: ERROR — {criterion.error}")
            else:
                # Grades are already on 1-10 scale (PSA style)
                lines.append(f"  {name}: {criterion.grade:.1f} ({criterion.confidence})")
        if self.overall is not None:
            lines.append(f"  OVERALL: {self.overall:.1f}")
        else:
            lines.append("  OVERALL: N/A (one or more criteria failed)")
        return "\n".join(lines)
