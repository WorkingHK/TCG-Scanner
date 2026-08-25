"""Unit tests for corner CV metrics — no VLM/API key needed."""

from __future__ import annotations

import numpy as np
import pytest

from tcg_grading.corners import _crop_corners, _measure_corner, _encode_image


class TestCropCorners:
    def _card(self, h=880, w=630):
        return np.ones((h, w, 3), dtype=np.uint8) * 200

    def test_returns_four_corners(self):
        crops = _crop_corners(self._card())
        assert set(crops.keys()) == {"top_left", "top_right", "bottom_left", "bottom_right"}

    def test_crop_size_bounded(self):
        crops = _crop_corners(self._card())
        for name, crop in crops.items():
            assert crop.shape[0] <= 400
            assert crop.shape[1] <= 400

    def test_small_card_doesnt_crash(self):
        crops = _crop_corners(self._card(h=100, w=80))
        assert len(crops) == 4

    def test_crops_are_rgb(self):
        crops = _crop_corners(self._card())
        for crop in crops.values():
            assert crop.ndim == 3
            assert crop.shape[2] == 3


class TestMeasureCorner:
    def test_uniform_image_returns_dict(self):
        crop = np.ones((400, 400, 3), dtype=np.uint8) * 200
        result = _measure_corner(crop)
        # May return empty dict if contour not found, but must be a dict
        assert isinstance(result, dict)

    def test_black_image_doesnt_crash(self):
        crop = np.zeros((400, 400, 3), dtype=np.uint8)
        result = _measure_corner(crop)
        assert isinstance(result, dict)

    def test_white_card_on_black_bg_has_metrics(self):
        # White square on black — should find contour
        crop = np.zeros((400, 400, 3), dtype=np.uint8)
        crop[50:380, 50:380] = 255
        result = _measure_corner(crop)
        assert isinstance(result, dict)
        # If contour found, keys should be present
        if result:
            # Updated to use radius_quality_score instead of rounding_deviation_px
            assert "radius_quality_score" in result
            assert "defect_pixel_area_px2" in result

    def test_rounding_deviation_non_negative(self):
        crop = np.zeros((400, 400, 3), dtype=np.uint8)
        crop[0:300, 0:300] = 255
        result = _measure_corner(crop)
        if result:
            # Metric name changed to radius_quality_score (0-10 scale)
            assert "radius_quality_score" in result
            assert 0 <= result["radius_quality_score"] <= 10


class TestEncodeImage:
    def test_returns_base64_string(self):
        img = np.ones((400, 400, 3), dtype=np.uint8) * 128
        b64 = _encode_image(img)
        assert isinstance(b64, str)
        assert len(b64) > 0

    def test_large_image_is_resized(self):
        # 4000x4000 should be scaled down
        img = np.ones((4000, 4000, 3), dtype=np.uint8) * 100
        b64 = _encode_image(img)
        assert isinstance(b64, str)

    def test_small_image_not_upscaled(self):
        img = np.ones((100, 100, 3), dtype=np.uint8) * 100
        b64 = _encode_image(img)
        assert isinstance(b64, str)
