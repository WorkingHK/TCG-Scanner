# TCG Scanner Changelog

All notable changes to this project will be documented in this file.

---

## [v0.1.4] - 2026-08-26

### Added
- **Detection comparison test** — `test_improved_detection.py` comparing reference document approach vs current TCG Scanner detection
  - Tests Canny edge detection with multi-epsilon approximation
  - Tests adaptive threshold + morphology
  - Validates current black background detection superiority
  - Documentation: `test_results_analysis.md`

- **Platform compatibility documentation** — Identified install.sh limitations
  - macOS only (Apple Silicon and Intel supported)
  - Missing Linux/Raspberry Pi support
  - Missing aarch64 architecture detection
  - Documented in CLAUDE.md

- **Background frame analysis** — Evaluated black PLA vs alternatives
  - Black: professional but low contrast with dark cards
  - Green/Blue: recommended for universal contrast
  - Grey: neutral professional alternative

### Changed
- **Grading scale refactor** — Changed from 1000-point to **PSA 1-10 scale**
  - Centering: 1-10 based on PSA 2025 tolerances
  - Corners/Edges/Surface: CV base score 1-10, VLM adjusts ±50 points
  - Final grade: min(all) + 0.5 if all others ≥ min+1
  - More aligned with industry standard

- **Camera capture method** — Improved reliability for low-FPS cameras
  - Use grab/retrieve pattern instead of direct read()
  - Add 250ms delays between frames for 5fps cameras
  - Request 5120×2880 resolution (was 9999×9999)
  - File: `tcg_grading/capture.py`

- **Rectified image margin** — Increased to **50px** (was implicit/undocumented)
  - Output: 730×980 (630×880 canonical + 50px margin)
  - Critical for corner extraction from true edge
  - File: `tcg_grading/detect.py` (MARGIN=50)

- **Quadrilateral expansion** — Increased to **15px** (was 10px)
  - Better captures true physical edge
  - File: `tcg_grading/detect.py` (EXPANSION_PX=15)

- **Surface scratch detection** — Smart filtering algorithm (major improvement)
  - Background suppression: removes false positives from artwork/holo patterns
  - Count-based scoring: score by actual scratch count, not pixel coverage
  - Characteristic filtering: linear scratches only (aspect ratio ≥3:1)
  - Otsu thresholding: adaptive threshold calculation
  - File: `tcg_grading/surface.py`

- **Surface scoring algorithm** — Count-based instead of coverage-based
  - 0-5 scratches: 10-9 (Pristine)
  - 5-15 scratches: 9-8 (Near Mint)
  - 15-30 scratches: 8-7 (Excellent)
  - 30-60 scratches: 7-5 (Good)
  - 60+ scratches: 5-1 (Fair/Poor)

### Fixed
- **Centering black background artifacts** — Auto-detect and ignore rectification artifacts
  - Detects when card boundary is inset >5% from image edges
  - Falls back to full image as card boundary
  - File: `tcg_grading/centering.py`

- **Camera frame retrieval** — More robust for low-bandwidth USB cameras
  - Prevents "failed to grab" errors
  - Handles cameras that don't support read() directly

### Documentation
- Added Chinese OpenCV reference document (`Brainstorm/ref.md`)
- Added detection comparison analysis (`test_results_analysis.md`)
- Updated CLAUDE.md: v0.1.4, tcg-grading env name, camera details, platform support
- Updated README.md: v0.1.4 changes, PSA 1-10 scale

---

## [v0.1.3] - 2026-08-25

### Added
- **One-click installer** — `install.sh` for automated setup
  - Detects architecture (macOS arm64/x86_64)
  - Installs Miniforge if needed
  - Creates conda environment
  - Generates desktop launcher

### Changed
- **CV-driven grading** — CV metrics calculate base score, VLM validates
  - CV provides objective measurements
  - VLM adjusts ±50 points on 1000-point scale
  - More consistent and defensible scores

---

## [v0.1.2] - 2026-06-11

### Added
- **Corner radius measurement** — Measures actual corner radius against Pokemon card 3mm standard
  - Circle fitting algorithm using `cv2.minEnclosingCircle()`
  - Quality scoring 0-10 based on deviation from ideal
  - Output metrics: radius_mm, deviation_from_ideal_mm, radius_quality_score
  - File: `tcg_grading/corners.py:_measure_corner()`
  - Documentation: `docs/corner-radius-measurement.md`

- **Quadrilateral expansion** — 10px outward push of detected card boundary before perspective transform
  - Ensures rectified image includes true outermost edge
  - Captures the physical corner that touches the frame, not the inner white border edge
  - File: `tcg_grading/detect.py` (EXPANSION_PX = 10)

- **Black frame support** — Detection now handles both black and blue backgrounds
  - User switched from blue to black frame fixture on 2026-06-11
  - Multi-method masking works for both background colors

### Changed
- **Corner crop size** — Reduced from 120×120px to **60×60px**
  - Focuses on corner point with radius curve only
  - Prevents capturing entire border edges meeting in L-shape
  - Captures 2× the ideal 30px radius for context

