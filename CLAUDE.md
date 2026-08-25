# TCG Scanner — Agent Reference

**Project:** TCG Scanner PoC — AI-powered Pokemon card grading  
**Version:** v0.1.3  
**Status:** Proof of Concept for investor demo

---

## Quick Context

This is a **conda-managed Python project** with a PySide6 desktop app. Hybrid CV+VLM pipeline grades Pokemon cards on 4 criteria (Centering, Corners, Edges, Surface) and outputs TAG Portal-style HTML reports.

**Always activate the conda env before any Python operation:**
```bash
conda activate tcgscanner
```

---

## Environment Requirements

- **Python:** 3.11 via conda (not system Python)
- **Conda env name:** `tcgscanner`
- **Dependencies:** Defined in `environment.yml` (never use pip outside the env)
- **Setup on new machine:**
  ```bash
  conda env create -f environment.yml
  conda activate tcgscanner
  ```

**Why conda:** User explicitly requested conda for this project (differs from other projects like OrangePi deployment which run without venvs).

---

## Project Structure

```
tcg_grading/          # Core grading engine (CV + VLM pipeline)
├── pipeline.py       # Main entry: grade_card()
├── detect.py         # Card detection & rectification
├── centering.py      # Pure CV centering grade
├── corners.py        # CV metrics + VLM grade
├── edges.py          # CV metrics + VLM grade
├── surface.py        # CV metrics + VLM grade
├── final_grade.py    # Overall grade computation
├── capture.py        # Camera classes (UVCCamera, MockCamera)
├── report_html.py    # TAG Portal HTML generation
└── rubric.py         # VLM grading prompts

desktop/              # PySide6 GUI
├── main_window.py    # MainWindow + SettingsDialog + GradeWorker

tests/                # Pytest suite
├── test_*.py         # Unit tests per module
└── fixtures/         # Sample card images

docs/
├── skills/           # CC skill documentation
└── superpowers/specs/# Design spec (2026-05-26)

.tcg_settings.json    # User settings (API key, camera, metadata) - gitignored
```

---

## Common Operations

### Run Desktop App
```bash
conda activate tcgscanner
PYTHONPATH=. python desktop/main_window.py
```

### Run Tests
```bash
conda activate tcgscanner
pytest                           # All tests
pytest tests/test_detect.py      # Single module
pytest -v -s                     # Verbose with print output
```

### Grade a Card (Engine Only)
```python
import asyncio
from tcg_grading.pipeline import grade_card

# From file
report = asyncio.run(grade_card(image_path='path/to/card.jpg'))

# From camera
report = asyncio.run(grade_card(use_camera=True, camera_index=1))

# From test fixtures
report = asyncio.run(grade_card(fixtures_dir='tests/fixtures'))

print(report.summary())
```

### Check Camera Index
```bash
conda activate tcgscanner
python -c "
from tcg_grading.capture import UVCCamera
UVCCamera.list_devices()
"
```

---

## Key Files & Constants

| File | Key Constants/Functions |
|------|-------------------------|
| `tcg_grading/detect.py` | `CANONICAL_WIDTH=630`, `CANONICAL_HEIGHT=880`, `EXPANSION_PX=10`, `detect_card()` |
| `tcg_grading/corners.py` | `CORNER_CROP_PX=60`, `CORNER_INSET_PX=0`, `_measure_corner()` (3mm radius measurement) |
| `tcg_grading/edges.py` | `EDGE_STRIP_HEIGHT=70`, `EDGE_INSET_PX=0`, `grade_edges()` |
| `tcg_grading/centering.py` | `PSA_2025_TOLERANCES` (centering thresholds), `grade_centering()` |
| `tcg_grading/rubric.py` | `CORNERS_RUBRIC`, `EDGES_RUBRIC`, `SURFACE_RUBRIC` (VLM prompts) |
| `tcg_grading/final_grade.py` | `compute_final_grade()` (min + 0.5 if all ≥ min+1) |
| `tcg_grading/capture.py` | `UVCCamera` (48MP USB camera), `MockCamera` (test fixtures) |
| `desktop/main_window.py` | `SettingsDialog` (API key, camera_index, rotate_90_cw) |

---

## Settings & Configuration

**User settings** persist in `.tcg_settings.json` (gitignored):
- `api_key`: Anthropic API key
- `camera_index`: 0=built-in, 1=first USB camera
- `rotate_90_cw`: `true` if camera is mounted sideways
- `card_name`, `card_set`, `card_number`: Metadata for reports

**Environment variables** (fallback if not in settings):
- `ANTHROPIC_API_KEY`: API key for Claude Vision

---

## Camera Setup

- **Hardware:** 48MP USB/UVC camera
- **Driver:** OpenCV VideoCapture (no gphoto2)
- **Rotation:** v0.1.1 added 90° clockwise rotation toggle (Settings UI) for sideways-mounted cameras
- **Index:** Built-in=0, first USB=1, second USB=2 (check with `UVCCamera.list_devices()`)

---

## Detection & Grading Pipeline

1. **Capture/Load:** Image from camera, file, or fixtures
2. **Detect & Rectify:** `detect_card()` → perspective transform to 630×880px canonical size
   - Multi-method masking: edges, brightness, adaptive threshold, saturation
   - **Quadrilateral expansion (10px):** Pushes detected boundary outward to capture true physical edge
   - Card presence validation: rejects empty frames (low edge variance)
   - minAreaRect fallback for irregular contours
   - Inner frame detection (artwork border) with proportion-based fallback
