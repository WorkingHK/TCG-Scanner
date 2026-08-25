"""Unit tests for final grade aggregation — no CV deps needed."""

from __future__ import annotations

import pytest

from tcg_grading.final_grade import compute_final_grade, build_grade_report
from tcg_grading.types import CriterionGrade


def _grade(g: float) -> CriterionGrade:
    return CriterionGrade(grade=g, confidence="high", evidence={}, annotated_crop_path=None)


def _err() -> CriterionGrade:
    return CriterionGrade(grade=1.0, confidence="low", evidence={}, annotated_crop_path=None, error="failed")


class TestComputeFinalGrade:
    def test_all_10_gives_10(self):
        assert compute_final_grade(_grade(10), _grade(10), _grade(10), _grade(10)) == 10.0

    def test_min_plus_half_when_rest_are_one_higher(self):
        # min=8, rest=[9,9,9] → all >= 9 → overall = 8.5
        result = compute_final_grade(_grade(8), _grade(9), _grade(9), _grade(9))
        assert result == 8.5

    def test_no_bonus_when_rest_not_all_one_higher(self):
        # min=8, rest=[8,9,9] → not all >= 9 → overall = 8.0
        result = compute_final_grade(_grade(8), _grade(8), _grade(9), _grade(9))
        assert result == 8.0

    def test_none_when_any_criterion_errored(self):
        result = compute_final_grade(_grade(9), _err(), _grade(9), _grade(9))
        assert result is None

    def test_none_when_criterion_missing(self):
        result = compute_final_grade(_grade(9), None, _grade(9), _grade(9))
        assert result is None

    def test_capped_at_10(self):
        # Should never exceed 10.0 from normal grading
        result = compute_final_grade(_grade(10), _grade(10), _grade(10), _grade(10))
        assert result <= 10.0

    def test_all_same_grade_no_bonus(self):
        # min=7, rest=[7,7,7] → not all >= 8 → overall = 7.0
        result = compute_final_grade(_grade(7), _grade(7), _grade(7), _grade(7))
        assert result == 7.0

    def test_one_low_drags_down(self):
        # min=5, rest=[9,9,9] → all >= 6 → overall = 5.5
        result = compute_final_grade(_grade(5), _grade(9), _grade(9), _grade(9))
        assert result == 5.5

    def test_two_lows_no_bonus(self):
        # min=5, rest=[5,9,9] → not all >= 6 → overall = 5.0
        result = compute_final_grade(_grade(5), _grade(5), _grade(9), _grade(9))
        assert result == 5.0


class TestBuildGradeReport:
    def test_builds_report_with_overall(self):
        report = build_grade_report(_grade(9), _grade(9), _grade(9), _grade(9))
        assert report.overall == 9.0
        assert report.centering is not None

    def test_report_none_overall_on_error(self):
        report = build_grade_report(_grade(9), _err(), _grade(9), _grade(9))
        assert report.overall is None
