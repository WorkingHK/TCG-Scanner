"""Async orchestrator — runs the full grading pipeline on one card."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
import cv2

from .capture import MockCamera, RealCamera, UVCCamera
from .centering import grade_centering
from .corners import grade_corners
from .detect import detect_card
from .edges import grade_edges
from .final_grade import compute_final_grade
from .surface import grade_surface
from .types import CardImage, GradeReport

logger = logging.getLogger(__name__)


async def grade_card(
    image_path: Optional[str | Path] = None,
    use_camera: bool = False,
    camera_index: int = 1,          # 1 = first USB camera (0 = built-in)
    rotate_90_cw: bool = False,     # rotate camera capture 90° clockwise
    fixtures_dir: Optional[str | Path] = None,
    output_dir: Optional[str | Path] = None,
    api_key: Optional[str] = None,
) -> GradeReport:
    """
    Full grading pipeline. Provide exactly one of:
      - image_path: path to an existing image file
      - use_camera=True: capture via gphoto2 (RealCamera)
      - fixtures_dir: use MockCamera from that directory

    Args:
        image_path: Path to a card image to grade.
        use_camera: If True, capture from the tethered camera.
        camera_index: Camera index for gphoto2 (default 0).
        rotate_90_cw: Rotate camera capture 90° clockwise.
        fixtures_dir: Directory for MockCamera (dev/test mode).
        output_dir: Where to save crops/results. Defaults to captures/<date>/<ts>/.
        api_key: Anthropic API key (falls back to ANTHROPIC_API_KEY env var).

    Returns:
        GradeReport with four sub-grades and overall grade.
    """
    # ------------------------------------------------------------------ setup
    import os
    base_url = os.environ.get("ANTHROPIC_BASE_URL")

    if api_key:
        client = anthropic.Anthropic(api_key=api_key, base_url=base_url) if base_url else anthropic.Anthropic(api_key=api_key)
    else:
        client = anthropic.Anthropic(base_url=base_url) if base_url else anthropic.Anthropic()

    ts = datetime.now()
    if output_dir is None:
        output_dir = Path("captures") / ts.strftime("%Y-%m-%d") / ts.strftime("%H%M%S")
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------- capture
    card_image: CardImage
    if image_path is not None:
        path = Path(image_path)
        import numpy as np
        from PIL import Image
        rgb = np.array(Image.open(path).convert("RGB"))
        card_image = CardImage(path=path, rgb=rgb, captured_at=ts)
        logger.info("Loaded image from %s", path)
    elif use_camera:
        cam = UVCCamera(camera_index=camera_index, rotate_90_cw=rotate_90_cw)
        card_image = cam.capture()
        cam.close()
        logger.info("Captured from UVCCamera index %d", camera_index)
    elif fixtures_dir is not None:
        cam = MockCamera(fixtures_dir=Path(fixtures_dir))
        card_image = cam.capture()
        logger.info("Loaded from MockCamera (%s)", fixtures_dir)
    else:
        raise ValueError("Provide image_path, use_camera=True, or fixtures_dir.")

    # save raw capture
    raw_path = output_dir / "raw_capture.jpg"
    cv2.imwrite(str(raw_path), cv2.cvtColor(card_image.rgb, cv2.COLOR_RGB2BGR))

    # --------------------------------------------------------------- detection
    logger.info("Detecting card outline…")
    detected = detect_card(card_image)

    rect_path = output_dir / "rectified.jpg"
    cv2.imwrite(str(rect_path), cv2.cvtColor(detected.rgb, cv2.COLOR_RGB2BGR))

    # ----------------------------------------------------------- centering (sync, fast)
    logger.info("Grading centering…")
    centering_result = grade_centering(detected)
    logger.info("Centering: %.1f (%s)", centering_result.grade, centering_result.confidence)

    # -------------------------------------------------- corners / edges / surface (parallel)
    logger.info("Grading corners, edges, surface in parallel…")

    async def _grade_corners():
        return await asyncio.to_thread(grade_corners, detected, client, output_dir)

    async def _grade_edges():
        return await asyncio.to_thread(grade_edges, detected, client, output_dir)

    async def _grade_surface():
        return await asyncio.to_thread(grade_surface, detected, client, output_dir)

    corners_result, edges_result, surface_result = await asyncio.gather(
        _grade_corners(),
        _grade_edges(),
        _grade_surface(),
        return_exceptions=False,
    )

    logger.info("Corners: %.1f  Edges: %.1f  Surface: %.1f",
                corners_result.grade, edges_result.grade, surface_result.grade)

    # ----------------------------------------------------------- final grade
    overall = compute_final_grade(centering_result, corners_result, edges_result, surface_result)
    logger.info("Overall grade: %s", f"{overall:.1f}" if overall is not None else "N/A")

    report = GradeReport(
        centering=centering_result,
        corners=corners_result,
        edges=edges_result,
        surface=surface_result,
        overall=overall,
        timestamp=ts,
        capture_path=output_dir,
    )

    # save JSON report
    report_path = output_dir / "grade_report.json"
    _save_report_json(report, report_path)

    return report


def _save_report_json(report: GradeReport, path: Path) -> None:
    """Serialize GradeReport to JSON (best-effort)."""
    def _criterion_dict(c):
        if c is None:
            return None
        return {
            "grade": c.grade,
            "confidence": c.confidence,
            "evidence": c.evidence,
            "annotated_crop_path": str(c.annotated_crop_path) if c.annotated_crop_path else None,
            "error": c.error,
        }

    data = {
        "timestamp": report.timestamp.isoformat(),
        "overall": report.overall,
        "centering": _criterion_dict(report.centering),
        "corners": _criterion_dict(report.corners),
        "edges": _criterion_dict(report.edges),
        "surface": _criterion_dict(report.surface),
        "capture_path": str(report.capture_path) if report.capture_path else None,
    }
    path.write_text(json.dumps(data, indent=2))
    logger.info("Saved report → %s", path)
