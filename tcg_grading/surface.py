"""Surface grading: CV pre-detection + VLM assessment."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .types import DetectedCard, CriterionGrade
from .rubric import SURFACE_RUBRIC

logger = logging.getLogger(__name__)

CARD_MAX_PX = 2048  # max long side before upload
TILE_MAX_PX = 1024  # high-res tile crops


def _encode_image(img: np.ndarray, max_px: int = CARD_MAX_PX) -> str:
    """Resize if needed and base64-encode as JPEG."""
    h, w = img.shape[:2]
    if max(h, w) > max_px:
        scale = max_px / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return base64.b64encode(buf.tobytes()).decode()


def _detect_surface_defects(rgb: np.ndarray) -> tuple[np.ndarray, dict]:
    """
    Pre-detect candidate surface defects using morphological ops + Hough lines.
    Returns annotated image copy and evidence dict.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    annotated = rgb.copy()
    evidence: dict = {}

    # --- Scratch detection via top-hat morphology ---
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
    _, scratch_mask = cv2.threshold(tophat, 30, 255, cv2.THRESH_BINARY)
    scratch_pixel_count = int(np.sum(scratch_mask > 0))
    evidence["scratch_candidate_pixels"] = scratch_pixel_count

    # Overlay scratch candidates in red
    annotated[scratch_mask > 0] = [255, 80, 80]

    # --- Print line / refractor detection via Hough ---
    edges = cv2.Canny(gray, 30, 100)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80, minLineLength=40, maxLineGap=10)
    line_count = 0
    if lines is not None:
        line_count = len(lines)
        for line in lines[:20]:  # annotate first 20
            x1, y1, x2, y2 = line[0]
            cv2.line(annotated, (x1, y1), (x2, y2), (80, 80, 255), 1)
    evidence["hough_line_count"] = line_count

    # Derive a simple severity estimate for the evidence panel
    total_px = gray.shape[0] * gray.shape[1]
    scratch_pct = scratch_pixel_count / total_px * 100
    evidence["scratch_coverage_pct"] = round(scratch_pct, 3)

    return annotated, evidence


def _compute_cv_base_score(cv_evidence: dict) -> Optional[float]:
    """
    Compute base surface grade from CV measurements.
    Maps scratch_coverage_pct and hough_line_count to 0-1000 scale.
    Returns None if insufficient data.
    """
    scratch_pct = cv_evidence.get("scratch_coverage_pct", 0)
    line_count = cv_evidence.get("hough_line_count", 0)

    # Score scratch coverage: 0-0.1%=1000, 0.1-0.5%=900, 0.5-1%=800, 1-2%=700, 2-5%=500, >5%=lower
    if scratch_pct <= 0.1:
        scratch_score = 1000.0
    elif scratch_pct <= 0.5:
        scratch_score = 900.0
    elif scratch_pct <= 1.0:
        scratch_score = 800.0
    elif scratch_pct <= 2.0:
        scratch_score = 700.0
    elif scratch_pct <= 5.0:
        scratch_score = 500.0
    else:
        scratch_score = max(100.0, 500.0 - (scratch_pct - 5.0) * 30.0)

    # Score line count: 0-20=1000, 20-50=900, 50-100=800, 100-200=600, >200=lower
    # Note: Hough lines can detect card artwork details, so be lenient
    if line_count <= 20:
        line_score = 1000.0
    elif line_count <= 50:
        line_score = 900.0
    elif line_count <= 100:
        line_score = 800.0
    elif line_count <= 200:
        line_score = 600.0
    else:
        line_score = max(100.0, 600.0 - (line_count - 200) * 10.0)

    # Take worse of the two metrics
    base_score = min(scratch_score, line_score)
    return base_score


