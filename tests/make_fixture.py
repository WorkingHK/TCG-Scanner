#!/usr/bin/env python3
"""
Generate a synthetic test card image for use as a fixture.
Run once to create tests/fixtures/sample_card.jpg.

Usage (inside tcgscanner conda env):
    python tests/make_fixture.py
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def make_synthetic_card(
    img_w: int = 900,
    img_h: int = 1200,
    card_w: int = 630,
    card_h: int = 880,
    inner_margin_x: int = 55,
    inner_margin_y: int = 65,
) -> np.ndarray:
    """
    Create a synthetic card image:
    - Dark background
    - White card with slight off-white inner image frame
    - Sharp corners, clean edges (grade ~10 card)
    """
    img = np.full((img_h, img_w, 3), 30, dtype=np.uint8)  # dark grey bg

    # Center the card
    x0 = (img_w - card_w) // 2
    y0 = (img_h - card_h) // 2
    x1 = x0 + card_w
    y1 = y0 + card_h

    # Draw card body (cream white)
    img[y0:y1, x0:x1] = [245, 240, 230]

    # Draw inner image frame (slightly darker, simulates printed image area)
    fx0 = x0 + inner_margin_x
    fy0 = y0 + inner_margin_y
    fx1 = x1 - inner_margin_x
    fy1 = y1 - inner_margin_y
    img[fy0:fy1, fx0:fx1] = [120, 150, 180]  # blue-ish art area

    # Add some texture inside the art area
    art = img[fy0:fy1, fx0:fx1]
    noise = np.random.randint(0, 20, art.shape, dtype=np.uint8)
    img[fy0:fy1, fx0:fx1] = np.clip(art.astype(int) + noise - 10, 0, 255).astype(np.uint8)

    # Draw card border outline
    cv2.rectangle(img, (x0, y0), (x1 - 1, y1 - 1), (80, 80, 80), 2)

    # Draw inner frame outline
    cv2.rectangle(img, (fx0, fy0), (fx1 - 1, fy1 - 1), (60, 60, 60), 1)

    return img


def main():
    out_dir = Path(__file__).parent / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)

    img = make_synthetic_card()
    out = out_dir / "sample_card.jpg"
    cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"Saved {out}  ({img.shape[1]}x{img.shape[0]})")

    # Also save a "damaged" card for comparison testing
    damaged = make_synthetic_card()
    # Add edge damage
    rng = np.random.default_rng(42)
    for _ in range(30):
        x = int(rng.integers(0, damaged.shape[1]))
        y = int(rng.integers(0, damaged.shape[0]))
        cv2.circle(damaged, (x, y), int(rng.integers(2, 8)), (200, 200, 200), -1)
    out2 = out_dir / "damaged_card.jpg"
    cv2.imwrite(str(out2), damaged, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"Saved {out2}")


if __name__ == "__main__":
    main()
