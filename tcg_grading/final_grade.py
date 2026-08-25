"""Rule-based aggregation of four criterion grades into an overall grade."""

from __future__ import annotations

from typing import Optional

from .types import CriterionGrade, GradeReport


def compute_final_grade(
    centering: Optional[CriterionGrade],
    corners: Optional[CriterionGrade],
    edges: Optional[CriterionGrade],
    surface: Optional[CriterionGrade],
) -> Optional[float]:
    """
    Aggregate four sub-grades into an overall grade.

    All grades are on 1-10 scale (PSA style).

    Rule (from design spec):
        overall = min(four) + 0.5   if all others >= min + 1
                = min(four)         otherwise

    Returns None if any criterion is missing or errored.
    """
    criteria = [centering, corners, edges, surface]

    # Require all four criteria to be present and error-free
    if any(c is None or c.error is not None for c in criteria):
        return None

    # All grades are already 1-10 scale
    grades = [c.grade for c in criteria]  # type: ignore[union-attr]

    # Apply the aggregation rule
    grades_sorted = sorted(grades)
    bottom = grades_sorted[0]
    rest = grades_sorted[1:]

    if all(g >= bottom + 1.0 for g in rest):
        overall = bottom + 0.5
    else:
        overall = bottom

    # Cap at 10.0 (10.5 is only for pristine, not computed here automatically)
    return min(overall, 10.0)


def format_grade_for_display(grade_1000: float) -> float:
    """Convert internal 0-1000 scale to display 1-10 scale (PSA style)."""
    return round(grade_1000 / 100.0, 1)


def build_grade_report(
    centering: Optional[CriterionGrade],
    corners: Optional[CriterionGrade],
    edges: Optional[CriterionGrade],
    surface: Optional[CriterionGrade],
    **kwargs,
) -> GradeReport:
    """Build a GradeReport from four criterion grades."""
    overall = compute_final_grade(centering, corners, edges, surface)
    return GradeReport(
        centering=centering,
        corners=corners,
        edges=edges,
        surface=surface,
        overall=overall,
        **kwargs,
    )
