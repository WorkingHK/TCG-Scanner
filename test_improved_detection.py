#!/usr/bin/env python3
"""
Test improved card detection techniques from reference document.

Implements:
1. Robust corner ordering using sum/diff method (already in detect.py)
2. Multi-method edge detection (Canny + adaptive threshold + morphological ops)
3. Aspect ratio + area ratio + convexity filtering
4. Multiple epsilon values for polygon approximation
5. Better parameter tuning for challenging lighting conditions

Compares with current TCG Scanner detection.
"""

import sys
from pathlib import Path
from datetime import datetime
import cv2
import numpy as np
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)


def order_points(pts: np.ndarray) -> np.ndarray:
    """
    Order 4 corner points as [top-left, top-right, bottom-right, bottom-left].
    Uses sum/diff method from reference document.
    """
    rect = np.zeros((4, 2), dtype=np.float32)

    # Sum method: smallest sum = top-left, largest = bottom-right
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # top-left
    rect[2] = pts[np.argmax(s)]  # bottom-right

    # Diff method: smallest diff = top-right, largest = bottom-left
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # top-right
    rect[3] = pts[np.argmax(diff)]  # bottom-left

    return rect


def preprocess_for_weak_edges(gray: np.ndarray) -> np.ndarray:
    """
    Enhanced preprocessing for low-contrast or complex backgrounds.
    Combines adaptive threshold + morphological operations.
    """
    # Adaptive threshold to handle lighting variations
    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        21, 10
    )

    # Morphological closing to connect broken edges
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Morphological opening to remove small noise
    opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel)

    return opened


def find_document_contour_robust(
    image: np.ndarray,
    use_enhanced_preprocessing: bool = False
) -> tuple[np.ndarray | None, dict]:
    """
    Find card contour with multi-criteria filtering.

    Filters by:
    - Aspect ratio (cards are ~1.4:1)
    - Area ratio (card should occupy reasonable portion of frame)
    - Convexity (cards are convex quadrilaterals)

    Returns: (quad_points, debug_info)
    """
    h, w = image.shape[:2]
    img_area = h * w
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

    debug = {
        'method': None,
        'contours_found': 0,
        'quad_candidates': 0,
        'filtered_by_aspect': 0,
        'filtered_by_area': 0,
        'filtered_by_convexity': 0,
    }

    # Resize for faster processing if image is very large
    target_width = 800
    if w > target_width:
        ratio = w / target_width
        resized = cv2.resize(gray, (target_width, int(h / ratio)))
        log.info(f"Resized {w}×{h} to {resized.shape[1]}×{resized.shape[0]} for detection")
    else:
        ratio = 1.0
        resized = gray

    # Choose preprocessing method
    if use_enhanced_preprocessing:
        edges = preprocess_for_weak_edges(resized)
        debug['method'] = 'adaptive_threshold_morph'
    else:
        # Standard Canny edge detection
        blurred = cv2.GaussianBlur(resized, (5, 5), 0)
        edges = cv2.Canny(blurred, 75, 200)  # Reference doc uses these thresholds
        # Dilate to close small gaps
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=1)
        debug['method'] = 'canny'

    # Find contours
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    debug['contours_found'] = len(contours)

    if not contours:
        log.warning("No contours found")
        return None, debug

    # Sort by area (largest first)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]

    # Calculate area on resized image
    resized_area = resized.shape[0] * resized.shape[1]

    # Try each contour with multiple epsilon values
    for cnt in contours:
        area = cv2.contourArea(cnt)
        area_ratio = area / resized_area

        # Area filter: 10% - 95% of image
        if area_ratio < 0.10 or area_ratio > 0.95:
            debug['filtered_by_area'] += 1
            continue

        peri = cv2.arcLength(cnt, True)

        # Try multiple epsilon values (reference doc suggests this)
        for epsilon_factor in [0.02, 0.015, 0.01, 0.005]:
            approx = cv2.approxPolyDP(cnt, epsilon_factor * peri, True)

            if len(approx) == 4:
                debug['quad_candidates'] += 1

                # Check convexity
                is_convex = cv2.isContourConvex(approx)
                if not is_convex:
                    debug['filtered_by_convexity'] += 1
                    continue

                # Check aspect ratio
                rect = cv2.minAreaRect(approx)
                rect_w, rect_h = rect[1]
                if rect_w == 0 or rect_h == 0:
                    continue

                aspect = max(rect_w, rect_h) / min(rect_w, rect_h)

                # Pokemon cards are 63mm × 88mm = aspect ~1.397
                # Allow 1.0 - 2.0 range (reference doc uses 0.7-1.4, we're more lenient)
                if aspect < 1.0 or aspect > 2.0:
                    debug['filtered_by_aspect'] += 1
                    continue

                # Found a good candidate!
                quad = approx.reshape(4, 2).astype(np.float32)
                # Scale back to original image coordinates
                quad = quad * ratio
                log.info(f"✓ Found card: area={area_ratio*100:.1f}%, aspect={aspect:.2f}, " +
                        f"convex={is_convex}, epsilon={epsilon_factor}")
                return quad, debug

    log.warning(f"No valid card quad found. Tried {debug['contours_found']} contours, " +
               f"found {debug['quad_candidates']} quads, filtered {debug['filtered_by_aspect']} by aspect, " +
               f"{debug['filtered_by_area']} by area, {debug['filtered_by_convexity']} by convexity")
    return None, debug


