"""Card outline detection and perspective rectification."""

from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

from .types import CardImage, DetectedCard, Point, Polygon

log = logging.getLogger(__name__)

# Canonical card dimensions in mm (standard Pokemon card: 63 x 88 mm)
CARD_WIDTH_MM = 63.0
CARD_HEIGHT_MM = 88.0
CARD_ASPECT = CARD_HEIGHT_MM / CARD_WIDTH_MM  # ~1.397

# Output rectified image dimensions (pixels)
CANONICAL_WIDTH = 630
CANONICAL_HEIGHT = 880


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as [top-left, top-right, bottom-right, bottom-left]."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # top-left: smallest sum
    rect[2] = pts[np.argmax(s)]   # bottom-right: largest sum
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # top-right: smallest diff
    rect[3] = pts[np.argmax(diff)]  # bottom-left: largest diff
    return rect


def _find_card_edge_from_black_background(rgb: np.ndarray) -> Optional[np.ndarray]:
    """
    Find the TRUE card edge by detecting where the card meets the black background.

    This filters out the black PLA frame first, then finds the boundary between
    card and background. This captures the actual physical edge including the
    silver/grey card border.

    Returns:
        4-point quadrilateral of the true card edge, or None if not found
    """
    h, w = rgb.shape[:2]
    img_area = h * w

    # Convert to HSV for better black detection
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # Method 1: Detect black background using brightness + saturation
    # Black PLA: low brightness AND low saturation
    # Relaxed thresholds to work with various lighting conditions
    v_channel = hsv[:, :, 2]
    s_channel = hsv[:, :, 1]

    # More lenient threshold: V < 80 (was 60), S < 70 (was 50)
    black_mask = (v_channel < 80) & (s_channel < 70)
    black_mask = black_mask.astype(np.uint8) * 255

    # Check if we actually detected significant black area (at least 5% of image)
    black_area_pct = (black_mask > 0).sum() / img_area * 100
    log.info(f"Black background detected: {black_area_pct:.1f}% of image")

    if black_area_pct < 5:
        log.warning(f"Insufficient black background detected ({black_area_pct:.1f}%), skipping black background method")
        return None

    # Clean up the mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    black_mask = cv2.morphologyEx(black_mask, cv2.MORPH_CLOSE, kernel, iterations=3)
    black_mask = cv2.morphologyEx(black_mask, cv2.MORPH_OPEN, kernel, iterations=2)

    # Invert: 255 = card, 0 = black background
    card_mask = cv2.bitwise_not(black_mask)

    # Find the card contour from this mask
    contours, _ = cv2.findContours(card_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        log.warning("No contours found in card mask")
        return None

    # Find largest contour (should be the card)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for cnt in contours[:3]:
        area = cv2.contourArea(cnt)
        area_pct = area / img_area * 100

        # Skip if too small or too large
        if area_pct < 10 or area_pct > 95:
            continue

        peri = cv2.arcLength(cnt, True)

        # Try multiple epsilon values for polygon approximation
        for epsilon_factor in [0.02, 0.015, 0.01, 0.005]:
            approx = cv2.approxPolyDP(cnt, epsilon_factor * peri, True)

            if len(approx) == 4:
                rect = cv2.minAreaRect(approx)
                w_rect, h_rect = rect[1]
                if w_rect > 0 and h_rect > 0:
                    aspect = max(w_rect, h_rect) / min(w_rect, h_rect)
                    if 1.0 <= aspect <= 2.0:
                        log.info(f"Found card edge from black background: area={area_pct:.1f}%, aspect={aspect:.2f}")
                        return approx.reshape(4, 2).astype(np.float32)

        # Fallback: use minAreaRect
        if area_pct > 20:
            rect = cv2.minAreaRect(cnt)
            w_rect, h_rect = rect[1]
            if w_rect > 0 and h_rect > 0:
                aspect = max(w_rect, h_rect) / min(w_rect, h_rect)
                if 1.0 <= aspect <= 2.0:
                    log.info(f"Found card edge via minAreaRect from black mask: area={area_pct:.1f}%, aspect={aspect:.2f}")
                    box = cv2.boxPoints(rect)
                    return box.astype(np.float32)

    log.warning("Could not find valid card quadrilateral from black background mask")
    return None
    """Find the largest quadrilateral contour that looks like a card."""
    # Blur + Canny
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)
    # Dilate to close gaps
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Sort by area descending
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    img_area = gray.shape[0] * gray.shape[1]

    for cnt in contours[:10]:
        area = cv2.contourArea(cnt)
        if area < img_area * 0.1:
            break  # too small

        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)

        if len(approx) == 4:
            # Check aspect ratio is roughly card-like
            rect = cv2.minAreaRect(approx)
            w, h = rect[1]
            if w == 0 or h == 0:
                continue
            aspect = max(w, h) / min(w, h)
            if 1.2 <= aspect <= 1.6:
                log.info(f"Found card: area={area:.0f} ({area/img_area*100:.1f}%), aspect={aspect:.2f}")
                return approx.reshape(4, 2).astype(np.float32)

    log.warning(f"No card-like quad in top {min(10, len(contours))} contours")
    return None


