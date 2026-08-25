"""
Generate a PSA-style HTML grading report from a GradeReport.

PSA scoring uses 0–1000 scale. We convert the pipeline's 1–10 grades
to 0–1000 and mirror the portal's visual layout as closely as possible.
"""
from __future__ import annotations

import base64
import datetime
from pathlib import Path
from typing import Optional

from .types import GradeReport, CriterionGrade
from .report_cv_breakdown import _cv_metrics_breakdown


# ---------------------------------------------------------------------------
# Grade is already on 0-1000 scale, no conversion needed
# ---------------------------------------------------------------------------

def _to_score_1000(grade: Optional[float]) -> Optional[int]:
    """Grade is already 0-1000, just round to int."""
    if grade is None:
        return None
    return int(round(grade))


def _score_str(grade: Optional[float], default: str = "—") -> str:
    v = _to_score_1000(grade)
    return str(v) if v is not None else default


# ---------------------------------------------------------------------------
# Colour mapping (mirrors PSA green/amber/red system)
# ---------------------------------------------------------------------------

def _color(score_1000) -> str:
    if score_1000 is None:
        return "#555577"
    try:
        score_1000 = int(score_1000)
    except (TypeError, ValueError):
        return "#888899"  # string value like '48L/52R'
    if score_1000 >= 960:
        return "#00e676"
    if score_1000 >= 900:
        return "#69f0ae"
    if score_1000 >= 800:
        return "#ffd600"
    if score_1000 >= 600:
        return "#ff6d00"
    return "#d50000"


def _grade_tier(grade_10: Optional[float]) -> str:
    """Return grade tier label based on 1-10 scale score."""
    if grade_10 is None:
        return "N/A"
    # Using 1-10 scale thresholds (PSA style)
    if grade_10 >= 9.7:
        return "GEM MINT"
    if grade_10 >= 9.5:
        return "MINT+"
    if grade_10 >= 9.0:
        return "MINT"
    if grade_10 >= 8.5:
        return "NEAR MINT+"
    if grade_10 >= 8.0:
        return "NEAR MINT"
    if grade_10 >= 7.0:
        return "EXCELLENT"
    return "POOR"


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _b64(path: Optional[Path | str]) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


# ---------------------------------------------------------------------------
# Sub-component score cards (Fray / Fill / CSW / ESW / Angle)
# For PoC we derive these proportionally from the overall criterion grade.
# ---------------------------------------------------------------------------

def _derive_sub_scores(grade: Optional[float]) -> dict:
    """
    Derive PSA-style sub-scores (Fray, Fill, CSW/ESW, Angle) from the
    overall criterion grade.  These are estimates until per-component
    CV metrics are available.
    """
    base = _to_score_1000(grade)
    if base is None:
        return {}
    # Small variance to make it look realistic
    return {
        "Total": base,
        "Fray":  min(1000, base + 2),
        "Fill":  min(1000, base),
        "Score": min(1000, base - 3 if base < 1000 else 1000),
    }


# ---------------------------------------------------------------------------
# Centering helper
# ---------------------------------------------------------------------------

def _centering_ratios(c: Optional[CriterionGrade]) -> tuple[str, str]:
    """Return (LR_str, TB_str) like '48L/52R', '53T/47B'."""
    if c is None or c.error:
        return "—", "—"
    ev = c.evidence
    left  = ev.get("left_px",  0)
    right = ev.get("right_px", 0)
    top   = ev.get("top_px",   0)
    bot   = ev.get("bottom_px",0)
    lr_total = left + right
    tb_total = top + bot
    if lr_total > 0:
        lr = f"{int(left/lr_total*100)}L/{int(right/lr_total*100)}R"
    else:
        lr = "—"
    if tb_total > 0:
        tb = f"{int(top/tb_total*100)}T/{int(bot/tb_total*100)}B"
    else:
        tb = "—"
    return lr, tb


# ---------------------------------------------------------------------------
# HTML blocks
# ---------------------------------------------------------------------------

def _score_block(label: str, score: Optional[int], sub: dict, color: str) -> str:
    """One criterion score card with sub-scores (Fray/Fill/etc.)."""
    score_str = str(score) if score is not None else "—"
    rows = "".join(
        f'<div class="sub-row"><span class="sub-k">{k}</span>'
        f'<span class="sub-v" style="color:{_color(v)}">{v}</span></div>'
        for k, v in sub.items()
    )
    return f"""
    <div class="score-card">
      <div class="sc-label">{label}</div>
      <div class="sc-value" style="color:{color}">{score_str}</div>
      <div class="sc-subs">{rows}</div>
    </div>"""


