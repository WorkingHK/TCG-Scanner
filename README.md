# TCG Scanner — Card Grading PoC

AI-powered Pokémon card grading system using computer vision + Claude Vision API. Produces TAG Portal-style reports on a **PSA 1–10 scale** across four criteria: **Centering, Corners, Edges, Surface**.

**Version:** v0.1.4

> **Status:** Proof of Concept (investor demo target). Not production-ready. Goal is "demo-able, plausible, defensible in plain English" — not "matches PSA to the half-grade."

---

## Quick Start

**One-click setup:**
```bash
bash setup.sh
```

This will create the conda environment and install all dependencies automatically.

**Then run the app:**
```bash
conda activate tcg-grading
PYTHONPATH=. python desktop/main_window.py
```

In the app:
1. Click **⚙ Settings** → paste your Anthropic API key, choose your camera, fill card metadata
2. Click **📷 Live Preview** → position card under camera
3. Click **▶ GRADE** → ~10–15s later the TAG Portal HTML report opens in your browser

---

## What's New in v0.1.4

### PSA 1-10 Scale Refactor
- **Grading scale changed** from 1000-point to standard PSA 1-10 scale
- **CV-driven scoring** — Computer vision calculates base scores, VLM validates and adjusts
- More aligned with industry standard grading

### Camera Improvements
- **Low-FPS camera support** — grab/retrieve pattern with delays for 5fps cameras
- **Reliable resolution** — Request 5120×2880 (was 9999×9999, caused USB bandwidth issues)
- **Warm-up frames** — Proper auto-exposure/white-balance settling

### Enhanced Detection
- **50px margin** — Rectified images now 730×980 (630×880 + 50px margin) for reliable corner extraction
- **Centering fix** — Auto-detect and ignore black background artifacts from rectification
- **15px expansion** — Quadrilateral expansion increased for better edge capture

### Surface Scratch Detection
- **Smart filtering** — Background suppression eliminates false positives from holographic patterns
- **Count-based scoring** — Score based on actual scratch count (5-15 = near mint) not raw coverage
- **Characteristic filtering** — Linear scratches only, excludes artwork patterns

**See full changelog:** [`CHANGELOG.md`](CHANGELOG.md)

---

## What's New in v0.1.2

### Corner Radius Measurement
- **Measures actual corner radius** against Pokemon card 3mm standard
- **Quality scoring 0-10** based on deviation from ideal
- **Circle fitting algorithm** for accurate radius measurement
- Helps distinguish mint (perfect radius) vs worn (flattened) corners

### Improved Corner/Edge Capture
- **Captures outermost edge** — The actual corner touching the black frame, not inner area
- **60×60px corner crops** — Focused on corner radius curve only
- **70px edge strips** — Captures actual card border
- **10px quadrilateral expansion** — Ensures rectified image includes true physical edge

### Black Frame Support
- Detection now works with **black background** (switched from blue)
- Multi-method masking handles both colors

**See full changelog:** [`CHANGELOG.md`](CHANGELOG.md)  
**Technical details:** [`docs/corner-radius-measurement.md`](docs/corner-radius-measurement.md)

---

## Project Layout

