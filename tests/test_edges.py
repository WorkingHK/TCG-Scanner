"""Tests for edge grading — CV metrics only (no API key needed)."""

from __future__ import annotations

import numpy as np
import pytest

from tcg_grading.edges import _crop_edge_strips, _measure_edge
from tcg_grading.types import DetectedCard, Polygon


def _make_card(w: int = 630, h: int = 880) -> DetectedCard:
    rgb = np.ones((h, w, 3), dtype=np.uint8) * 200
    return DetectedCard(
        rgb=rgb,
        pixels_per_mm=10.0,
        outer_corners=[(0, 0), (w - 1, 0), (w - 1, h - 1), (0, h - 1)],
        inner_frame=None,
    )


class TestCropEdgeStrips:
    def test_returns_four_strips(self):
        card = _make_card()
        strips = _crop_edge_strips(card.rgb)
        assert set(strips.keys()) == {"top", "bottom", "left", "right"}

    def test_horizontal_strips_correct_height(self):
        card = _make_card()
        strips = _crop_edge_strips(card.rgb)
        from tcg_grading.edges import EDGE_STRIP_HEIGHT
        assert strips["top"].shape[0] == EDGE_STRIP_HEIGHT
        assert strips["bottom"].shape[0] == EDGE_STRIP_HEIGHT

    def test_vertical_strips_correct_width(self):
        card = _make_card()
        strips = _crop_edge_strips(card.rgb)
        from tcg_grading.edges import EDGE_STRIP_HEIGHT
        assert strips["left"].shape[1] == EDGE_STRIP_HEIGHT
        assert strips["right"].shape[1] == EDGE_STRIP_HEIGHT

    def test_strips_are_rgb(self):
        card = _make_card()
        strips = _crop_edge_strips(card.rgb)
        for name, strip in strips.items():
            assert strip.ndim == 3, f"{name} strip should be RGB"
            assert strip.shape[2] == 3


class TestMeasureEdge:
    def test_returns_dict(self):
        strip = np.ones((150, 630, 3), dtype=np.uint8) * 200
        result = _measure_edge(strip, "horizontal")
        assert isinstance(result, dict)

    def test_uniform_strip_has_keys(self):
        strip = np.ones((150, 630, 3), dtype=np.uint8) * 200
        result = _measure_edge(strip, "horizontal")
        # Should either return metrics or an error key
        assert "rms_deviation" in result or "error" in result

    def test_does_not_crash_on_black_strip(self):
        strip = np.zeros((150, 630, 3), dtype=np.uint8)
        result = _measure_edge(strip, "horizontal")
        assert isinstance(result, dict)

    def test_does_not_crash_on_vertical_orientation(self):
        strip = np.ones((880, 150, 3), dtype=np.uint8) * 200
        result = _measure_edge(strip, "vertical")
        assert isinstance(result, dict)
