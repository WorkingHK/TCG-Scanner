"""Integration tests for the grading pipeline using MockCamera."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from tcg_grading.final_grade import compute_final_grade, build_grade_report
from tcg_grading.types import CriterionGrade, GradeReport
from tcg_grading.capture import MockCamera


def _grade(g: float) -> CriterionGrade:
    return CriterionGrade(grade=g, confidence="high", evidence={}, annotated_crop_path=None)


# ---------------------------------------------------------------------------
# MockCamera tests (no API key needed)
# ---------------------------------------------------------------------------

class TestMockCamera:
    def test_mock_camera_raises_on_empty_dir(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            MockCamera(fixtures_dir=tmp_path)

    def test_mock_camera_loads_fixture(self, tmp_path):
        import cv2
        # Create a synthetic card image and save it
        img = np.ones((880, 630, 3), dtype=np.uint8) * 200
        cv2.imwrite(str(tmp_path / "card.jpg"), img)

        cam = MockCamera(fixtures_dir=tmp_path)
        card = cam.capture()
        assert card.rgb is not None
        assert card.rgb.shape[2] == 3
        assert card.path.exists()

    def test_mock_camera_cycles_fixtures(self, tmp_path):
        import cv2
        for i in range(2):
            img = np.ones((880, 630, 3), dtype=np.uint8) * (100 + i * 50)
            cv2.imwrite(str(tmp_path / f"card_{i}.jpg"), img)

        cam = MockCamera(fixtures_dir=tmp_path)
        c1 = cam.capture()
        c2 = cam.capture()
        c3 = cam.capture()  # should wrap back to first
        assert c3.path.name == c1.path.name


# ---------------------------------------------------------------------------
# Pipeline smoke test with mocked VLM (no API key needed)
# ---------------------------------------------------------------------------

class TestGradeCardPipeline:
    """Smoke test the pipeline end-to-end with VLM calls mocked out."""

    def _make_fixture(self, tmp_path: Path) -> Path:
        """Create a synthetic card image that detect_card can find."""
        import cv2
        # White card on black background — 630×880 card in 900×1200 frame
        img = np.zeros((1200, 900, 3), dtype=np.uint8)
        img[160:1040, 135:765] = 240  # white card region
        path = tmp_path / "synthetic_card.jpg"
        cv2.imwrite(str(path), img)
        return path

    def test_grade_card_with_image_path(self, tmp_path):
        """Run grade_card with a local image path and mocked VLM."""
        fixture = self._make_fixture(tmp_path)

        mock_vlm_response = MagicMock()
        mock_vlm_response.content = [
            MagicMock(
                text='{"per_corner": {"top_left": {"observation": "ok", "severity": "none"}, '
                     '"top_right": {"observation": "ok", "severity": "none"}, '
                     '"bottom_left": {"observation": "ok", "severity": "none"}, '
                     '"bottom_right": {"observation": "ok", "severity": "none"}}, '
                     '"worst_corner": "top_left", "worst_corner_observation": "fine", '
                     '"grade": 8.5, "confidence": "high", "reasoning": "All corners sharp."}'
            )
        ]

        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_vlm_response
            mock_cls.return_value = mock_client

            report = asyncio.run(
                __import__("tcg_grading.pipeline", fromlist=["grade_card"]).grade_card(
                    image_path=fixture,
                    output_dir=tmp_path / "out",
                )
            )

        assert isinstance(report, GradeReport)
        # Centering is pure CV — should have a grade
        assert report.centering is not None

    def test_grade_report_summary_format(self):
        """GradeReport.summary() should produce readable output."""
        report = build_grade_report(
            _grade(9.0), _grade(8.5), _grade(8.0), _grade(9.0),
        )
        summary = report.summary()
        assert "Centering" in summary
        assert "OVERALL" in summary
        assert "9.0" in summary or "8.5" in summary


# ---------------------------------------------------------------------------
# GradeReport property tests
# ---------------------------------------------------------------------------

class TestGradeReport:
    def test_all_criteria_ok_true_when_no_errors(self):
        report = build_grade_report(_grade(9), _grade(8), _grade(7), _grade(10))
        assert report.all_criteria_ok is True

    def test_all_criteria_ok_false_when_error(self):
        err = CriterionGrade(grade=1.0, confidence="low", evidence={},
                             annotated_crop_path=None, error="failed")
        report = build_grade_report(_grade(9), err, _grade(7), _grade(10))
        assert report.all_criteria_ok is False

    def test_all_criteria_ok_false_when_none(self):
        report = GradeReport(
            centering=_grade(9), corners=None, edges=_grade(7), surface=_grade(8),
            overall=None,
        )
        assert report.all_criteria_ok is False