```
TCG Scanner/
├── tcg_grading/              # Python engine (the brain)
│   ├── __init__.py
│   ├── types.py              # CardImage, DetectedCard, CriterionGrade, GradeReport
│   ├── rubric.py             # PSA centering thresholds + VLM rubric prompts
│   ├── capture.py            # UVCCamera (USB), RealCamera (gphoto2), MockCamera
│   ├── detect.py             # Card outline + perspective rectification + inner-frame
│   ├── centering.py          # Pure CV grader (PSA 2025 tolerance table)
│   ├── corners.py            # CV metrics + Claude Vision grading
│   ├── edges.py              # CV metrics + Claude Vision grading
│   ├── surface.py            # CV pre-detection + Claude Vision grading
│   ├── final_grade.py        # min + 0.5 if all others ≥ min+1 else min
│   ├── pipeline.py           # async orchestrator (grade_card)
│   └── report_html.py        # TAG Portal-style HTML report generator
│
├── desktop/                  # PySide6 desktop app
│   ├── __init__.py
│   └── main_window.py        # Main UI + Settings dialog + camera live preview
│
├── tests/                    # pytest suite (49 tests)
│   ├── test_centering.py
│   ├── test_corners.py
│   ├── test_edges.py
│   ├── test_final_grade.py
│   ├── test_pipeline.py
│   └── make_fixture.py       # Generate synthetic test card images
│
├── ref/                      # Design reference docs
│   ├── TAG Portal.pdf        # Reference grading report style we mimic
│   ├── tag_portal.html       # Static HTML mockup
│   ├── tag_report_live.html  # Generated report from a real grading run
│   ├── Grading Criteria.md   # Full PSA-style rubric
│   ├── cardcentering.md      # Centering math reference
│   └── PM.md                 # Project management notes
│
├── docs/superpowers/specs/   # Design specs
│   └── 2026-05-26-tcg-grading-design.md   # Approved design spec
│
├── captures/YYYY-MM-DD/HHMMSS/   # Auto-saved per-grade outputs
│   ├── raw_capture.jpg
│   ├── rectified.jpg
│   ├── corners_composite.jpg
│   ├── edges_annotated.jpg
│   ├── surface_annotated.jpg
│   ├── grade_report.json
│   └── grade_report.html
│
├── environment.yml           # Conda env definition (Python 3.11 + deps)
├── pyproject.toml            # Editable install metadata
├── .tcg_settings.json        # User settings (API key, card metadata) — gitignored
└── README.md                 # This file
```

---

## Setup

### One-Click Setup (Recommended)

```bash
bash setup.sh
```

The script will:
- Check for conda installation
- Create the `tcg-grading` environment from `environment.yml`
- Install all dependencies (Python 3.11, OpenCV, PySide6, Anthropic SDK, etc.)
- Display next steps

If the environment already exists, it will offer to update or recreate it.

### Manual Setup

```bash
conda env create -f environment.yml
conda activate tcg-grading
```

### Anthropic API Key

The system uses Claude Vision to grade corners, edges, and surface defects. You need an Anthropic API key (`sk-ant-...`).

**How to set it (any of these work):**

| Method | Where it goes |
|---|---|
| Settings dialog in app | `.tcg_settings.json` (project root) |
| `export ANTHROPIC_API_KEY=sk-ant-...` | Environment |
| Env var in shell launching the app | Inherited by subprocess |

The desktop app picks up the key from settings first, then env var as fallback.

---

## Running

### Desktop UI (recommended)

```bash
conda activate tcg-grading
PYTHONPATH=. python desktop/main_window.py
```

**Features:**
- ⚙ Settings dialog: API key, camera selector, card metadata, cert #
- 📂 Load Image: grade an existing JPG/PNG file
- 📷 Live Preview: stream from USB camera at ~10 fps
- ▶ GRADE: capture full-res still + run pipeline + auto-open HTML report
- 🌐 View Report: re-open the last generated TAG Portal HTML

### Programmatic / CLI

```python
import asyncio
from tcg_grading.pipeline import grade_card
from tcg_grading.report_html import generate_report

report = asyncio.run(grade_card(image_path="path/to/card.jpg"))
print(report.summary())

generate_report(
    report,
    card_name="Sylveon EX",
    card_set="Prismatic Evolutions #156/131",
    cert="C5314038",
    output_path="report.html",
)
```

### Tests

```bash
PYTHONPATH=. pytest tests/ -v
# 49 tests passing as of last run
```

---

## How It Works

### Pipeline (target ~15s end-to-end)

```
capture → detect_card → ┌─ grade_centering (CV, ~50ms)
                        │
                        ├─ grade_corners   (CV + VLM)  ┐
                        │                              │ asyncio.gather
                        ├─ grade_edges     (CV + VLM)  │ — parallel
                        │                              │
                        └─ grade_surface   (CV + VLM)  ┘
                                  │
                        compute_final_grade
                                  │
                          GradeReport → JSON + HTML report
```

### Grading Criteria

