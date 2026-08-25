#!/usr/bin/env python3
"""Generate synthetic test card fixtures. Run: python tests/fixtures/make_fixture.py"""
from pathlib import Path
import cv2
import numpy as np

def make_card(img_w=900, img_h=1200, damage=False):
    img = np.full((img_h, img_w, 3), 30, dtype=np.uint8)
    x0, y0 = (img_w - 630) // 2, (img_h - 880) // 2
    x1, y1 = x0 + 630, y0 + 880
    img[y0:y1, x0:x1] = [245, 240, 230]
    fx0, fy0, fx1, fy1 = x0+55, y0+65, x1-55, y1-65
    img[fy0:fy1, fx0:fx1] = [120, 150, 180]
    rng = np.random.default_rng(42)
    art = img[fy0:fy1, fx0:fx1].astype(int)
    art += rng.integers(-10, 20, art.shape)
    img[fy0:fy1, fx0:fx1] = np.clip(art, 0, 255).astype(np.uint8)
    cv2.rectangle(img, (x0, y0), (x1-1, y1-1), (80, 80, 80), 2)
    cv2.rectangle(img, (fx0, fy0), (fx1-1, fy1-1), (60, 60, 60), 1)
    if damage:
        for _ in range(40):
            x = int(rng.integers(0, img_w))
            y = int(rng.integers(0, img_h))
            cv2.circle(img, (x, y), int(rng.integers(2, 8)), (200, 200, 200), -1)
    return img

out = Path(__file__).parent
out.mkdir(parents=True, exist_ok=True)
cv2.imwrite(str(out / "sample_card.jpg"), make_card(), [cv2.IMWRITE_JPEG_QUALITY, 95])
cv2.imwrite(str(out / "damaged_card.jpg"), make_card(damage=True), [cv2.IMWRITE_JPEG_QUALITY, 95])
print(f"Saved sample_card.jpg and damaged_card.jpg to {out}")