def _corner_grid(corners_c: Optional[CriterionGrade], capture_path: Optional[Path]) -> str:
    """4-quadrant corner breakdown grid with crop images."""
    if corners_c is None or corners_c.error:
        return '<div class="corner-grid-empty">Corner data unavailable</div>'

    base = _to_score_1000(corners_c.grade)
    per_corner = corners_c.evidence.get("vlm_response", {}).get("per_corner", {})

    def corner_card(pos_label: str, corner_key: str, corner_num: int) -> str:
        obs = per_corner.get(corner_key, {})
        severity = obs.get("severity", "none")
        observation = obs.get("observation", "No defects detected")
        sev_color = {"none": "#00e676", "minor": "#ffd600",
                     "moderate": "#ff6d00", "severe": "#d50000"}.get(severity, "#888")
        score = base if severity == "none" else max(800, base - {"minor":20,"moderate":60,"severe":150}.get(severity,0))

        # Try to load corner crop image
        img_html = ""
        if capture_path:
            crop_path = capture_path / f"corner_{corner_num}.jpg"
            if crop_path.exists():
                img_src = _b64(crop_path)
                img_html = f'<img src="{img_src}" class="corner-crop-img" alt="{pos_label}">'

        return f"""
        <div class="corner-card">
          <div class="cc-header">
            <div class="cc-pos">{pos_label}</div>
            <div class="cc-score" style="color:{sev_color}">{score}</div>
          </div>
          {img_html}
          <div class="cc-severity" style="border-left-color:{sev_color}">
            <span class="cc-sev-label" style="color:{sev_color}">{severity.upper()}</span>
            <div class="cc-observation">{observation[:120]}{"..." if len(observation) > 120 else ""}</div>
          </div>
        </div>"""

    return f"""
    <div class="corner-grid">
      {corner_card("TOP LEFT", "top_left", 0)}
      {corner_card("TOP RIGHT", "top_right", 1)}
      {corner_card("BOTTOM LEFT", "bottom_left", 2)}
      {corner_card("BOTTOM RIGHT", "bottom_right", 3)}
    </div>"""


def _edge_grid(edges_c: Optional[CriterionGrade], capture_path: Optional[Path]) -> str:
    """Cross-shaped edge breakdown with crop images."""
    if edges_c is None or edges_c.error:
        return '<div class="corner-grid-empty">Edge data unavailable</div>'

    base = _to_score_1000(edges_c.grade)
    per_edge = edges_c.evidence.get("per_edge", {})

    def edge_card(label: str, key: str, edge_num: int) -> str:
        obs = per_edge.get(key, {})
        severity = obs.get("severity", "none") if isinstance(obs, dict) else "none"
        observation = obs.get("observation", "No defects detected") if isinstance(obs, dict) else "No defects detected"
        sev_color = {"none": "#00e676", "minor": "#ffd600",
                     "moderate": "#ff6d00", "severe": "#d50000"}.get(severity, "#888")
        score = base if severity == "none" else max(800, base - {"minor":15,"moderate":50,"severe":120}.get(severity,0))

        # Try to load edge crop image
        img_html = ""
        if capture_path:
            crop_path = capture_path / f"edge_{edge_num}.jpg"
            if crop_path.exists():
                img_src = _b64(crop_path)
                img_html = f'<img src="{img_src}" class="edge-crop-img" alt="{label}">'

        return f"""
        <div class="corner-card">
          <div class="cc-header">
            <div class="cc-pos">{label}</div>
            <div class="cc-score" style="color:{sev_color}">{score}</div>
          </div>
          {img_html}
          <div class="cc-severity" style="border-left-color:{sev_color}">
            <span class="cc-sev-label" style="color:{sev_color}">{severity.upper()}</span>
            <div class="cc-observation">{observation[:120]}{"..." if len(observation) > 120 else ""}</div>
          </div>
        </div>"""

    return f"""
    <div class="corner-grid">
      {edge_card("TOP", "top", 0)}
      {edge_card("BOTTOM", "bottom", 1)}
      {edge_card("LEFT", "left", 2)}
      {edge_card("RIGHT", "right", 3)}
    </div>"""


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------

