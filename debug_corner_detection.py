"""
Debug script to visualize corner detection.
Run this after grading to see what's being captured.
"""
import cv2
import numpy as np
from pathlib import Path
import sys

# Find the most recent capture
captures_dir = Path('captures')
if not captures_dir.exists():
    print('No captures directory found')
    sys.exit(1)

# Get most recent date directory
date_dirs = sorted(captures_dir.glob('????-??-??'))
if not date_dirs:
    print('No captures found')
    sys.exit(1)

latest_date = date_dirs[-1]
time_dirs = sorted(latest_date.glob('*'))
if not time_dirs:
    print(f'No captures in {latest_date}')
    sys.exit(1)

latest_capture = time_dirs[-1]
print(f'Analyzing: {latest_capture}')
print()

# Load rectified image
rectified_path = latest_capture / 'rectified.jpg'
if not rectified_path.exists():
    print('No rectified.jpg found')
    sys.exit(1)

img = cv2.imread(str(rectified_path))
h, w = img.shape[:2]

# Draw corner crop regions on the image
overlay = img.copy()
CORNER_SIZE = 60  # Current setting

regions = {
    'TL': ([0, 60], [0, 60], (0, 255, 0)),      # Green for top-left
    'TR': ([0, 60], [w-60, w], (0, 255, 255)),  # Yellow for top-right
    'BL': ([h-60, h], [0, 60], (255, 0, 0)),    # Blue for bottom-left
    'BR': ([h-60, h], [w-60, w], (255, 0, 255)) # Magenta for bottom-right
}

for name, (rows, cols, color) in regions.items():
    cv2.rectangle(overlay, (cols[0], rows[0]), (cols[1], rows[1]), color, 3)
    cv2.putText(overlay, name, (cols[0]+5, rows[0]+20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

# Save visualization
output_path = latest_capture / 'corner_regions_debug.jpg'
cv2.imwrite(str(output_path), overlay)
print(f'✅ Saved visualization to: {output_path}')
print()

# Load and analyze actual corner crops
print('Corner crop analysis:')
for i, name in enumerate(['TOP_LEFT', 'TOP_RIGHT', 'BOTTOM_LEFT', 'BOTTOM_RIGHT']):
    corner_path = latest_capture / f'corner_{i}.jpg'
    if corner_path.exists():
        corner = cv2.imread(str(corner_path))
        h_c, w_c = corner.shape[:2]

        # Check [0:10, 0:10] for actual corner presence
        sample = corner[0:10, 0:10]
        avg_color = sample.mean(axis=(0,1))

        # Check for edge detection
        gray = cv2.cvtColor(corner, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)

        # Count edges in different regions to detect straight vs curved
        top_edges = np.sum(edges[0:10, :] > 0)
        left_edges = np.sum(edges[:, 0:10] > 0)
        corner_edges = np.sum(edges[0:20, 0:20] > 0)

        print(f'  corner_{i} ({name}): size={w_c}×{h_c}')
        print(f'    [0,0] color: B={int(avg_color[0])} G={int(avg_color[1])} R={int(avg_color[2])}')
        print(f'    edges: top={top_edges}, left={left_edges}, corner_region={corner_edges}')

        if top_edges > 50 and left_edges < 20:
            print(f'    ⚠️  Detecting horizontal edge (top/bottom edge, not corner)')
        elif left_edges > 50 and top_edges < 20:
            print(f'    ⚠️  Detecting vertical edge (left/right edge, not corner)')
        elif corner_edges > 100:
            print(f'    ✅ Detecting corner curve')
        else:
            print(f'    ❓ Unclear pattern')
        print()

print('Open corner_regions_debug.jpg to see which areas are being captured')
