import cv2
import numpy as np
from pathlib import Path

# Load the most recent rectified image to analyze
rectified_path = Path('captures/2026-06-10/155919/rectified.jpg')
if rectified_path.exists():
    img = cv2.imread(str(rectified_path))
    h, w = img.shape[:2]

    print(f'Analyzing rectified image: {w}×{h}')
    print()

    # Sample different regions to understand the layout
    # Top-left corner region
    tl_region = img[0:40, 0:40]
    tl_avg = tl_region.mean(axis=(0,1))

    print('Top-left [0:40, 0:40] average color (BGR):')
    print(f'  B={int(tl_avg[0])} G={int(tl_avg[1])} R={int(tl_avg[2])}')

    if tl_avg[0] < 50:  # Low blue = black background
        print('  ❌ BLACK background present at [0,0]')
        print('  → Need to find where white border starts')

        # Scan from [0,0] to find first white pixel
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Scan along diagonal
        for offset in range(min(h, w)):
            if gray[offset, offset] > 150:  # Found white
                print(f'  → White border starts at approximately [{offset}, {offset}]')
                break
    else:
        print('  ✅ Card border starts at or near [0,0]')

    print()

    # Check where actual corner is by looking at edge transitions
    print('Analyzing corner positions:')

    # Top-left: look for L-shape (white edges meeting)
    # Bottom-left: check if it's different
    bl_region = img[h-40:h, 0:40]
    bl_avg = bl_region.mean(axis=(0,1))
    print(f'Bottom-left [h-40:h, 0:40] average: B={int(bl_avg[0])} G={int(bl_avg[1])} R={int(bl_avg[2])}')

    print()
    print('DIAGNOSIS:')
    print('If top has black but bottom doesn\'t, the rectified image is misaligned')
    print('If both have black, we need to offset all corner crops inward')
    print('If neither has black but top shows "both edges", the corner detection is finding inner edge')

else:
    print('No rectified.jpg found. Please run a grading first.')
