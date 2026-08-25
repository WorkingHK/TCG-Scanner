"""
Erosion-based scratch/crack detection for trading cards.
Uses proper CV workflow: grayscale → threshold → erode → difference.
"""

import cv2
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt


def erosion_scratch_detection(image_path: str, kernel_size=(3, 3), kernel_shape='rect', threshold_method='otsu'):
    """
    Detect scratches and cracks using erosion on binary image.

    Workflow:
    1. Read image → grayscale
    2. Binarize with thresholding (Otsu)
    3. Apply erosion (shrinks boundaries)
    4. Difference = Original binary - Eroded = Thin features (scratches)

    Args:
        image_path: Path to input image
        kernel_size: (width, height) for structuring element
        kernel_shape: 'rect', 'ellipse', or 'cross'
        threshold_method: 'otsu', 'binary', or 'adaptive'

    Returns:
        dict with original, binary, eroded, and scratch_mask
    """
    # Step 1: Read and convert to grayscale
    original = cv2.imread(image_path)
    if original is None:
        raise FileNotFoundError(f"Could not load image: {image_path}")

    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    print(f"✓ Loaded image: {gray.shape[1]}x{gray.shape[0]} pixels")

    # Step 2: Binarization (threshold to black/white)
    if threshold_method == 'otsu':
        # Otsu's method automatically finds optimal threshold
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        print(f"✓ Applied Otsu's binarization")
    elif threshold_method == 'binary':
        # Fixed threshold at 127
        _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
        print(f"✓ Applied binary threshold (127)")
    elif threshold_method == 'adaptive':
        # Adaptive threshold (local neighborhoods)
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, 11, 2)
        print(f"✓ Applied adaptive threshold")
    else:
        raise ValueError(f"Unknown threshold method: {threshold_method}")

    # Step 3: Create structuring element (kernel)
    if kernel_shape == 'rect':
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
    elif kernel_shape == 'ellipse':
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, kernel_size)
    elif kernel_shape == 'cross':
        kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, kernel_size)
    else:
        raise ValueError(f"Unknown kernel shape: {kernel_shape}")

    print(f"✓ Created {kernel_shape} kernel ({kernel_size[0]}x{kernel_size[1]})")

    # Step 4: Apply erosion (shrinks white regions, removes thin features)
    eroded = cv2.erode(binary, kernel, iterations=1)
    print(f"✓ Applied erosion")

    # Step 5: Difference = Original - Eroded = Removed features (scratches/boundaries)
    scratch_mask = cv2.absdiff(binary, eroded)

    scratch_pixels = np.sum(scratch_mask > 0)
    total_pixels = scratch_mask.size
    scratch_coverage = (scratch_pixels / total_pixels) * 100

    print(f"✓ Detected scratches: {scratch_pixels:,} pixels ({scratch_coverage:.3f}%)")

    return {
        'original': original,
        'gray': gray,
        'binary': binary,
        'kernel': kernel,
        'eroded': eroded,
        'scratch_mask': scratch_mask,
        'scratch_coverage_pct': scratch_coverage,
        'scratch_pixels': scratch_pixels,
    }


def visualize_results(results, save_path=None):
    """
    Display original, binary, eroded, and scratch mask side-by-side.
    """
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))

    # Row 1: Original → Grayscale → Binary
    axes[0, 0].imshow(cv2.cvtColor(results['original'], cv2.COLOR_BGR2RGB))
    axes[0, 0].set_title('Original Image')
    axes[0, 0].axis('off')

    axes[0, 1].imshow(results['gray'], cmap='gray')
    axes[0, 1].set_title('Grayscale')
    axes[0, 1].axis('off')

    axes[0, 2].imshow(results['binary'], cmap='gray')
    axes[0, 2].set_title('Binary (Otsu Threshold)')
    axes[0, 2].axis('off')

    # Row 2: Eroded → Difference (Scratches) → Overlay
    axes[1, 0].imshow(results['eroded'], cmap='gray')
    axes[1, 0].set_title('Eroded (Boundaries Shrunk)')
    axes[1, 0].axis('off')

    axes[1, 1].imshow(results['scratch_mask'], cmap='hot')
    axes[1, 1].set_title(f'Scratches Detected\n({results["scratch_coverage_pct"]:.3f}% coverage)')
    axes[1, 1].axis('off')

    # Overlay scratches on original
    overlay = results['original'].copy()
    overlay[results['scratch_mask'] > 0] = [0, 0, 255]  # Red
    axes[1, 2].imshow(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB))
    axes[1, 2].set_title('Scratches Overlay (Red)')
    axes[1, 2].axis('off')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"✓ Saved visualization to: {save_path}")

    plt.show()


def compare_kernel_sizes(image_path: str):
    """
    Compare different kernel sizes to see their effect.
    """
    kernel_sizes = [(2, 2), (3, 3), (5, 5), (7, 7)]

    fig, axes = plt.subplots(2, 4, figsize=(16, 8))

    for idx, ksize in enumerate(kernel_sizes):
        results = erosion_scratch_detection(image_path, kernel_size=ksize, kernel_shape='rect')

        # Top row: Eroded
        axes[0, idx].imshow(results['eroded'], cmap='gray')
        axes[0, idx].set_title(f'Eroded {ksize[0]}x{ksize[1]}')
        axes[0, idx].axis('off')

        # Bottom row: Scratches
        axes[1, idx].imshow(results['scratch_mask'], cmap='hot')
        axes[1, idx].set_title(f'Scratches: {results["scratch_coverage_pct"]:.2f}%')
        axes[1, idx].axis('off')

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python erosion_detection.py <image_path>")
        print()
        print("Example:")
        print("  python erosion_detection.py captures/2026-06-11/145621/rectified.jpg")
        sys.exit(1)

    image_path = sys.argv[1]

    # Run detection
    print("=" * 60)
    print("Erosion-Based Scratch Detection")
    print("=" * 60)
    print()

    results = erosion_scratch_detection(
        image_path,
        kernel_size=(3, 3),
        kernel_shape='rect',
        threshold_method='otsu'
    )

    print()
    print("Results:")
    print(f"  Scratch pixels: {results['scratch_pixels']:,}")
    print(f"  Scratch coverage: {results['scratch_coverage_pct']:.3f}%")
    print()

    # Visualize
    visualize_results(results, save_path='erosion_detection_results.png')

    # Compare kernel sizes
    print()
    print("Comparing different kernel sizes...")
    compare_kernel_sizes(image_path)
