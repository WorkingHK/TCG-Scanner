"""
Helper function to generate CV metrics breakdown section for the HTML report.
Shows CV base score, VLM adjustment, and final grade.
"""


def _color(score: int) -> str:
    """Return color for a score (1-10 scale)."""
    if score is None:
        return "#888"
    if score >= 900:
        return "#00e676"
    elif score >= 800:
        return "#76ff03"
    elif score >= 700:
        return "#ffd600"
    elif score >= 600:
        return "#ffab00"
    elif score >= 500:
        return "#ff6d00"
    else:
        return "#d50000"


def _cv_metrics_breakdown(report) -> str:
    """
    Generate a section showing CV vs VLM breakdown for each criterion.
    Only shows if cv_base_score_1000 is available in evidence.
    """

    # Check if any criterion has CV metrics
    has_cv_metrics = False
    for criterion in ['corners', 'edges', 'surface']:
        c = getattr(report, criterion, None)
        if c and c.evidence.get('cv_base_score_1000') is not None:
            has_cv_metrics = True
            break

    if not has_cv_metrics:
        return ""

    rows = []

    for criterion_name in ['Corners', 'Edges', 'Surface']:
        c = getattr(report, criterion_name.lower(), None)
        if not c:
            continue

        evidence = c.evidence or {}
        cv_base = evidence.get('cv_base_score_1000')
        vlm_raw = evidence.get('vlm_raw_grade_1000')
        vlm_adj = evidence.get('vlm_adjustment', 0)
        final = evidence.get('final_grade_1000')
        vlm_disabled = evidence.get('vlm_disabled', False)

        if cv_base is None:
            continue

        # Color coding
        cv_color = _color(cv_base)
        final_color = _color(final) if final else cv_color
        adj_color = "#00e676" if vlm_adj >= 0 else "#d50000"

        status = "CV Only" if vlm_disabled else "CV + VLM"

        row = f"""
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:14px; font-weight:700; color:#fff;">{criterion_name.upper()}</td>
          <td style="padding:14px; text-align:center;">
            <span style="font-size:1.2rem; font-weight:900; color:{cv_color}">{int(cv_base)}</span>
          </td>
          <td style="padding:14px; text-align:center;">
            <span style="font-size:1.0rem; font-weight:700; color:{adj_color}">
              {'+' if vlm_adj > 0 else ''}{int(vlm_adj) if vlm_adj else '—'}
            </span>
          </td>
          <td style="padding:14px; text-align:center;">
            <span style="font-size:1.2rem; font-weight:900; color:{final_color}">{int(final) if final else int(cv_base)}</span>
          </td>
          <td style="padding:14px; text-align:center; font-size:0.7rem; color:var(--muted);">{status}</td>
        </tr>
        """
        rows.append(row)

    if not rows:
        return ""

    return f"""
  <!-- CV Metrics Breakdown -->
  <div class="section-hdr">Grading Methodology Breakdown</div>
  <div style="background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:20px; margin-bottom:24px;">
    <div style="font-size:0.75rem; color:var(--muted); margin-bottom:16px;">
      <strong>CV-Driven Scoring:</strong> Computer vision metrics establish the objective base score (0-1000).
      {'VLM (Vision Language Model) can refine within ±50 points based on visual assessment.' if not vlm_disabled else 'VLM is currently disabled for CV tuning - using pure CV metrics only.'}
    </div>
    <table style="width:100%; border-collapse:collapse;">
      <thead>
        <tr style="border-bottom:2px solid var(--border);">
          <th style="text-align:left; padding:12px; font-size:.65rem; color:var(--muted); text-transform:uppercase;">Criterion</th>
          <th style="text-align:center; padding:12px; font-size:.65rem; color:var(--muted); text-transform:uppercase;">CV Base</th>
          <th style="text-align:center; padding:12px; font-size:.65rem; color:var(--muted); text-transform:uppercase;">VLM Adj</th>
          <th style="text-align:center; padding:12px; font-size:.65rem; color:var(--muted); text-transform:uppercase;">Final</th>
          <th style="text-align:center; padding:12px; font-size:.65rem; color:var(--muted); text-transform:uppercase;">Method</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </div>
    """

# Export for use in report_html.py
__all__ = ['_cv_metrics_breakdown']
