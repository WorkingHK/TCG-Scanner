# TCG Scanner Changelog

All notable changes to this project will be documented in this file.

---

## [v0.1.2] - 2026-06-11 (In Progress)

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