3. **Centering (CV only):** Measure inner frame offset vs PSA 2025 tolerances → grade 0–10
4. **Parallel grading (CV+VLM):**
   - **Corners:** Extract 4 corner crops (60×60px from [0,0]) → CV radius measurement (3mm standard) + edge metrics → VLM grades with rubric
   - **Edges:** Extract 4 edge strips (70px from [0]) → CV metrics (straightness, wear) → VLM grades
   - **Surface:** Full card crop → CV metrics (scratch detection, holographic uniformity) → VLM grades
5. **Final Grade:** `min(all 4) + 0.5` if all others ≥ min+1, else `min(all 4)`
6. **Report:** Save crops + JSON + HTML to `captures/YYYY-MM-DD/HHMMSS/`

---

## Corner & Edge Capture Details (Updated 2026-06-11)

**Corner Crops:**
- Size: 60×60px (captures ~2× the ideal 3mm/30px radius)
- Position: From pixel [0,0] - no inset, captures outermost edge
- Goal: Capture the true physical corner that touches the black frame

**Edge Crops:**
- Size: 70px height/width strips  
- Position: From pixel [0] - no inset, captures outermost edge
- Goal: Capture the actual card border edge

**Quadrilateral Expansion (`tcg_grading/detect.py`):**
- Expansion: 10px outward from detected card boundary
- Why: Card detection often stops at inner edge of white border; expansion ensures rectified image includes the true physical corner
- Applied before perspective transform in `detect_card()`

**Background Frame:**
- **Black frame** (switched from blue 2026-06-11)
- Detection handles both black and blue backgrounds via multi-method masking

**Corner Radius Measurement (`tcg_grading/corners.py:_measure_corner()`):**
- Standard: Pokemon cards have 3mm corner radius (30px at 10px/mm scale)
- Method: Circle fitting using `cv2.minEnclosingCircle()` on corner contour points
- Quality scoring: 0-10 based on deviation from 3mm ideal
  - ≤0.3mm: 10/10 (Excellent)
  - ≤0.5mm: 9/10 (Good)
  - ≤1.0mm: 7-8/10 (Acceptable)
  - ≤2.0mm: 4-7/10 (Poor)
  - >2.0mm: 1-4/10 (Bad)

---

## Troubleshooting

### "No card-like quadrilateral found"
- **Cause:** Poor lighting, card edges blend with background, or card fills >95% of frame
- **Fix:** Improve background contrast (use blue rack), ensure visible background around all 4 edges, adjust camera distance

### "Detected region does not appear to contain a card"
- **Cause:** Empty frame or uniform background detected instead of card
- **Check:** Card presence validation looks for color variation (H/S/V std) and edge variance (Laplacian)
- **Threshold:** Edge variance < 50 = rejected

### Camera not found / wrong camera
- **Check index:** `UVCCamera.list_devices()`
- **Settings:** Adjust `camera_index` in Settings UI
- **macOS privacy:** System Settings → Privacy & Security → Camera → allow Terminal/app

### Conda env not activating
- **Check conda:** `which conda` (should be miniforge3)
- **Recreate env:** `conda env remove -n tcgscanner && conda env create -f environment.yml`

### API key errors
- **Check key:** Settings UI → paste Anthropic API key
- **Or env var:** `export ANTHROPIC_API_KEY=sk-ant-...`

---

## Hard Rules

1. **Always use conda env** — Never run Python commands without `conda activate tcgscanner`
2. **Never pip install outside env** — Add deps to `environment.yml` then `conda env update -f environment.yml`
3. **PYTHONPATH=. for desktop app** — Required for imports to work
4. **API key required** — Either in Settings UI or `ANTHROPIC_API_KEY` env var
5. **Card presence validation** — Empty frames are rejected (don't try to grade blue racks!)

---

## Demo Target

- **Host:** Raspberry Pi 5 (8 GB) running Ubuntu 24.04 LTS
- **Display:** External monitor via HDMI
- **Network:** Venue Wi-Fi/Ethernet for live Anthropic API calls
- **Goal:** "Demo-able, plausible, defensible in plain English" — not PSA-grade accuracy

---

## Out of Scope (PoC)

- Back of card grading
- Card identification / OCR
- Persistent database
- Real-time video feed
- Multi-card batch processing
- Authentication / user accounts

---

## Version History

- **v0.1.0** (2026-06-08): Initial release — full grading pipeline
- **v0.1.1** (2026-06-10): Camera rotation toggle, improved detection (multi-method masking, card presence validation, minAreaRect fallback)
- **v0.1.2** (2026-06-11): Corner radius measurement (3mm standard), corner/edge capture from outermost edge (60×60px corners, 70px edges, no inset), 10px quad expansion for true physical corner capture, black frame support
- **v0.1.3** (2026-06-11): CV-driven grading with VLM validation — CV metrics calculate base score (0-1000 scale), VLM adjusts ±50 points for consistency and accuracy

---

## Design Spec

Full approved design: `docs/superpowers/specs/2026-05-26-tcg-grading-design.md`

Defines:
- Three-layer architecture (engine / desktop / CC skills)
- Per-criterion methodology (CV metrics → VLM grading → score)
- Error handling tiers (recoverable / per-criterion / fatal)
- Risks & mitigations (camera tethering, CV reliability, API cost, Pi performance)
