"""Grading scale tables and VLM rubric text for all criteria."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Centering — PSA tolerance table (front only, as of 2025)
# Format: grade -> max allowed ratio (larger/smaller, so 55/45 -> 55.0/45.0 -> 1.222)
# We store the "worse side percentage" threshold, e.g. grade 10 requires <= 55% on worse side
# ---------------------------------------------------------------------------

# Maps minimum grade -> maximum worse-side border percentage (out of 100)
# Grades are on 1-10 scale (PSA style)
CENTERING_GRADE_THRESHOLDS: list[tuple[float, float]] = [
    # (grade, max_worse_side_pct)  — sorted best to worst
    (10.0, 55.0),   # 55/45
    (9.0,  60.0),   # 60/40
    (8.5,  62.5),   # 62.5/37.5
    (8.0,  65.0),   # 65/35
    (7.5,  67.5),   # 67.5/32.5
    (7.0,  70.0),   # 70/30
    (6.5,  72.5),
    (6.0,  75.0),
    (5.5,  77.5),
    (5.0,  80.0),
    (4.5,  82.5),
    (4.0,  85.0),
    (3.5,  87.5),
    (3.0,  90.0),
    (2.5,  92.5),
    (2.0,  95.0),
    (1.5,  98.33),
    (1.0,  100.0),  # anything goes (miscut range)
]


def centering_ratio_to_grade(left: float, right: float, top: float, bottom: float) -> float:
    """
    Given border measurements in pixels (or mm), return a centering grade.
    Uses the worst axis (L/R or T/B) and maps to PSA 2025 tolerances.
    """
    def worse_pct(a: float, b: float) -> float:
        total = a + b
        if total == 0:
            return 50.0
        return max(a, b) / total * 100.0

    lr_pct = worse_pct(left, right)
    tb_pct = worse_pct(top, bottom)
    worst = max(lr_pct, tb_pct)

    for grade, threshold in CENTERING_GRADE_THRESHOLDS:
        if worst <= threshold:
            return grade
    return 1.0


# ---------------------------------------------------------------------------
# VLM rubric text — used as system prompts (prompt-cached across cards)
# ---------------------------------------------------------------------------

CORNERS_RUBRIC = """
You are an expert TCG (Trading Card Game) card grader specializing in corner assessment.
Grade the card corners using the following PSA-style rubric:

GRADE 10 (Gem Mint): Corners appear perfectly sharp and square. No visible wear, fraying, or
marks under close inspection. Corner stock is pristine.

GRADE 9 (Mint): Corners still appear sharp. Very slight fraying or a tiny touch may be visible
under magnification, but corners appear perfect to the naked eye.

GRADE 8.5: Corners sharp but one or two show a very minor touch or slight fraying visible to
naked eye. No rounding.

GRADE 8: All corners still appear square. Minor wear on one or two corners — light touches,
tiny fraying. Very minor areas of fill may start to show under high resolution.

GRADE 7.5: Corners show a little more wear; starting to lose their sharpness. All four corners
may have light touches where stock was compromised. Slight fraying on corner surface.

GRADE 7: Corners still appear square but multiple corners display fraying on corner surfaces.
Slight bend or hit that compromises card surface might be present. Larger fray artifacts visible.

GRADE 6.5: A corner may start losing its shape due to more excessive corner surface wear, a bend
or dinged corner, or a larger area of fill. Three or four corners showing significant fraying.

GRADE 6: One corner may show slight rounding. Fraying more prevalent on multiple corners.
Multiple corners show more significant wear on front and back. A slight bend or ding clearly present.

GRADE 5.5: Very minor corner rounding on one or two corners. A more severe bend or slight
wrinkle may be present on a corner's surface.

GRADE 5: Rounding of a corner or two becomes slightly more significant. Larger areas of corner
surface wear or chipping visible. All four corners lost squareness due to surface wear or fill issues.

GRADE 4.5: A corner clearly rounded, accompanied by an area of corner surface wear, fraying or
chipping. Multiple corners with bends or dings impacting corner surface.

GRADE 4: Two or three corners clearly rounded, accompanied by areas of corner surface wear,
fraying or chipping. Bends, dings and surface wear more prevalent.

GRADE 3.5 and below: All four corners rounded. Increasing severity of rounding, fraying,
dirtiness, and structural compromise.

GRADE 1–2: Corners misshaped, extreme rounding, parts may have fallen off or been torn off.

You will be given:
- Four corner crop images (top-left, top-right, bottom-left, bottom-right)
- CV measurement data (rounding deviation, defect pixel area per corner)

Respond ONLY in valid JSON with this exact schema:
{
  "per_corner": {
    "top_left": {"observation": "...", "severity": "none|minor|moderate|severe"},
    "top_right": {"observation": "...", "severity": "none|minor|moderate|severe"},
    "bottom_left": {"observation": "...", "severity": "none|minor|moderate|severe"},
    "bottom_right": {"observation": "...", "severity": "none|minor|moderate|severe"}
  },
  "worst_corner": "top_left|top_right|bottom_left|bottom_right",
  "worst_corner_observation": "...",
  "grade": <number 100-1000>,
  "confidence": "high|medium|low",
  "reasoning": "..."
}
""".strip()


EDGES_RUBRIC = """
You are an expert TCG (Trading Card Game) card grader specializing in edge assessment.
Grade the card edges using the following PSA-style rubric:

GRADE 10 (Gem Mint): Edges perfectly smooth and clean. No nicks, chips, fraying, or
roughness visible anywhere.

GRADE 9 (Mint): Edges appear smooth to naked eye. Very slight roughness may be detectable
under magnification only.

GRADE 8.5: Edges almost perfect. A very minor nick or slight roughness on one edge
visible under close inspection.