def _check_card_present(rgb: np.ndarray, mask: np.ndarray, contour_area_pct: float) -> bool:
    """
    Verify that the detected region actually contains a card, not just background.

    Checks:
    - Region has sufficient color variation (not solid color background)
    - Has edges/features typical of printed cards

    Returns True if a card is likely present.
    """
    # Check 1: Area - warn if unusual but don't reject based on this alone
    if contour_area_pct < 5:
        log.warning(f"Card area {contour_area_pct:.1f}% is very small")
        return False

    # Check 2: Rectified card should have color variation (not uniform background)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h_std = hsv[:,:,0].std()
    s_std = hsv[:,:,1].std()
    v_std = hsv[:,:,2].std()

    # A real card has artwork, text, borders → high variation
    # A uniform background has low variation
    if h_std < 10 and s_std < 20 and v_std < 20:
        log.warning(f"Rectified region has low color variation (H_std={h_std:.1f}, S_std={s_std:.1f}, V_std={v_std:.1f}) - likely uniform background, not a card")
        return False

    # Check 3: Real cards have edges/details (high frequency content)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    edge_variance = laplacian.var()

    if edge_variance < 50:
        log.warning(f"Rectified region has low edge variance ({edge_variance:.1f}) - likely blank, not a card")
        return False

    log.info(f"Card presence validated: area={contour_area_pct:.1f}%, color_var=(H:{h_std:.1f}, S:{s_std:.1f}, V:{v_std:.1f}), edges={edge_variance:.1f}")
    return True