| Criterion | CV does | VLM does | Notes |
|---|---|---|---|
| **Centering** | Inner-frame detection, L/R + T/B margin ratios, PSA 2025 lookup | — | Pure CV. ~50ms. |
| **Corners** | Crop 4×400px ROIs, rounding deviation, defect pixel area | Sees 4 crops + metrics + rubric, returns JSON | One VLM call |
| **Edges** | Crop 4 edge strips, RMS deviation, chip count, deepest notch | Same pattern as corners | One VLM call |
| **Surface** | Top-hat morphology for scratches, Hough for print lines, annotate copy | Sees annotated full card + 2 high-res tile crops | One VLM call |
| **Final** | `min + 0.5 if all others ≥ min+1 else min`, capped at 10.0 | — | Pure rule |

### Score Conversion (TAG Portal style)

The pipeline grades on a 1.0–10.0 PSA-style scale internally; the HTML report converts to the **TAG Portal 0–1000 scale**:

| 1–10 grade | TAG score | Tier |
|---|---|---|
| 10.0 | 1000 | GEM MINT |
| 9.5 | 950 | MINT+ |
| 9.0 | 900 | MINT |
| 8.5 | 850 | NEAR MINT+ |
| 8.0 | 800 | NEAR MINT |
| 7.0 | 700 | EXCELLENT |
| <5.0 | <500 | POOR |

### Card Detection

`detect.py` runs Canny edge detection + contour filtering to find the card quad, then perspective-rectifies to a canonical **630×880 px** image (matching real Pokémon card 63×88 mm at 10 px/mm).

The inner image frame is detected with a second contour pass; if not found, a **proportion-based fallback** uses standard Pokémon card proportions (4.7% left/right border, 9.5% top, 64% bottom for the artwork window). This means centering always returns a grade — never errors.

---

## Configuration

### `.tcg_settings.json` (auto-saved by app)

```json
{
  "api_key": "sk-ant-...",
  "camera_index": 1,
  "card_name": "Sylveon EX",
  "card_set": "Prismatic Evolutions #156/131",
  "cert": "C5314038"
}
```

This file is **gitignored** and never sent anywhere except Anthropic's API.

### Camera Index

| Index | Typical mapping (macOS) |
|---|---|
| 0 | Built-in FaceTime HD Camera |
| 1 | First USB camera (your 48MP USB cam) |
| 2+ | Additional USB cameras |

The Settings dialog auto-detects available cameras via `cv2.VideoCapture` and lists them with their resolution.

### Model Selection

Defined per VLM module (`corners.py`, `edges.py`, `surface.py`):

| Setting | Current value | Notes |
|---|---|---|
| Model | `claude-sonnet-4-6` | Fast (2-3s/call). Was `claude-opus-4-7` initially — too slow for demo. |
| Max tokens | 512 | Down from 1024 — keeps responses concise |
| Prompt caching | `cache_control: ephemeral` on system prompt | ~80% input cost saving after warmup |
| Temperature | default (1.0) | Should be set to 0.0 for stability — see TODO |

---

## API Key & Endpoint Notes

⚠️ **Important:** If `anthropic.Anthropic()` shows `base_url: https://cc.zhihuiapi.top` (or any non-Anthropic endpoint), it's a **third-party proxy**. Some proxies strip image content from vision API requests, which makes the model return null/N/A for all corner crops. To use the real Anthropic API:

```bash
unset ANTHROPIC_BASE_URL
# or set it explicitly to the official endpoint
export ANTHROPIC_BASE_URL=https://api.anthropic.com
```

To check current endpoint:
```bash
PYTHONPATH=. python -c "import anthropic; print(anthropic.Anthropic().base_url)"
```

---

## TAG Portal HTML Report

Each grade auto-generates `grade_report.html` in `captures/<date>/<time>/` with:

- **Hero score** (0–1000 + tier label, e.g. "GEM MINT")
- **Population & rank strip** (placeholder until pop DB is wired up)
- **TAG Grading Summary** — Centering / Corners / Edges / Surface side-by-side
- **Centering Detail** — visual L/R + T/B bars
- **Defects of Notable Grade Significance** — VLM observations highlighted
- **Corner detail** (4-quadrant grid TL/TR/BL/BR)
- **Edge detail** (4-quadrant grid Top/Bottom/Left/Right)