GRADE 8: Edges mostly smooth. Minor wear — very light roughness, a tiny nick or chip
on one edge. Clean overall appearance.

GRADE 7.5: One or two edges show minor chipping or light wear that's slightly more
noticeable. No large chips or fraying.

GRADE 7: Light chipping beginning to appear on multiple edges. Some slight roughness.
Still a generally clean appearance.

GRADE 6.5: Moderate chipping or fraying on one or more edges. More significant roughness
that is clearly visible.

GRADE 6: Noticeable chipping or fraying on multiple edges. Moderate wear that impacts
the card's appearance.

GRADE 5–5.5: Heavy chipping or fraying visible on multiple edges. Significant wear that
is clearly distracting.

GRADE 4 and below: Severe edge damage — deep chips, tears, heavy fraying, or significant
structural compromise.

You will be given:
- Four edge strip images (top, bottom, left, right)
- CV measurement data (RMS deviation from straight line, chip count, deepest notch depth per edge)

Respond ONLY in valid JSON with this exact schema:
{
  "per_edge": {
    "top": {"observation": "...", "severity": "none|minor|moderate|severe"},
    "bottom": {"observation": "...", "severity": "none|minor|moderate|severe"},
    "left": {"observation": "...", "severity": "none|minor|moderate|severe"},
    "right": {"observation": "...", "severity": "none|minor|moderate|severe"}
  },
  "worst_edge": "top|bottom|left|right",
  "worst_edge_observation": "...",
  "grade": <number 100-1000>,
  "confidence": "high|medium|low",
  "reasoning": "..."
}
""".strip()


SURFACE_RUBRIC = """
You are an expert TCG (Trading Card Game) card grader specializing in surface assessment.
Grade the card surface using the following PSA-style rubric:

GRADE 10 (Gem Mint): Card surface is flawless. No scratches, print lines, stains, creases,
dents, or any surface defect visible under any lighting condition.

GRADE 9 (Mint): Surface appears flawless to naked eye. Under magnification, one or two
extremely faint print lines or very minor imperfections may be detectable.

GRADE 8.5: Very minor surface defect — a faint scratch, light print line, or tiny stain
that requires close inspection to notice.

GRADE 8: One or two minor surface defects — slight scratches, light print lines, or a
small stain. Visible under close inspection but not immediately obvious.

GRADE 7.5: A few minor surface defects that are somewhat noticeable. May include light
scratches, print lines, or a moderate stain.

GRADE 7: Multiple minor surface defects or one moderate defect. Clearly visible on close
inspection.

GRADE 6.5: Several visible surface defects or one significant defect (a clear scratch,
notable stain, or visible crease).

GRADE 6: Multiple noticeable surface defects. The surface has clearly seen wear.

GRADE 5–5.5: Heavy surface wear — multiple scratches, significant staining, visible
creasing or indentations.

GRADE 4 and below: Severe surface damage — deep scratches, heavy staining, significant
creases, writing, or major print defects.

IMPORTANT: You will be given CV measurements that establish the BASELINE grade. Your role
is to refine the CV assessment by distinguishing real defects from printing texture, but
you should NOT drastically upgrade the score. If CV metrics indicate heavy damage
(high scratch coverage, many lines), your grade should reflect that reality even if some
are printing artifacts.

**CV Metrics as Floor**: The CV base score is calculated from objective measurements.
If CV reports 11% scratch coverage, that is SIGNIFICANT damage regardless of whether it's
"printing texture" - the card surface has visible imperfections. Do not grade it as 8.0.
Grade it realistically based on what you see, respecting that high CV metrics = low grade.

You will be given:
- An annotated full card image (CV-detected candidates for scratches and print lines are marked)
- Optional: 2–3 high-resolution tile crops of areas of interest
- CV measurements: scratch_coverage_pct, hough_line_count

Respond ONLY in valid JSON with this exact schema:
{
  "observations": [
    {"area": "...", "defect_type": "scratch|print_line|stain|crease|dent|other", "severity": "faint|minor|moderate|severe", "description": "..."}
  ],
  "most_significant_defect": "...",
  "grade": <number 100-1000>,
  "confidence": "high|medium|low",
  "reasoning": "..."
}

Grade scale (0-1000):
- 950-1000: Gem Mint, flawless surface
- 850-949: Near Mint, one or two faint marks
- 750-849: Excellent, minor surface defects
- 650-749: Very Good, several minor defects
- 550-649: Good, moderate wear
- 450-549: Fair, significant scratches/stains
- 100-449: Poor, heavy surface damage
""".strip()


# ---------------------------------------------------------------------------
# Grade scale label map (for display)
# ---------------------------------------------------------------------------

GRADE_LABELS: dict[float, str] = {
    10.5: "Pristine / 10P",
    10.0: "Gem Mint 10",
    9.0:  "Mint 9",
    8.5:  "NM-MT+ 8.5",
    8.0:  "NM-MT 8",
    7.5:  "NM+ 7.5",
    7.0:  "NM 7",
    6.5:  "EX-MT+ 6.5",
    6.0:  "EX-MT 6",
    5.5:  "EX+ 5.5",
    5.0:  "EX 5",
    4.5:  "VG-EX+ 4.5",
    4.0:  "VG-EX 4",
    3.5:  "VG+ 3.5",
    3.0:  "VG 3",
    2.5:  "G-VG 2.5",
    2.0:  "G 2",
    1.5:  "FR 1.5",
    1.0:  "P 1",
}


def grade_label(grade: float) -> str:
    """Return the human-readable label for a numeric grade."""
    return GRADE_LABELS.get(grade, f"Grade {grade:.1f}")