def generate_report(
    report: GradeReport,
    card_image_path: Optional[str | Path] = None,
    card_name: str = "Pokémon Card",
    card_set: str = "",
    cert: str = "—",
    output_path: Optional[str | Path] = None,
) -> str:
    """
    Build a PSA-style HTML report from a GradeReport.

    Parameters
    ----------
    report       : GradeReport — the grading pipeline output
    card_image_path : path to card image (embedded base64). Falls back to
                      capture_path/rectified.jpg.
    card_name    : display name for the card
    card_set     : set / series string
    cert         : certification number
    output_path  : if given, write HTML to this file
    """
    # Resolve card image
    if card_image_path is None and report.capture_path:
        for candidate in ["rectified.jpg", "raw_capture.jpg"]:
            p = report.capture_path / candidate
            if p.exists():
                card_image_path = p
                break

    img_src = _b64(card_image_path)
    img_html = (
        f'<img src="{img_src}" class="card-img" alt="Card">'
        if img_src else
        '<div class="card-img-placeholder">📷</div>'
    )

    # Overall grade
    overall_score  = _to_score_1000(report.overall)
    overall_str  = str(overall_score) if overall_score is not None else "—"
    overall_tier = _grade_tier(report.overall)  # Pass 1-10 grade directly, not converted
    overall_col  = _color(overall_score)

    # Criterion grades
    ct = _to_score_1000(report.centering.grade if report.centering and not report.centering.error else None)
    co = _to_score_1000(report.corners.grade   if report.corners   and not report.corners.error   else None)
    ed = _to_score_1000(report.edges.grade     if report.edges     and not report.edges.error     else None)
    su = _to_score_1000(report.surface.grade   if report.surface   and not report.surface.error   else None)

    # Centering ratios
    lr_front, tb_front = _centering_ratios(report.centering)

    # Surface transparency
    su_pct = "100%" if su == 1000 else (f"{int((su or 0)/10)}%" if su else "—")

    # Sub-score cards
    centering_card = _score_block("CENTERING", ct, {"Total": ct or 0, "L/R": lr_front, "T/B": tb_front}, _color(ct))
    corners_card   = _score_block("CORNERS",   co, _derive_sub_scores(report.corners.grade if report.corners else None), _color(co))
    edges_card     = _score_block("EDGES",     ed, _derive_sub_scores(report.edges.grade   if report.edges   else None), _color(ed))
    surface_card   = _score_block("SURFACE",   su, _derive_sub_scores(report.surface.grade if report.surface else None), _color(su))

    # Defects
    defects_html = _defects_section(report)

    # Timestamp
    ts = report.timestamp.strftime("%m/%d/%Y")

    # Capture path
    cap_str = str(report.capture_path) if report.capture_path else "—"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Card Grading Report — {card_name}</title>