def _select_tiles(rgb: np.ndarray, n: int = 2) -> list[np.ndarray]:
    """Select n high-res tile crops from areas with most defect candidates."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)

    h, w = rgb.shape[:2]
    tile_h, tile_w = h // 3, w // 3
    tiles_scored: list[tuple[float, np.ndarray]] = []

    for row in range(3):
        for col in range(3):
            y0, y1 = row * tile_h, (row + 1) * tile_h
            x0, x1 = col * tile_w, (col + 1) * tile_w
            score = float(np.sum(tophat[y0:y1, x0:x1]))
            tiles_scored.append((score, rgb[y0:y1, x0:x1]))

    tiles_scored.sort(key=lambda t: t[0], reverse=True)
    return [t[1] for t in tiles_scored[:n]]


def grade_surface(
    card: DetectedCard,
    client,  # anthropic.Anthropic
    output_dir: Optional[Path] = None,
) -> CriterionGrade:
    """Grade card surface using CV pre-detection + VLM assessment."""
    try:
        annotated, cv_evidence = _detect_surface_defects(card.rgb)

        # Save annotated image
        annotated_path: Optional[Path] = None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            annotated_path = output_dir / "surface_annotated.jpg"
            cv2.imwrite(str(annotated_path), cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR))

        # Select high-res tile crops from worst areas
        tiles = _select_tiles(card.rgb, n=2)

        # Build VLM message content
        content: list[dict] = []

        # Main annotated card image
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": _encode_image(annotated, max_px=CARD_MAX_PX),
            }
        })
        content.append({
            "type": "text",
            "text": "Above: full card with CV-detected scratch candidates (red overlay) and edge lines (blue overlay)."
        })

        # Tile crops
        for i, tile in enumerate(tiles):
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": _encode_image(tile, max_px=TILE_MAX_PX),
                }
            })
            content.append({
                "type": "text",
                "text": f"High-res tile crop #{i+1} (area with most CV-detected candidates)."
            })

        # CV evidence summary
        content.append({
            "type": "text",
            "text": (
                f"CV measurements:\n"
                f"  Scratch candidate pixels: {cv_evidence['scratch_candidate_pixels']}\n"
                f"  Scratch coverage: {cv_evidence['scratch_coverage_pct']:.3f}%\n"
                f"  Hough line count: {cv_evidence['hough_line_count']}\n\n"
                f"Note: CV detects candidates; VLM should distinguish real defects from printing texture."
            )
        })

        content.append({
            "type": "text",
            "text": "Please grade the surface condition of this card. Return ONLY valid JSON as specified in the rubric."
        })

        # VLM call with prompt caching on system prompt
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SURFACE_RUBRIC,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": content}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown fences before parsing
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(raw)

        # Validate required keys
        required = {"observations", "grade", "confidence", "reasoning"}
        if not required.issubset(result.keys()):
            raise ValueError(f"VLM response missing keys: {required - result.keys()}")

        vlm_grade_1000 = float(result["grade"])  # VLM now returns 0-1000 scale
        if not (100.0 <= vlm_grade_1000 <= 1000.0):
            raise ValueError(f"Grade out of range: {vlm_grade_1000}")

        # CV-driven scoring: use CV metrics as base (0-1000), VLM adjusts ±50
        cv_base_score = _compute_cv_base_score(cv_evidence)

        # Blend: CV base score + VLM adjustment (clamped to ±50 from CV base)
        if cv_base_score is not None:
            # VLM can adjust by up to ±50 points from CV base
            adjustment = vlm_grade_1000 - cv_base_score
            adjustment = max(-50.0, min(50.0, adjustment))
            final_grade = cv_base_score + adjustment
            final_grade = max(100.0, min(1000.0, final_grade))
        else:
            # Fallback: no CV base, trust VLM fully
            final_grade = vlm_grade_1000
            adjustment = 0

        # Grade is 0-1000 (TAG scale)
        evidence = {
            "cv": cv_evidence,
            "cv_base_score_1000": cv_base_score,
            "vlm_raw_grade_1000": vlm_grade_1000,
            "vlm_adjustment": round(adjustment, 1),
            "final_grade_1000": round(final_grade, 0),
            "vlm_observations": result.get("observations", ""),
            "vlm_reasoning": result.get("reasoning", ""),
        }

        return CriterionGrade(
            grade=final_grade,  # 0-1000 scale
            confidence=result.get("confidence", "medium"),
            evidence=evidence,
            annotated_crop_path=annotated_path,
        )

    except json.JSONDecodeError as e:
        logger.warning(f"Surface VLM returned malformed JSON, retrying: {e}")
        # One retry with explicit JSON reminder
        try:
            retry_content = content + [{
                "type": "text",
                "text": "Your previous response was not valid JSON. Return ONLY a JSON object, no markdown, no explanation."
            }]
            response = client.messages.create(
                model="claude-opus-4-7",
                max_tokens=1024,
                system=[{"type": "text", "text": SURFACE_RUBRIC, "cache_control": {"type": "ephemeral"}}],
                messages=[
                    {"role": "user", "content": content},
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": retry_content[-1:]},
                ],
            )
            result = json.loads(response.content[0].text.strip())
            vlm_grade_10 = float(result["grade"])
            vlm_grade_1000 = vlm_grade_10 * 100.0

            # Apply same CV-VLM blending for retry path
            cv_base_score = _compute_cv_base_score(cv_evidence)
            if cv_base_score is not None:
                adjustment = vlm_grade_1000 - cv_base_score
                adjustment = max(-50.0, min(50.0, adjustment))
                final_grade = cv_base_score + adjustment
                final_grade = max(100.0, min(1000.0, final_grade))
            else:
                final_grade = vlm_grade_1000
                adjustment = 0

            # Convert back to 1-10 scale
            grade = final_grade / 100.0

            evidence = {
                "cv": cv_evidence,
                "cv_base_score_1000": cv_base_score,
                "vlm_raw_grade_1000": vlm_grade_1000,
                "vlm_adjustment": round(adjustment, 1),
                "final_grade_1000": round(final_grade, 0),
                "vlm_observations": result.get("observations", ""),
                "vlm_reasoning": result.get("reasoning", ""),
            }
            return CriterionGrade(
                grade=grade,
                confidence=result.get("confidence", "low"),
                evidence=evidence,
                annotated_crop_path=annotated_path,
            )
        except Exception as retry_err:
            return CriterionGrade(
                grade=5.0,
                confidence="low",
                evidence={"cv": cv_evidence, "error": str(retry_err)},
                annotated_crop_path=annotated_path,
                error=f"Surface VLM retry failed: {retry_err}",
            )

    except Exception as e:
        logger.error(f"Surface grading failed: {e}")
        return CriterionGrade(
            grade=5.0,
            confidence="low",
            evidence={"error": str(e)},
            annotated_crop_path=None,
            error=str(e),
        )