def four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """
    Perspective transform to rectify card to rectangular view.
    From reference document.
    """
    # Order the points
    rect = order_points(pts)
    (tl, tr, br, bl) = rect

    # Calculate width: max of top and bottom edge lengths
    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))

    # Calculate height: max of left and right edge lengths
    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))

    # Target rectangle corners
    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]
    ], dtype=np.float32)

    # Compute perspective transform matrix
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))

    return warped


def compare_detection_methods(image_path: str):
    """Compare current TCG Scanner detection vs improved reference doc method."""
    # Load image
    image = cv2.imread(image_path)
    if image is None:
        log.error(f"Failed to load image: {image_path}")
        return

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]

    log.info(f"\n{'='*60}")
    log.info(f"Testing: {Path(image_path).name}")
    log.info(f"Image size: {w}×{h}")
    log.info(f"{'='*60}\n")

    # ===== METHOD 1: Reference Document Approach (Canny) =====
    log.info("METHOD 1: Reference Document (Canny + Multi-Epsilon)")
    log.info("-" * 60)
    quad_ref, debug_ref = find_document_contour_robust(image, use_enhanced_preprocessing=False)

    if quad_ref is not None:
        warped_ref = four_point_transform(image, quad_ref)
        cv2.imwrite("output_ref_canny.jpg", warped_ref)
        log.info(f"✓ Success! Saved to output_ref_canny.jpg")
        log.info(f"  Rectified size: {warped_ref.shape[1]}×{warped_ref.shape[0]}")
    else:
        log.warning("✗ Failed to detect card")

    log.info(f"  Debug: {debug_ref}\n")

    # ===== METHOD 2: Reference Document Approach (Enhanced) =====
    log.info("METHOD 2: Reference Document (Adaptive Threshold + Morphology)")
    log.info("-" * 60)
    quad_enh, debug_enh = find_document_contour_robust(image, use_enhanced_preprocessing=True)

    if quad_enh is not None:
        warped_enh = four_point_transform(image, quad_enh)
        cv2.imwrite("output_ref_enhanced.jpg", warped_enh)
        log.info(f"✓ Success! Saved to output_ref_enhanced.jpg")
        log.info(f"  Rectified size: {warped_enh.shape[1]}×{warped_enh.shape[0]}")
    else:
        log.warning("✗ Failed to detect card")

    log.info(f"  Debug: {debug_enh}\n")

    # ===== METHOD 3: Current TCG Scanner =====
    log.info("METHOD 3: Current TCG Scanner Detection")
    log.info("-" * 60)
    try:
        from tcg_grading.detect import detect_card
        from tcg_grading.types import CardImage

        card_img = CardImage(
            path=Path(image_path),
            rgb=rgb,
            captured_at=datetime.now()
        )
        detected = detect_card(card_img)

        cv2.imwrite("output_tcg_scanner.jpg", cv2.cvtColor(detected.rgb, cv2.COLOR_RGB2BGR))
        log.info(f"✓ Success! Saved to output_tcg_scanner.jpg")
        log.info(f"  Rectified size: {detected.rgb.shape[1]}×{detected.rgb.shape[0]}")
        log.info(f"  Pixels per mm: {detected.pixels_per_mm:.2f}")
        if detected.inner_frame:
            log.info(f"  Inner frame detected: {detected.inner_frame.points}")
    except Exception as e:
        log.error(f"✗ TCG Scanner failed: {e}")

    # ===== Create comparison visualization =====
    log.info(f"\n{'='*60}")
    log.info("Creating side-by-side comparison...")
    log.info(f"{'='*60}\n")

    # Draw detection results on original image
    vis = image.copy()

    # Draw Method 1 result (green)
    if quad_ref is not None:
        ordered_ref = order_points(quad_ref).astype(np.int32)
        cv2.polylines(vis, [ordered_ref], True, (0, 255, 0), 3)
        cv2.putText(vis, "Ref:Canny", tuple(ordered_ref[0]),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    # Draw Method 2 result (blue)
    if quad_enh is not None:
        ordered_enh = order_points(quad_enh).astype(np.int32)
        cv2.polylines(vis, [ordered_enh], True, (255, 0, 0), 2)
        cv2.putText(vis, "Ref:Enhanced", tuple(ordered_enh[0] + [0, 30]),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)

    cv2.imwrite("output_comparison.jpg", vis)
    log.info("✓ Saved comparison visualization to output_comparison.jpg")
    log.info("  Green = Reference (Canny), Blue = Reference (Enhanced)\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_improved_detection.py <image_path>")
        print("\nTry with test fixtures:")
        print("  python test_improved_detection.py tests/fixtures/pikachu_001.jpg")
        sys.exit(1)

    image_path = sys.argv[1]
    compare_detection_methods(image_path)