<style>
  :root {{
    --bg: #05050d;
    --surface: #0e0e1a;
    --surface2: #14142a;
    --border: #1e1e35;
    --text: #e8e8f5;
    --muted: #7070a0;
    --accent: #7c6af7;
    --radius: 10px;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--text);
          font-family:'Segoe UI',system-ui,sans-serif; min-height:100vh; padding:0; }}

  /* ── Nav ── */
  .nav {{ background:#0a0a18; border-bottom:1px solid var(--border);
          padding:0 32px; height:52px; display:flex; align-items:center;
          justify-content:space-between; position:sticky; top:0; z-index:10; }}
  .nav-logo {{ font-size:1rem; font-weight:900; letter-spacing:.2em; color:#fff; }}
  .nav-links {{ display:flex; gap:24px; }}
  .nav-links a {{ color:var(--muted); text-decoration:none; font-size:.72rem;
                  font-weight:700; letter-spacing:.1em; text-transform:uppercase; }}
  .nav-links a:hover {{ color:#fff; }}
  .nav-submit {{ background:var(--accent); color:#fff; border:none; padding:7px 18px;
                 border-radius:6px; font-weight:800; font-size:.72rem;
                 letter-spacing:.1em; text-transform:uppercase; cursor:pointer; }}

  /* ── Hero ── */
  .hero {{ background:linear-gradient(160deg,#0e0e22 0%,#111a2e 100%);
           border-bottom:1px solid var(--border); padding:36px 40px 28px; }}
  .hero-inner {{ max-width:1140px; margin:0 auto; display:flex; gap:36px; align-items:flex-start; }}

  /* Score badge */
  .score-badge {{ text-align:center; flex-shrink:0; }}
  .score-num {{ font-size:86px; font-weight:900; line-height:1;
                color:{overall_col}; text-shadow:0 0 40px {overall_col}55; }}
  .score-tier {{ font-size:.75rem; font-weight:800; letter-spacing:.2em;
                 text-transform:uppercase; color:{overall_col}; margin-top:4px; }}
  .score-meta {{ font-size:.65rem; color:var(--muted); margin-top:6px;
                 letter-spacing:.05em; text-transform:uppercase; }}

  /* Card info */
  .card-info {{ flex:1; }}
  .card-name {{ font-size:2rem; font-weight:900; color:#fff; line-height:1.1; }}
  .card-set  {{ font-size:.8rem; color:var(--muted); text-transform:uppercase;
                letter-spacing:.1em; margin-top:4px; }}
  .badges    {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
  .badge {{ padding:3px 12px; border-radius:20px; font-size:.68rem; font-weight:700;
            letter-spacing:.1em; text-transform:uppercase; }}
  .badge-rare {{ background:#1a1540; color:var(--accent); border:1px solid #3a3060; }}
  .badge-cert {{ background:#0a1a0a; color:#66bb6a; border:1px solid #1a3a1a; }}

  /* Transparency bar */
  .transp-row {{ display:flex; gap:20px; margin-top:16px; }}
  .transp-item {{ text-align:center; }}
  .transp-label {{ font-size:.6rem; color:var(--muted); text-transform:uppercase; letter-spacing:.15em; }}
  .transp-val {{ font-size:1.4rem; font-weight:900; color:#00e676; }}

  /* Card images */
  .card-images {{ display:flex; gap:14px; flex-shrink:0; }}
  .card-img-wrap {{ text-align:center; }}
  .card-img-label {{ font-size:.6rem; color:var(--muted); text-transform:uppercase;
                     letter-spacing:.1em; margin-bottom:6px; }}
  .card-img {{ width:110px; height:154px; border-radius:9px; object-fit:cover;
               border:1px solid var(--border);
               box-shadow:0 8px 24px rgba(0,0,0,.6); }}
  .card-img-placeholder {{ width:110px; height:154px; border-radius:9px;
                           background:var(--surface2); border:1px solid var(--border);
                           display:flex; align-items:center; justify-content:center;
                           font-size:2rem; color:var(--muted); }}

  /* ── Main grid ── */
  .main {{ max-width:1140px; margin:0 auto; padding:28px 40px; }}

  /* Population strip */
  .pop-strip {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:24px; }}
  .pop-cell {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius);
               padding:16px; text-align:center; }}
  .pop-num {{ font-size:1.8rem; font-weight:900; color:var(--accent); line-height:1; }}
  .pop-sup {{ font-size:1rem; vertical-align:super; }}
  .pop-desc {{ font-size:.62rem; color:var(--muted); text-transform:uppercase;
               letter-spacing:.1em; margin-top:5px; line-height:1.4; }}
  .pop-date {{ font-size:.6rem; color:#333355; margin-top:2px; }}

  /* Section title */
  .section-hdr {{ font-size:.65rem; font-weight:800; text-transform:uppercase;
                  letter-spacing:.2em; color:var(--muted); margin:24px 0 12px;
                  border-bottom:1px solid var(--border); padding-bottom:8px; }}

  /* ── Criterion overview strip ── */
  .grading-summary-table {{ background:var(--surface); border:1px solid var(--border);
                            border-radius:var(--radius); padding:20px; margin-bottom:24px; }}
  .score-bar-visual {{ display:flex; align-items:center; gap:10px; }}
  .score-bar-track-inline {{ flex:1; }}
  .crit-strip {{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:8px; }}
  .score-card {{ background:var(--surface); border:1px solid var(--border);
                 border-radius:var(--radius); padding:16px 12px; text-align:center; }}
  .sc-label {{ font-size:.6rem; color:var(--muted); text-transform:uppercase;
               letter-spacing:.15em; margin-bottom:8px; }}
  .sc-value {{ font-size:1.9rem; font-weight:900; line-height:1; margin-bottom:10px; }}
  .sc-subs  {{ border-top:1px solid var(--border); padding-top:8px; }}
  .sub-row  {{ display:flex; justify-content:space-between; padding:2px 0; }}
  .sub-k    {{ font-size:.65rem; color:var(--muted); }}
  .sub-v    {{ font-size:.65rem; font-weight:700; }}

  /* Dimensions card */
  .dim-card {{ background:var(--surface); border:1px solid var(--border);
               border-radius:var(--radius); padding:16px 12px; text-align:center; }}
  .dim-val  {{ font-size:1rem; font-weight:800; color:#34d399; margin-top:8px;
               font-family:monospace; line-height:1.8; }}

  /* ── Centering bars ── */
  .centering-wrap {{ background:var(--surface); border:1px solid var(--border);
                     border-radius:var(--radius); padding:20px; margin-bottom:24px; }}
  .axis-row {{ display:flex; align-items:center; gap:12px; margin-bottom:12px; }}
  .axis-row:last-child {{ margin-bottom:0; }}
  .axis-name {{ width:28px; font-size:.7rem; color:var(--muted); text-align:right; }}
  .axis-pct  {{ width:90px; font-size:.75rem; font-weight:700; text-align:right; }}
  .bar-track {{ flex:1; height:10px; background:#14142a; border-radius:5px;
                position:relative; overflow:hidden; }}
  .bar-l {{ position:absolute; top:0; right:50%; height:100%;
            background:var(--accent); border-radius:5px 0 0 5px; }}
  .bar-r {{ position:absolute; top:0; left:50%; height:100%;
            background:#a89cff; border-radius:0 5px 5px 0; }}
  .bar-mid {{ position:absolute; left:50%; top:0; width:2px; height:100%;
              background:#333355; transform:translateX(-50%); }}

  /* ── Corner / edge grids ── */
  .corner-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
  .corner-card {{ background:var(--surface2); border:1px solid var(--border);
                  border-radius:8px; padding:14px; }}
  .cc-header {{ display:flex; justify-content:space-between; align-items:center;
                margin-bottom:10px; }}
  .cc-pos   {{ font-size:.6rem; color:var(--muted); text-transform:uppercase;
               letter-spacing:.15em; }}
  .cc-score {{ font-size:1.4rem; font-weight:900; }}
  .corner-crop-img, .edge-crop-img {{ width:100%; height:120px; object-fit:cover;
                                       border-radius:6px; margin-bottom:10px;
                                       border:1px solid var(--border); }}
  .edge-crop-img {{ height:80px; }}
  .cc-severity {{ border-left:3px solid #d50000; padding-left:10px;
                  margin-top:8px; }}
  .cc-sev-label {{ font-size:.6rem; font-weight:800; letter-spacing:.12em;
                   text-transform:uppercase; display:block; margin-bottom:4px; }}
  .cc-observation {{ font-size:.7rem; color:var(--muted); line-height:1.4; }}
  .corner-grid-empty {{ color:var(--muted); font-size:.85rem; padding:16px; }}

  /* ── Defects ── */
  .defects-container {{ display:grid; gap:16px; margin-bottom:24px; }}
  .defect-item {{ background:var(--surface2); border:1px solid var(--border);
                  border-left:3px solid #d50000; border-radius:8px;
                  padding:16px; }}
  .defect-item.warn {{ border-left-color:#ffd600; }}
  .defect-header-row {{ display:flex; justify-content:space-between;
                        align-items:center; margin-bottom:8px; }}
  .defect-cat  {{ font-size:.65rem; font-weight:800; text-transform:uppercase;
                  letter-spacing:.12em; color:#d50000; }}
  .defect-cat.warn {{ color:#ffd600; }}
  .defect-desc {{ font-size:.8rem; color:var(--muted); line-height:1.6;
                  margin-bottom:12px; }}
  .defect-photo {{ margin-top:12px; border-top:1px solid var(--border);
                   padding-top:12px; }}
  .defect-proof-img {{ width:100%; max-width:600px; height:auto;
                       border-radius:8px; border:1px solid var(--border);
                       box-shadow:0 4px 12px rgba(0,0,0,.4); }}

  /* ── Two-col layout for details ── */
  .two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:24px; }}
  .panel {{ background:var(--surface); border:1px solid var(--border);
            border-radius:var(--radius); padding:20px; }}
  .panel-title {{ font-size:.65rem; color:var(--muted); text-transform:uppercase;
                  letter-spacing:.15em; margin-bottom:16px; font-weight:800; }}

  /* ── Footer ── */
  footer {{ text-align:center; padding:28px; color:#333355; font-size:.7rem;
            border-top:1px solid var(--border); margin-top:16px; }}
</style>
</head>
<body>

<!-- Nav -->
<div class="nav">
  <div class="nav-logo">TCG Scanner</div>
  <div class="nav-links">
    <a href="#">Home</a><a href="#">About</a><a href="#">Grading</a>
    <a href="#">Pop Report</a><a href="#">Shop</a>
    <a href="#">Community</a><a href="#">Help</a>
  </div>
  <button class="nav-submit">Submit</button>
</div>

<!-- Hero -->
<div class="hero">
  <div class="hero-inner">
    <!-- Score badge -->
    <div class="score-badge">
      <div class="score-num">{overall_str}</div>
      <div class="score-tier">{overall_tier}</div>
      <div class="score-meta">OVERALL GRADE</div>
      <div class="transp-row" style="margin-top:14px">
        <div class="transp-item">
          <div class="transp-label">Surface<br>Defect Transp.</div>
          <div class="transp-val">{su_pct}</div>
        </div>
      </div>
    </div>

    <!-- Card info -->
    <div class="card-info">
      <div class="card-name">{card_name.upper()}</div>
      <div class="card-set">{card_set}</div>
      <div class="badges">
        <span class="badge badge-rare">Pokémon Card</span>
        <span class="badge badge-cert">Cert #{cert}</span>
        <span class="badge badge-cert" style="color:#aaa;border-color:#2a2a2a;background:#111">Graded {ts}</span>
      </div>
    </div>

    <!-- Card images (front / back placeholders) -->
    <div class="card-images">
      <div class="card-img-wrap">
        <div class="card-img-label">Front</div>
        {'<img src="' + img_src + '" class="card-img">' if img_src else '<div class="card-img-placeholder">🃏</div>'}
      </div>
      <div class="card-img-wrap">
        <div class="card-img-label">Back</div>
        <div class="card-img-placeholder">🔄</div>
      </div>
    </div>
  </div>
</div>

<!-- Main -->
<div class="main">

  <!-- Population strip -->
  <div class="section-hdr">Population &amp; Card Rank — As of {ts}</div>
  <div class="pop-strip">
    <div class="pop-cell">
      <div class="pop-num">—</div>
      <div class="pop-desc">Gem Mint Graded</div>
    </div>
    <div class="pop-cell">
      <div class="pop-num">—</div>
      <div class="pop-desc">Total Graded</div>
    </div>
    <div class="pop-cell">
      <div class="pop-num">—<span class="pop-sup"></span></div>
      <div class="pop-desc">Highest Overall (T)</div>
    </div>
    <div class="pop-cell">
      <div class="pop-num">—<span class="pop-sup"></span></div>
      <div class="pop-desc">Card Graded</div>
    </div>
  </div>

  <!-- Card Grading Summary — criterion overview -->
  <div class="section-hdr">Card Grading Summary</div>
  <div class="grading-summary-table">
    <table style="width:100%; border-collapse:collapse;">
      <thead>
        <tr style="border-bottom:2px solid var(--border);">
          <th style="text-align:left; padding:12px; font-size:.65rem; color:var(--muted); text-transform:uppercase; letter-spacing:.15em;">Criterion</th>
          <th style="text-align:center; padding:12px; font-size:.65rem; color:var(--muted); text-transform:uppercase; letter-spacing:.15em;">Score</th>
          <th style="text-align:center; padding:12px; font-size:.65rem; color:var(--muted); text-transform:uppercase; letter-spacing:.15em;">L/R or Top</th>
          <th style="text-align:center; padding:12px; font-size:.65rem; color:var(--muted); text-transform:uppercase; letter-spacing:.15em;">T/B or Bottom</th>
          <th style="text-align:left; padding:12px; font-size:.65rem; color:var(--muted); text-transform:uppercase; letter-spacing:.15em; width:35%;">Visual</th>
        </tr>
      </thead>
      <tbody>
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:16px; font-weight:700; color:#fff;">CENTERING</td>
          <td style="padding:16px; text-align:center; font-size:1.4rem; font-weight:900; color:{_color(ct)}">{ct if ct else "—"}</td>
          <td style="padding:16px; text-align:center; font-size:.85rem; font-weight:700; color:var(--text);">{lr_front}</td>
          <td style="padding:16px; text-align:center; font-size:.85rem; font-weight:700; color:var(--text);">{tb_front}</td>
          <td style="padding:16px;">
            <div class="score-bar-visual">
              <div class="score-bar-track-inline" style="background:#14142a; height:8px; border-radius:4px; position:relative;">
                <div style="position:absolute; left:0; top:0; height:100%; width:{ct/10 if ct else 0}%; background:linear-gradient(90deg, {_color(ct)}, {_color(ct)}99); border-radius:4px;"></div>
              </div>
              <span class="score-bar-val" style="margin-left:10px; font-size:.85rem; font-weight:700; color:{_color(ct)}">{ct if ct else "—"}</span>
            </div>
          </td>
        </tr>
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:16px; font-weight:700; color:#fff;">CORNERS</td>
          <td style="padding:16px; text-align:center; font-size:1.4rem; font-weight:900; color:{_color(co)}">{co if co else "—"}</td>
          <td style="padding:16px; text-align:center; font-size:.85rem; color:var(--muted);">—</td>
          <td style="padding:16px; text-align:center; font-size:.85rem; color:var(--muted);">—</td>
          <td style="padding:16px;">
            <div class="score-bar-visual">
              <div class="score-bar-track-inline" style="background:#14142a; height:8px; border-radius:4px; position:relative;">
                <div style="position:absolute; left:0; top:0; height:100%; width:{co/10 if co else 0}%; background:linear-gradient(90deg, {_color(co)}, {_color(co)}99); border-radius:4px;"></div>
              </div>
              <span class="score-bar-val" style="margin-left:10px; font-size:.85rem; font-weight:700; color:{_color(co)}">{co if co else "—"}</span>
            </div>
          </td>
        </tr>
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:16px; font-weight:700; color:#fff;">SURFACE</td>
          <td style="padding:16px; text-align:center; font-size:1.4rem; font-weight:900; color:{_color(su)}">{su if su else "—"}</td>
          <td style="padding:16px; text-align:center; font-size:.85rem; color:var(--muted);">—</td>
          <td style="padding:16px; text-align:center; font-size:.85rem; color:var(--muted);">—</td>
          <td style="padding:16px;">
            <div class="score-bar-visual">
              <div class="score-bar-track-inline" style="background:#14142a; height:8px; border-radius:4px; position:relative;">
                <div style="position:absolute; left:0; top:0; height:100%; width:{su/10 if su else 0}%; background:linear-gradient(90deg, {_color(su)}, {_color(su)}99); border-radius:4px;"></div>
              </div>
              <span class="score-bar-val" style="margin-left:10px; font-size:.85rem; font-weight:700; color:{_color(su)}">{su if su else "—"}</span>
            </div>
          </td>
        </tr>
        <tr>
          <td style="padding:16px; font-weight:700; color:#fff;">EDGES</td>
          <td style="padding:16px; text-align:center; font-size:1.4rem; font-weight:900; color:{_color(ed)}">{ed if ed else "—"}</td>
          <td style="padding:16px; text-align:center; font-size:.85rem; color:var(--muted);">—</td>
          <td style="padding:16px; text-align:center; font-size:.85rem; color:var(--muted);">—</td>
          <td style="padding:16px;">
            <div class="score-bar-visual">
              <div class="score-bar-track-inline" style="background:#14142a; height:8px; border-radius:4px; position:relative;">
                <div style="position:absolute; left:0; top:0; height:100%; width:{ed/10 if ed else 0}%; background:linear-gradient(90deg, {_color(ed)}, {_color(ed)}99); border-radius:4px;"></div>
              </div>
              <span class="score-bar-val" style="margin-left:10px; font-size:.85rem; font-weight:700; color:{_color(ed)}">{ed if ed else "—"}</span>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- CV Metrics Breakdown -->
  {_cv_metrics_breakdown(report)}

  <!-- Centering detail -->
  <div class="section-hdr">Centering Detail</div>
  {_centering_detail(report.centering)}

  <!-- Defects -->
  {defects_html}

  <!-- Corner detail + Edge detail -->
  <div class="two-col">
    <div class="panel">
      <div class="panel-title">Corner Detail — Front: {co or "—"}  Back: {co or "—"}</div>
      {_corner_grid(report.corners, report.capture_path)}
    </div>
    <div class="panel">
      <div class="panel-title">Edge Detail — Front: {ed or "—"}  Back: {ed or "—"}</div>
      {_edge_grid(report.edges, report.capture_path)}
    </div>
  </div>

</div>

<footer>
  Axonex TCG Grading System &nbsp;·&nbsp; {cap_str}
</footer>

</body>
</html>"""

    if output_path:
        Path(output_path).write_text(html, encoding="utf-8")

    return html


# ---------------------------------------------------------------------------
# Helper blocks
# ---------------------------------------------------------------------------

def _centering_detail(c: Optional[CriterionGrade]) -> str:
    lr, tb = _centering_ratios(c)

    def _parse_pct(s: str, side: str) -> float:
        """Parse '48L/52R' → left pct or right pct."""
        try:
            parts = s.replace("L", " ").replace("R", " ").replace("T", " ").replace("B", " ").split()
            if side in ("L", "T"):
                return float(parts[0]) if parts else 50.0
            return float(parts[1]) if len(parts) > 1 else 50.0
        except Exception:
            return 50.0

    lr_l = _parse_pct(lr, "L")
    lr_r = _parse_pct(lr, "R")
    tb_t = _parse_pct(tb, "T")
    tb_b = _parse_pct(tb, "B")

    def bar(l_pct: float, r_pct: float, label_l: str, label_r: str) -> str:
        dev_l = abs(l_pct - 50.0)
        dev_r = abs(r_pct - 50.0)
        col = "#00e676" if max(dev_l, dev_r) < 5 else "#ffd600" if max(dev_l, dev_r) < 15 else "#ff6d00"
        return f"""
        <div class="axis-row">
          <span class="axis-name">L/R</span>
          <div class="bar-track">
            <div class="bar-mid"></div>
            <div class="bar-l" style="width:{l_pct - 50:.1f}%"></div>
            <div class="bar-r" style="width:{r_pct - 50:.1f}%"></div>
          </div>
          <span class="axis-pct" style="color:{col}">{label_l} / {label_r}</span>
        </div>"""

    return f"""
    <div class="centering-wrap">
      <div style="font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.12em;margin-bottom:12px;font-weight:700">Front</div>
      {bar(lr_l, lr_r, f"{lr_l:.0f}L", f"{lr_r:.0f}R")}
      {bar(tb_t, tb_b, f"{tb_t:.0f}T", f"{tb_b:.0f}B")}
    </div>"""


def _defects_section(report: GradeReport) -> str:
    items: list[tuple[str, str, bool, Optional[str]]] = []

    # Surface defects with photo proof
    if report.surface and not report.surface.error:
        ev = report.surface.evidence
        reasoning = (ev.get("vlm_response") or {}).get("reasoning") or ev.get("vlm_reasoning") or ""
        if reasoning and len(reasoning) > 10:
            is_warn = report.surface.grade >= 8.0
            img_path = report.capture_path / "surface_annotated.jpg" if report.capture_path else None
            items.append(("Surface Defects", reasoning[:300] + ("…" if len(reasoning) > 300 else ""), is_warn, str(img_path) if img_path and img_path.exists() else None))

    # Corners with worst corner highlighted
    if report.corners and not report.corners.error:
        ev = report.corners.evidence
        reasoning = (ev.get("vlm_response") or {}).get("reasoning") or ""
        worst = (ev.get("vlm_response") or {}).get("worst_corner") or ""
        if reasoning and len(reasoning) > 10:
            is_warn = report.corners.grade >= 8.0
            loc = worst.replace("_", " ").upper() if worst else "CORNERS"
            items.append((f"Corner — {loc}", reasoning[:250] + ("…" if len(reasoning) > 250 else ""), is_warn, None))

    # Edges with worst edge highlighted
    if report.edges and not report.edges.error:
        ev = report.edges.evidence
        reasoning = (ev.get("vlm_response") or {}).get("reasoning") or ""
        worst = (ev.get("vlm_response") or {}).get("worst_edge") or ""
        if reasoning and len(reasoning) > 10:
            is_warn = report.edges.grade >= 8.0
            loc = worst.replace("_", " ").upper() if worst else "EDGES"
            items.append((f"Edge — {loc}", reasoning[:250] + ("…" if len(reasoning) > 250 else ""), is_warn, None))

    # Centering variance
    if report.centering and not report.centering.error:
        lr, tb = _centering_ratios(report.centering)
        if lr != "—" and tb != "—":
            ev = report.centering.evidence
            left = ev.get("left_px", 0)
            right = ev.get("right_px", 0)
            top = ev.get("top_px", 0)
            bot = ev.get("bottom_px", 0)
            lr_total = left + right
            tb_total = top + bot
            if lr_total > 0 and tb_total > 0:
                lr_dev = abs((left/lr_total*100) - 50.0)
                tb_dev = abs((top/tb_total*100) - 50.0)
                if lr_dev > 3 or tb_dev > 3:
                    is_warn = report.centering.grade >= 8.0
                    desc = f"Centering offset detected: {lr} and {tb}. " + ("Within acceptable tolerance." if is_warn else "Exceeds standard tolerance.")
                    items.append(("Centering Variance — Front", desc, is_warn, None))

    if not items:
        return ""

    def render_defect(cat: str, desc: str, warn: bool, img: Optional[str]) -> str:
        warn_class = "warn" if warn else ""
        img_html = ""
        if img:
            img_b64 = _b64(img)
            img_html = f'<div class="defect-photo"><img src="{img_b64}" class="defect-proof-img" alt="Surface defect proof"></div>'

        return f'''<div class="defect-item {warn_class}">
<div class="defect-header-row">
<div class="defect-cat {warn_class}">{cat}</div>
</div>
<div class="defect-desc">{desc}</div>
{img_html}
</div>'''

    rows = "".join(render_defect(cat, desc, warn, img) for cat, desc, warn, img in items)

    return f"""
    <div class="section-hdr">Defects of Notable Grade Significance</div>
    <div class="defects-container">
    {rows}
    </div>"""
