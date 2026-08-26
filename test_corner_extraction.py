#!/usr/bin/env python3
"""Test corner extraction from original image with debug logging."""

import asyncio
import logging
import sys
from pathlib import Path

# Enable debug logging for corners module
logging.basicConfig(
    level=logging.DEBUG,
    format='%(name)s [%(levelname)s] %(message)s',
    stream=sys.stdout
)

from tcg_grading.pipeline import grade_card

async def main():
    print("=" * 80)
    print("Testing corner extraction from ORIGINAL image (no rectification distortion)")
    print("=" * 80)
    print()

    # Use latest capture instead of camera (for non-interactive testing)
    use_camera = False
    camera_index = None

    print("Using latest capture from disk...")

    try:
        report = await grade_card(
            use_camera=use_camera,
            camera_index=camera_index if use_camera else None,
            image_path=None if use_camera else "captures/2026-08-26/105313/raw_capture.jpg"
        )

        print("\n" + "=" * 80)
        print("RESULTS:")
        print("=" * 80)
        print(report.summary())

        if report.corners and report.corners.evidence:
            print("\nCorner CV metrics:")
            metrics = report.corners.evidence.get("cv_metrics", {})
            for corner_name, m in metrics.items():
                if m:
                    print(f"  {corner_name}:")
                    print(f"    radius: {m.get('radius_mm', 'N/A')}mm (ideal: 3.0mm)")
                    print(f"    deviation: {m.get('deviation_from_ideal_mm', 'N/A')}mm")
                    print(f"    quality: {m.get('radius_quality_score', 'N/A')}/10")
                else:
                    print(f"  {corner_name}: FAILED (no metrics)")

        if report.capture_path:
            print(f"\nResults saved to: {report.capture_path}")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
