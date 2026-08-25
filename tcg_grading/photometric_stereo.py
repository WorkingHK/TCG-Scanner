"""Photometric Stereo for 3D surface normal reconstruction and defect detection."""

import numpy as np
import cv2
from pathlib import Path
from typing import List, Tuple, Optional
import logging

log = logging.getLogger(__name__)


def photometric_stereo(
    images: List[np.ndarray],
    light_directions: np.ndarray,
    albedo_threshold: float = 0.1
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute surface normals and albedo from multiple images under different lighting.

    Uses Lambertian reflectance model: I = albedo * (N · L)
    where I = observed intensity, N = surface normal, L = light direction

    Args:
        images: List of 4 grayscale images (H x W), same object, different lighting
        light_directions: 4x3 array of unit light direction vectors (x, y, z)
                         Example: [[0, 0, 1],    # Top (overhead)
                                   [0, 0, -1],   # Bottom
                                   [-1, 0, 0],   # Left
                                   [1, 0, 0]]    # Right
        albedo_threshold: Minimum albedo to consider (filter dark regions)

    Returns:
        normals: (H x W x 3) surface normal vectors (unit length)
        albedo: (H x W) surface reflectance (0-1)
        normal_map_rgb: (H x W x 3) RGB visualization of normals
    """
    if len(images) != 4:
        raise ValueError(f"Expected 4 images, got {len(images)}")

    if light_directions.shape != (4, 3):
        raise ValueError(f"Expected 4x3 light directions, got {light_directions.shape}")

    # Normalize light directions (ensure unit vectors)
    light_dirs_norm = light_directions / np.linalg.norm(light_directions, axis=1, keepdims=True)

    h, w = images[0].shape

    # Stack images into intensity matrix I (4 x N) where N = h*w
    I = np.array([img.flatten() for img in images], dtype=np.float32)  # (4, N)

    # Solve for surface properties: I = G * L^T
    # where G = albedo * N (scaled normals), L = light directions
    # G = I * L * (L^T * L)^-1

    L = light_dirs_norm  # (4, 3)
    LT_L_inv = np.linalg.inv(L.T @ L)  # (3, 3)
    G = I.T @ L @ LT_L_inv  # (N, 3) - scaled normals

    # Albedo is the magnitude of G
    albedo = np.linalg.norm(G, axis=1)  # (N,)
    albedo = albedo.reshape(h, w)

    # Normalize G to get unit normals
    # Avoid division by zero for dark regions
    albedo_mask = albedo > albedo_threshold
    normals = np.zeros((h, w, 3), dtype=np.float32)

    G_reshaped = G.reshape(h, w, 3)
    normals[albedo_mask] = G_reshaped[albedo_mask] / albedo[albedo_mask, np.newaxis]

    # For regions with low albedo, set normal to point upward (0, 0, 1)
    normals[~albedo_mask] = [0, 0, 1]

    # Create RGB normal map visualization
    # Map X, Y, Z components to R, G, B channels
    # X: -1 to 1 → R: 0 to 255 (left = red, right = cyan)
    # Y: -1 to 1 → G: 0 to 255 (up = green, down = magenta)
    # Z: 0 to 1 → B: 0 to 255 (toward camera = blue)
    normal_map_rgb = np.zeros((h, w, 3), dtype=np.uint8)
    normal_map_rgb[:, :, 0] = ((normals[:, :, 0] + 1) * 127.5).astype(np.uint8)  # R
    normal_map_rgb[:, :, 1] = ((normals[:, :, 1] + 1) * 127.5).astype(np.uint8)  # G
    normal_map_rgb[:, :, 2] = (normals[:, :, 2] * 255).astype(np.uint8)          # B

    log.info(f"Photometric stereo completed: albedo range [{albedo.min():.3f}, {albedo.max():.3f}]")

    return normals, albedo, normal_map_rgb


def render_heightmap(
    normals: np.ndarray,
    albedo: np.ndarray,
    scale: float = 1.0
) -> np.ndarray:
    """
    Render a grayscale height-map from surface normals.
    Highlights surface defects like scratches and dents.

    Args:
        normals: (H x W x 3) surface normal vectors
        albedo: (H x W) surface reflectance
        scale: Scale factor for height integration

    Returns:
        heightmap: (H x W) grayscale image (0-255) showing surface relief
    """
    h, w = normals.shape[:2]

    # Integrate normals to get depth
    # Use simple cumulative integration along x and y
    # dz/dx ≈ -Nx/Nz, dz/dy ≈ -Ny/Nz

    # Avoid division by zero
    nz = normals[:, :, 2].copy()
    nz[nz == 0] = 1e-6

    # Compute gradients
    p = -normals[:, :, 0] / nz  # dz/dx
    q = -normals[:, :, 1] / nz  # dz/dy

    # Integrate along x, then along y
    depth = np.zeros((h, w), dtype=np.float32)

    # Integrate each row along x
    for y in range(h):
        depth[y, :] = np.cumsum(p[y, :])

    # Integrate along y (add average of each column)
    for x in range(w):
        depth[:, x] += np.cumsum(q[:, x])

    # Normalize to 0-255
    depth = depth * scale
    depth = depth - depth.min()
    if depth.max() > 0:
        depth = depth / depth.max() * 255

    heightmap = depth.astype(np.uint8)

    # Apply bilateral filter to reduce noise while preserving edges (defects)
    heightmap = cv2.bilateralFilter(heightmap, 9, 75, 75)

    log.info(f"Heightmap rendered: range [{heightmap.min()}, {heightmap.max()}]")

    return heightmap


def detect_surface_defects_from_normals(
    normals: np.ndarray,
    heightmap: np.ndarray,
    scratch_threshold: float = 20.0,
    dent_threshold: float = 15.0
) -> dict:
    """
    Detect scratches and dents from normal map and heightmap.

    Args:
        normals: (H x W x 3) surface normal vectors
        heightmap: (H x W) rendered height map
        scratch_threshold: Gradient threshold for scratch detection
        dent_threshold: Depth threshold for dent detection

    Returns:
        dict with scratch_mask, dent_mask, defect_count, defect_area
    """
    h, w = normals.shape[:2]

    # Detect scratches from high-frequency changes in normals
    # Compute Laplacian of each normal component
    normal_variance = np.zeros((h, w), dtype=np.float32)
    for i in range(3):
        laplacian = cv2.Laplacian(normals[:, :, i], cv2.CV_32F)
        normal_variance += laplacian ** 2

    normal_variance = np.sqrt(normal_variance)

    # Threshold to get scratch candidates
    _, scratch_mask = cv2.threshold(
        normal_variance.astype(np.uint8),
        int(scratch_threshold),
        255,
        cv2.THRESH_BINARY
    )

    # Detect dents from heightmap (regions significantly below mean)
    height_blur = cv2.GaussianBlur(heightmap, (15, 15), 0)
    height_diff = height_blur.astype(np.float32) - heightmap.astype(np.float32)

    _, dent_mask = cv2.threshold(
        height_diff.astype(np.uint8),
        int(dent_threshold),
        255,
        cv2.THRESH_BINARY
    )

    # Count defects
    scratch_contours, _ = cv2.findContours(scratch_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    dent_contours, _ = cv2.findContours(dent_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    scratch_area = sum(cv2.contourArea(c) for c in scratch_contours)
    dent_area = sum(cv2.contourArea(c) for c in dent_contours)

    total_area = h * w

    return {
        "scratch_mask": scratch_mask,
        "dent_mask": dent_mask,
        "scratch_count": len(scratch_contours),
        "dent_count": len(dent_contours),
        "scratch_area_pct": scratch_area / total_area * 100,
        "dent_area_pct": dent_area / total_area * 100,
        "total_defect_area_pct": (scratch_area + dent_area) / total_area * 100,
    }


def process_card_photometric_stereo(
    image_paths: List[str],
    output_dir: Optional[Path] = None
) -> dict:
    """
    Complete photometric stereo pipeline for a card.

    Args:
        image_paths: List of 4 image paths [top_lit, bottom_lit, left_lit, right_lit]
        output_dir: Optional directory to save visualization outputs

    Returns:
        dict with normals, albedo, heightmap, defects, and metrics
    """
    if len(image_paths) != 4:
        raise ValueError("Exactly 4 images required (top, bottom, left, right lighting)")

    # Load images as grayscale
    images = []
    for path in image_paths:
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise FileNotFoundError(f"Could not load image: {path}")
        images.append(img)

    log.info(f"Loaded 4 images: {[img.shape for img in images]}")

    # Define light directions (assuming overhead camera, lights from 4 sides)
    # Coordinate system: X=right, Y=down, Z=toward camera
    light_directions = np.array([
        [0, -1, 1],   # Top light (from above card)
        [0, 1, 1],    # Bottom light (from below card)
        [-1, 0, 1],   # Left light
        [1, 0, 1],    # Right light
    ], dtype=np.float32)

    # Run photometric stereo
    normals, albedo, normal_map_rgb = photometric_stereo(images, light_directions)

    # Render heightmap
    heightmap = render_heightmap(normals, albedo, scale=2.0)

    # Detect defects
    defects = detect_surface_defects_from_normals(normals, heightmap)

    # Save visualizations if output_dir provided
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

        cv2.imwrite(str(output_dir / "normal_map.jpg"), normal_map_rgb)
        cv2.imwrite(str(output_dir / "heightmap.jpg"), heightmap)
        cv2.imwrite(str(output_dir / "albedo.jpg"), (albedo * 255).astype(np.uint8))

        # Create defect overlay
        defect_overlay = cv2.cvtColor(images[0], cv2.COLOR_GRAY2BGR)
        defect_overlay[defects["scratch_mask"] > 0] = [0, 0, 255]  # Red for scratches
        defect_overlay[defects["dent_mask"] > 0] = [255, 0, 0]     # Blue for dents
        cv2.imwrite(str(output_dir / "defects_overlay.jpg"), defect_overlay)

        log.info(f"Saved visualizations to {output_dir}")

    return {
        "normals": normals,
        "albedo": albedo,
        "normal_map_rgb": normal_map_rgb,
        "heightmap": heightmap,
        "defects": defects,
        "metrics": {
            "scratch_count": defects["scratch_count"],
            "dent_count": defects["dent_count"],
            "total_defect_area_pct": defects["total_defect_area_pct"],
        }
    }


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)

    # Test with 4 images of the same card under different lighting
    image_paths = [
        "card_top_light.jpg",
        "card_bottom_light.jpg",
        "card_left_light.jpg",
        "card_right_light.jpg",
    ]

    try:
        result = process_card_photometric_stereo(
            image_paths,
            output_dir=Path("photometric_output")
        )

        print(f"Photometric Stereo Results:")
        print(f"  Scratches detected: {result['metrics']['scratch_count']}")
        print(f"  Dents detected: {result['metrics']['dent_count']}")
        print(f"  Total defect area: {result['metrics']['total_defect_area_pct']:.2f}%")

    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Please provide 4 images captured under different lighting conditions.")