def _mask_blue_background(rgb: np.ndarray, reference_blue: Optional[np.ndarray] = None) -> np.ndarray:
    """
    Mask out background using multiple methods and return the best card mask.
    Returns a binary mask where 255 = card, 0 = background.
    """
    h, w = rgb.shape[:2]
    img_area = h * w
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # Method 1: Canny edge detection to find card boundaries
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, kernel, iterations=2)

    # Find contours from edges
    edge_contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    edge_mask = np.zeros_like(gray)
    if edge_contours:
        # Draw the largest contours
        edge_contours = sorted(edge_contours, key=cv2.contourArea, reverse=True)[:5]
        cv2.drawContours(edge_mask, edge_contours, -1, 255, -1)
        kernel_large = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        edge_mask = cv2.morphologyEx(edge_mask, cv2.MORPH_CLOSE, kernel_large, iterations=3)

    # Method 2: Brightness threshold (Otsu)
    _, bright_mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, kernel, iterations=3)
    bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_OPEN, kernel, iterations=2)

    # Method 3: Adaptive threshold (local contrast)
    adaptive_mask = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, -10
    )
    adaptive_mask = cv2.morphologyEx(adaptive_mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Method 4: HSV saturation-based (cards usually have more saturated colors than background)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    _, sat_mask = cv2.threshold(hsv[:,:,1], 30, 255, cv2.THRESH_BINARY)
    sat_mask = cv2.morphologyEx(sat_mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Try each mask and score by best card-like contour
    best_mask = None
    best_score = 0
    best_name = None

    for mask_name, mask in [("edges", edge_mask), ("brightness", bright_mask), ("adaptive", adaptive_mask), ("saturation", sat_mask)]:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue

        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        for cnt in contours[:3]:
            area = cv2.contourArea(cnt)
            area_pct = area / img_area * 100

            # Skip if too small or too large (>95% = whole image)
            if area_pct < 5 or area_pct > 95:
                continue

            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)

            if len(approx) == 4:
                rect = cv2.minAreaRect(approx)
                w_rect, h_rect = rect[1]
                if w_rect > 0 and h_rect > 0:
                    aspect = max(w_rect, h_rect) / min(w_rect, h_rect)
                    if 1.0 <= aspect <= 2.0:
                        # Score: prefer larger area (but not whole image) and aspect closer to 1.4
                        area_score = min(area_pct / 80, 1.0)  # normalize to 0-1, cap at 80%
                        aspect_score = 1.0 - abs(aspect - 1.4) / 0.6  # ideal is 1.4
                        score = area_score * 0.7 + aspect_score * 0.3

                        if score > best_score:
                            best_score = score
                            best_mask = mask
                            best_name = mask_name
                            log.info(f"Best mask so far: {mask_name}, score={score:.3f}, area={area_pct:.1f}%, aspect={aspect:.2f}")
                            break

    if best_mask is not None:
        log.info(f"Selected mask method: {best_name}")
        return best_mask

    # Fallback to brightness if nothing worked
    log.warning("No good mask found, falling back to brightness threshold")
    return bright_mask


def _detect_inner_frame(rectified: np.ndarray) -> Optional[Polygon]:
    """
    Detect the inner printed image frame inside the card border.
    Returns a Polygon with 4 corners (tl, tr, br, bl) in rectified-image coords.
    Uses the assumption that the image frame is a well-defined rectangle
    inset from the card border.
    """
    gray = cv2.cvtColor(rectified, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape

    # Work on the central 80% of the card to avoid card border interference
    margin_x = int(w * 0.05)
    margin_y = int(h * 0.05)
    roi = gray[margin_y:h - margin_y, margin_x:w - margin_x]

    blurred = cv2.GaussianBlur(roi, (3, 3), 0)
    edges = cv2.Canny(blurred, 50, 150)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    roi_area = roi.shape[0] * roi.shape[1]
    best = None
    best_area = 0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < roi_area * 0.15 or area > roi_area * 0.9:
            continue
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        if len(approx) == 4 and area > best_area:
            best = approx.reshape(4, 2)
            best_area = area

    if best is None:
        # Fallback: use standard card proportions to estimate inner frame.
        # For centering measurement, we need the full printed area, not just artwork.
        # Standard card has roughly equal borders on all sides (~4-5mm).
        log.info("Inner frame contour not found — falling back to proportion-based estimate.")
        # Proportional bounds - equal borders on all sides for centering
        border_x = 0.075  # ~4.7mm side borders
        border_y = 0.095  # ~8.4mm top border
        # For bottom, use symmetric border (same as top approximately)
        l = int(w * border_x)
        r = int(w * (1.0 - border_x))
        t = int(h * border_y)
        b = int(h * (1.0 - border_y))  # Changed from 0.640 to 1.0-border_y for symmetry
        pts = np.array([[l, t], [r, t], [r, b], [l, b]], dtype=np.float32)
        ordered = _order_corners(pts)
        return Polygon(points=[(int(p[0]), int(p[1])) for p in ordered])

    # Translate back to full-image coordinates
    pts = best + np.array([margin_x, margin_y], dtype=np.float32)
    ordered = _order_corners(pts)
    return Polygon(points=[(int(p[0]), int(p[1])) for p in ordered])


def detect_card(card_image: CardImage, pixels_per_mm: Optional[float] = None) -> DetectedCard:
    """
    Detect the card outline, rectify perspective, detect inner image frame.

    Args:
        card_image: Input image (RGB).
        pixels_per_mm: If known from jig calibration. If None, estimated from
                       canonical card width and detected card width.

    Returns:
        DetectedCard with rectified RGB, pixels_per_mm, outer_corners, inner_frame.

    Raises:
        ValueError: If no card-like quadrilateral found.
    """
    rgb = card_image.rgb

    # PRIORITY 1: Try black background filtering first (most accurate for true edge)
    quad = _find_card_edge_from_black_background(rgb)
    blue_mask = None  # Initialize for later card presence check

    # PRIORITY 2: Try multi-method masking
    if quad is None:
        log.info("Black background detection failed, trying multi-method masking")
        blue_mask = _mask_blue_background(rgb)
        # Find contours on the mask
        contours, _ = cv2.findContours(blue_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if contours:
            # Try to find card quad from mask contours
            contours = sorted(contours, key=cv2.contourArea, reverse=True)
            img_area = blue_mask.shape[0] * blue_mask.shape[1]

            for cnt in contours[:5]:
                area = cv2.contourArea(cnt)
                if area < img_area * 0.05:  # relaxed threshold for mask
                    break

                peri = cv2.arcLength(cnt, True)

                # Try multiple epsilon values for polygon approximation
                for epsilon_factor in [0.02, 0.01, 0.005, 0.001]:
                    approx = cv2.approxPolyDP(cnt, epsilon_factor * peri, True)

                    if len(approx) == 4:
                        rect = cv2.minAreaRect(approx)
                        w, h = rect[1]
                        if w > 0 and h > 0:
                            aspect = max(w, h) / min(w, h)
                            if 1.0 <= aspect <= 2.0:  # relaxed from 1.2-1.6
                                log.info(f"Found card via mask: area={area:.0f} ({area/img_area*100:.1f}%), aspect={aspect:.2f}, epsilon={epsilon_factor}")
                                quad = approx.reshape(4, 2).astype(np.float32)
                                break

                if quad is not None:
                    break

                # If no 4-corner approx worked, try minAreaRect (oriented bounding box)
                if area >= img_area * 0.1:  # only for large contours
                    rect = cv2.minAreaRect(cnt)
                    w, h = rect[1]
                    if w > 0 and h > 0:
                        aspect = max(w, h) / min(w, h)
                        if 1.0 <= aspect <= 2.0:
                            log.info(f"Found card via minAreaRect: area={area:.0f} ({area/img_area*100:.1f}%), aspect={aspect:.2f}")
                            # Get the 4 corners of the rotated rect
                            box = cv2.boxPoints(rect)
                            quad = box.astype(np.float32)
                            log.info(f"minAreaRect corners (raw): {quad.tolist()}")
                            break

    # PRIORITY 3: Fallback to edge detection on grayscale
    if quad is None:
        log.info("Mask detection failed, trying edge detection")
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        quad = _find_card_contour(gray)

    if quad is None:
        raise ValueError("No card-like quadrilateral found in image.")

    log.info(f"Quad before ordering: {quad.tolist()}")
    ordered = _order_corners(quad)
    log.info(f"Quad after ordering: {ordered.tolist()}")

    # Black background detection finds the card+border boundary.
    # For corner grading: we extract from original image at quad vertices (perfect).
    # For edge/surface grading: rectified image should contain ONLY card, no black background.
    # Apply NEGATIVE expansion (shrink inward) to exclude black frame entirely.
    EXPANSION_PX = -10  # Shrink 10px inward to fully exclude black frame

    # Calculate the center and expand each corner away from it
    center = ordered.mean(axis=0)
    expanded = ordered.copy()

    for i in range(4):
        # Vector from center to corner
        direction = ordered[i] - center
        # Normalize and extend outward
        direction_norm = direction / (np.linalg.norm(direction) + 1e-6)
        # Move this corner outward by EXPANSION_PX
        expanded[i] = ordered[i] + direction_norm * EXPANSION_PX

    log.info(f"Quad after {EXPANSION_PX}px outward expansion: {expanded.tolist()}")

    # Destination corners for rectified output
    dst = np.array([
        [0, 0],
        [CANONICAL_WIDTH - 1, 0],
        [CANONICAL_WIDTH - 1, CANONICAL_HEIGHT - 1],
        [0, CANONICAL_HEIGHT - 1],
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(expanded, dst)
    rectified = cv2.warpPerspective(rgb, M, (CANONICAL_WIDTH, CANONICAL_HEIGHT))

    # Verify that the detected region actually contains a card
    quad_area = cv2.contourArea(quad)
    img_area = rgb.shape[0] * rgb.shape[1]
    contour_area_pct = quad_area / img_area * 100

    # If contour is >95% of image, it's likely the image boundary, not the card
    # But allow it if card presence checks pass (has features/edges)
    if contour_area_pct > 95:
        log.warning(f"Detected region is {contour_area_pct:.1f}% of image — likely image boundary. Checking card presence...")
        # Don't immediately reject - let card presence check decide

    # Create a dummy mask for card presence check if we used black background detection
    if blue_mask is None:
        blue_mask = np.ones((rgb.shape[0], rgb.shape[1]), dtype=np.uint8) * 255

    if not _check_card_present(rectified, blue_mask, contour_area_pct):
        if contour_area_pct > 95:
            raise ValueError("Card detection found image boundary instead of card edges. Ensure card has contrasting background and doesn't fill entire frame.")
        else:
            raise ValueError("Detected region does not appear to contain a card. Please place a card in the frame.")

    # Estimate pixels_per_mm from canonical width if not provided
    if pixels_per_mm is None:
        pixels_per_mm = CANONICAL_WIDTH / CARD_WIDTH_MM

    outer_corners: list[Point] = [(int(p[0]), int(p[1])) for p in ordered]

    inner_frame = _detect_inner_frame(rectified)
    if inner_frame is None:
        log.warning("Inner image frame not detected — centering will be approximate.")

    return DetectedCard(
        rgb=rectified,
        pixels_per_mm=pixels_per_mm,
        outer_corners=outer_corners,
        inner_frame=inner_frame,
        original_rgb=rgb,  # Pass through original image for corner extraction
        outer_corners_ordered=ordered,  # Pass through quad corners in original image coords
    )
