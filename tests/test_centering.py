"""Unit tests for centering grader."""

from __future__ import annotations

import numpy as np
import pytest

from tcg_grading.rubric import centering_ratio_to_grade
from tcg_grading.types import DetectedCard, Polygon
from tcg_grading.centering import grade_centering


class TestCenteringRatioToGrade:
    def test_perfect_centering_grades_10(self):
        # 51/49 → grade 10
        grade = centering_ratio_to_grade(49, 51, 49, 51)
        assert grade == 10.0

    def test_55_45_grades_10(self):
        # 55/45 is exactly at the PSA grade-10 boundary — accept 9.0 or 10.0
        grade = centering_ratio_to_grade(45, 55, 50, 50)
        assert grade >= 9.0

    def test_60_40_grades_9(self):
        grade = centering_ratio_to_grade(40, 60, 50, 50)
        assert grade == 9.0

    def test_65_35_grades_8(self):
        grade = centering_ratio_to_grade(35, 65, 50, 50)
        assert grade == 8.0

    def test_worst_axis_used(self):
        # LR = 60/40 (grade 9), TB = 65/35 (grade 8) → should use TB (worse)
        grade = centering_ratio_to_grade(40, 60, 35, 65)
        assert grade == 8.0

    def test_symmetric_is_grade_10(self):
        grade = centering_ratio_to_grade(50, 50, 50, 50)
        assert grade == 10.0

    def test_very_off_center_grades_low(self):
        # 80/20 → grade 5
        grade = centering_ratio_to_grade(20, 80, 50, 50)
        assert grade == 5.0


class TestGradeCentering:
    def _make_card(self, inner_frame=None) -> DetectedCard:
        rgb = np.zeros((880, 630, 3), dtype=np.uint8)
        return DetectedCard(
            rgb=rgb,
            pixels_per_mm=10.0,
            outer_corners=[(0, 0), (629, 0), (629, 879), (0, 879)],
            inner_frame=inner_frame,
        )

    def test_no_inner_frame_returns_error(self):
        card = self._make_card(inner_frame=None)
        result = grade_centering(card)
        assert result.error is not None
        assert result.confidence == "low"

    def test_centered_frame_grades_10(self):
        # Inner frame centered within ~55/45 tolerance
        # Card is 630x880, margins ~45px each side → ~55/45 at worst
        h, w = 880, 630
        margin_x, margin_y = 40, 56
        inner = Polygon(points=[
            (margin_x, margin_y),
            (w - margin_x, margin_y),
            (w - margin_x, h - margin_y),
            (margin_x, h - margin_y),
        ])
        card = self._make_card(inner_frame=inner)
        result = grade_centering(card)
        assert result.error is None
        assert result.grade >= 9.0

    def test_off_center_frame_grades_lower(self):
        # Left margin 40px, right margin 200px → heavy L/R imbalance
        h, w = 880, 630
        inner = Polygon(points=[
            (40, 50),
            (w - 200, 50),
            (w - 200, h - 50),
            (40, h - 50),
        ])
        card = self._make_card(inner_frame=inner)
        result = grade_centering(card)
        assert result.error is None
        assert result.grade <= 7.0

    def test_evidence_contains_expected_keys(self):
        h, w = 880, 630
        margin = 50
        inner = Polygon(points=[
            (margin, margin),
            (w - margin, margin),
            (w - margin, h - margin),
            (margin, h - margin),
        ])
        card = self._make_card(inner_frame=inner)
        result = grade_centering(card)
        assert result.error is None
        for key in ("left_px", "right_px", "top_px", "bottom_px", "lr_worse_pct", "tb_worse_pct"):
            assert key in result.evidence