Reference: `ref/TAG Portal.pdf` is the visual target. `ref/tag_portal.html` is a static mockup with hardcoded data; `ref/tag_report_live.html` is generated from a live pipeline run.

---

## Hardware

### Camera
- **Current**: 48MP UVC USB camera (Vendor 13028 / Product 18434)
- **Connection**: USB-C → Mac (or Pi 5 in production)
- **Driver**: OpenCV `cv2.VideoCapture` — no special driver needed
- **Future**: gphoto2-tethered DSLR via `RealCamera` class (for higher-end production)

### Demo Host
- **Dev**: macOS (any Mac)
- **Demo target**: Raspberry Pi 5 (8GB) + Ubuntu 24.04 LTS Desktop, external monitor via HDMI

### Lighting / Jig
- Bob delivers a fixed jig holding the card in known position under camera with controlled lighting (per design spec)
- Without jig: a flat plain background + diffuse light works for dev

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `ModuleNotFoundError: No module named 'tcg_grading'` | Run with `PYTHONPATH=.` from project root |
| `Inner frame not detected` (centering error) | Fixed — `detect.py` now falls back to proportion-based estimate |
| `KeyError: 'grade'` from corners/edges/surface | VLM returned malformed/empty JSON. Check API base URL (proxy stripping?) |
| Grading takes >30s | Switch model to `claude-sonnet-4-6` (already done). Check network. |
| `Surface VLM returned malformed JSON, retrying` | Markdown-fence stripping added — should be rare now |
| `Cannot open camera index N` | Camera in use by another app, or wrong index. Check Settings dialog. |
| App freezes during grading | Pipeline runs in `QThread` — should never freeze. Check stderr for stack trace. |
| `OpenCV: out device of bound` warnings | Harmless — OpenCV's camera enumeration probes more indexes than exist |

---

## Roadmap / TODO

**Done:**
- [x] Card outline detection + perspective rectification
- [x] Pure-CV centering grader (PSA 2025 tolerances)
- [x] CV + VLM grading for corners / edges / surface
- [x] Async parallel pipeline (`asyncio.gather`)
- [x] PySide6 desktop app with Settings dialog
- [x] UVC camera live preview + capture
- [x] TAG Portal-style HTML report (0–1000 scale)
- [x] Auto-save to `captures/<date>/<time>/`
- [x] 49 passing pytest tests
- [x] Inner-frame detection fallback (no more centering errors)

**Pending:**
- [ ] Real Anthropic API endpoint (currently using proxy that may strip images)
- [ ] Temperature 0.0 in VLM calls for stability
- [ ] Per-corner / per-edge real CV-driven sub-scores (currently derived proportionally)
- [ ] Population report data (currently placeholder)
- [ ] Back-of-card grading
- [ ] Card identification (which Pokémon, which set) — currently manual via Settings
- [ ] Pi 5 deployment script + systemd service
- [ ] Snapshot tests for VLM calls (VCR-style)

---

## Key Files to Know

| File | What it does |
|---|---|
| `tcg_grading/pipeline.py:grade_card()` | Single entrypoint for the whole pipeline |
| `tcg_grading/types.py:GradeReport` | Output shape — has `.summary()` and `capture_path` |
| `tcg_grading/rubric.py:CORNERS_RUBRIC` | Edit to change VLM grading prompts |
| `tcg_grading/detect.py:_detect_inner_frame()` | Inner artwork frame detection (with proportion fallback) |
| `tcg_grading/report_html.py:generate_report()` | Render TAG Portal HTML |
| `desktop/main_window.py:MainWindow` | All UI logic |
| `desktop/main_window.py:SettingsDialog` | API key + camera + card metadata config |

---

## Design Spec Reference

The complete approved design lives at `docs/superpowers/specs/2026-05-26-tcg-grading-design.md`. It defines:
- Three-layer architecture (engine / desktop / CC skills)
- Per-criterion methodology
- Error handling tiers (recoverable / per-criterion / fatal)
- Out-of-scope items (back grading, card ID, persistence DB, real-time video)
- Risks & mitigations (camera tethering, CV reliability, API cost overrun, Pi performance)

---

## License

Proprietary. Axonex internal — investor demo.