- **Corner crop position** — Now captures from pixel **[0,0]** with **no inset**
  - Previous: 10px inset (captured inner area)
  - Current: 0px inset (captures outermost edge touching frame)
  - File: `tcg_grading/corners.py` (CORNER_CROP_PX=60, CORNER_INSET_PX=0)

- **Edge strip size** — Adjusted to **70px** height/width with **no inset**
  - Previous: 60px with 10px inset
  - Current: 70px with 0px inset (captures from pixel [0])
  - File: `tcg_grading/edges.py` (EDGE_STRIP_HEIGHT=70, EDGE_INSET_PX=0)

### Fixed
- **Corner capture accuracy** — Top corners now capture actual corner curves instead of straight side edges
  - Root cause: Rectified image didn't include outermost edge
  - Solution: 10px quadrilateral expansion before perspective transform
  - Iterative tuning: 5px → 15px → 30px → 20px → **10px** (final value based on testing)

- **Edge capture accuracy** — Edges now capture actual card border, not inner artwork area
  - Reduced strip size and removed inset to focus on border region

### Technical Details

**Corner & Edge Capture (2026-06-11):**
- Corner crops: 60×60px from [0:60, 0:60] and equivalent positions
- Edge strips: 70px height from [0:70, :, :] and equivalent positions  
- No inset on either — captures from absolute edge
- Quadrilateral expansion: 10px outward before perspective transform

**Measurement Standards:**
- Pokemon card: 63×88mm physical size
- Corner radius standard: 3mm
- Rectified scale: 10 px/mm (630×880px image)
- Ideal radius in pixels: 30px

**Quality Scoring:**
| Deviation | Score | Grade |
|-----------|-------|-------|
| ≤0.3mm | 10/10 | Excellent |
| ≤0.5mm | 9/10 | Good |
| ≤1.0mm | 7-8/10 | Acceptable |
| ≤2.0mm | 4-7/10 | Poor |
| >2.0mm | 1-4/10 | Bad |

---

## [v0.1.1] - 2026-06-10

### Added
- **Camera rotation toggle** — 90° clockwise rotation option in Settings UI
  - For cameras mounted sideways
  - Applied before card detection
  - Persisted to `.tcg_settings.json`

- **Improved card detection**
  - Multi-method masking: edges, brightness, adaptive threshold, saturation
  - Card presence validation: rejects empty frames (low color/edge variance)
  - minAreaRect fallback: handles irregular contours when 4-corner approx fails
  - Better handling of uniform backgrounds

### Changed
- **VLM model** — Switched from `claude-opus-4-7` to `claude-sonnet-4-6`
  - Lower cost for demo budget constraints
  - Sufficient quality for PoC grading

---

## [v0.1.0] - 2026-06-08

### Added
- **Initial release** — Full grading pipeline for Pokemon cards
- **Four-criterion grading:**
  - Centering (CV only) — PSA 2025 tolerance table
  - Corners (CV + VLM) — Sharpness, wear, radius quality
  - Edges (CV + VLM) — Straightness, whitening, damage
  - Surface (CV + VLM) — Scratches, holographic uniformity, print defects

- **Desktop app** (PySide6)
  - Live camera preview
  - Settings dialog: API key, camera selection, card metadata
  - Grading results display with TAG Portal-style scores
  - HTML report generation

- **Detection & rectification**
  - Perspective transform to 630×880px canonical size
  - Inner frame detection for centering measurement
  - Multi-method background masking

- **Report output**
  - TAG Portal-style HTML report
  - JSON grade data
  - Corner/edge/surface crop images
  - Saved to `captures/YYYY-MM-DD/HHMMSS/`

- **Testing framework**
  - Pytest suite with fixtures
  - Mock camera for reproducible tests
  - Sample card images in `ref/`

- **Documentation**
  - Design spec: `docs/superpowers/specs/2026-05-26-tcg-grading-design.md`
  - README with quick start, architecture, troubleshooting
  - CLAUDE.md with agent reference and hard rules

### Technical Stack
- Python 3.11 (conda env: `tcgscanner`)
- PySide6 (Qt for desktop UI)
- OpenCV (computer vision)
- Anthropic Claude API (VLM grading)
- NumPy, Pillow (image processing)

---

## Future Roadmap

### Potential v0.1.3+ Features
- **Surface defect annotation** — Match TAG's visual marking technique (pending analysis)
- **Back-of-card grading** — Extend to both sides
- **Card identification** — OCR for card name/set
- **Batch processing** — Grade multiple cards in sequence
- **Grade history** — Track same card over time
- **Export formats** — PDF, CSV reports

### Known Limitations (PoC Scope)
- Front-only grading (back not implemented)
- No card identification/OCR
- No persistent database
- No real-time video feed
- Single-card manual workflow
- No authentication/user accounts

---

## Version Numbering

Format: `MAJOR.MINOR.PATCH`

- **MAJOR** — Breaking changes, architecture overhaul
- **MINOR** — New features, significant improvements
- **PATCH** — Bug fixes, small tweaks

Current status: PoC phase, minor versions track feature additions before investor demo.
