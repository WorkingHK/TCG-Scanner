"""
TCG Grader — full PySide6 desktop app with settings dialog and TAG Portal HTML report.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QImage, QPixmap, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from tcg_grading.capture import UVCCamera
from tcg_grading.pipeline import grade_card
from tcg_grading.report_html import generate_report as generate_html_report
from tcg_grading.types import GradeReport

logger = logging.getLogger(__name__)

SETTINGS_FILE = Path(__file__).parent.parent / ".tcg_settings.json"


# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except Exception:
            pass
    return {"api_key": "", "card_name": "", "card_set": "", "cert": ""}


def save_settings(data: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Grade colour helpers  (TAG Portal green / yellow / red)
# ---------------------------------------------------------------------------

def _tag_score(grade: Optional[float]) -> str:
    if grade is None:
        return "—"
    return str(int(round(grade)))  # Grade is already 0-1000


def _grade_color(grade: Optional[float]) -> str:
    if grade is None:
        return "#555577"
    s = grade  # Already 0-1000, no conversion needed
    if s >= 960: return "#00e676"
    if s >= 900: return "#69f0ae"
    if s >= 800: return "#ffd600"
    if s >= 600: return "#ff6d00"
    return "#d50000"


def _grade_tier(grade: Optional[float]) -> str:
    if grade is None:
        return "N/A"
    s = grade  # Already 0-1000, no conversion needed
    if s >= 970: return "GEM MINT"
    if s >= 950: return "MINT+"
    if s >= 900: return "MINT"
    if s >= 850: return "NEAR MINT+"
    if s >= 800: return "NEAR MINT"
    if s >= 700: return "EXCELLENT"
    return "POOR"


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self.setStyleSheet("""
            QDialog { background: #0e0e1a; color: #e8e8f5; }
            QLabel { color: #a0a0c0; font-size: 13px; }
            QLineEdit, QComboBox {
                background: #14142a; border: 1px solid #2a2a45;
                border-radius: 6px; padding: 8px 12px;
                color: #e8e8f5; font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus { border-color: #7c6af7; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background: #14142a; color: #e8e8f5; border: 1px solid #2a2a45; }
            QDialogButtonBox QPushButton {
                background: #7c6af7; color: white; border: none;
                border-radius: 6px; padding: 8px 20px; font-weight: bold;
            }
            QDialogButtonBox QPushButton:hover { background: #9d8fff; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("⚙  Configuration")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #e8e8f5;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.api_key_edit = QLineEdit(settings.get("api_key", ""))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-ant-api03-...")
        form.addRow("Anthropic API Key:", self.api_key_edit)

        # Camera selector
        self.camera_combo = QComboBox()
        cameras = UVCCamera.list_cameras()
        for cam in cameras:
            label = f"Camera {cam['index']} — {cam['resolution']}"
            if cam['index'] == 0:
                label += " (built-in)"
            self.camera_combo.addItem(label, cam['index'])
        # Pre-select saved index
        saved_idx = settings.get("camera_index", 1)
        for i in range(self.camera_combo.count()):
            if self.camera_combo.itemData(i) == saved_idx:
                self.camera_combo.setCurrentIndex(i)
                break
        form.addRow("Camera:", self.camera_combo)

        # Camera rotation toggle
        self.rotate_checkbox = QCheckBox("Rotate 90° clockwise")
        self.rotate_checkbox.setChecked(settings.get("rotate_90_cw", False))
        self.rotate_checkbox.setStyleSheet("QCheckBox { color: #e8e8f5; font-size: 13px; }")
        form.addRow("", self.rotate_checkbox)

        self.card_name_edit = QLineEdit(settings.get("card_name", ""))
        self.card_name_edit.setPlaceholderText("e.g. Sylveon EX")
        form.addRow("Card Name:", self.card_name_edit)

        self.card_set_edit = QLineEdit(settings.get("card_set", ""))
        self.card_set_edit.setPlaceholderText("e.g. Prismatic Evolutions #156/131")
        form.addRow("Set / Number:", self.card_set_edit)

        self.cert_edit = QLineEdit(settings.get("cert", ""))
        self.cert_edit.setPlaceholderText("e.g. C5314038")
        form.addRow("Cert #:", self.cert_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_settings(self) -> dict:
        return {
            "api_key":      self.api_key_edit.text().strip(),
            "camera_index": self.camera_combo.currentData(),
            "rotate_90_cw": self.rotate_checkbox.isChecked(),
            "card_name":    self.card_name_edit.text().strip(),
            "card_set":     self.card_set_edit.text().strip(),
            "cert":         self.cert_edit.text().strip(),
        }


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class GradeWorker(QThread):
    finished = Signal(object)
    error    = Signal(str)

    def __init__(self, image_path: Optional[Path] = None,
                 use_camera: bool = False, camera_index: int = 1,
                 rotate_90_cw: bool = False, api_key: str = ""):
        super().__init__()
        self.image_path   = image_path
        self.use_camera   = use_camera
        self.camera_index = camera_index
        self.rotate_90_cw = rotate_90_cw
        self.api_key      = api_key

    def run(self):
        try:
            if self.api_key:
                os.environ["ANTHROPIC_API_KEY"] = self.api_key
            report = asyncio.run(grade_card(
                image_path=self.image_path,
                use_camera=self.use_camera,
                camera_index=self.camera_index,
                rotate_90_cw=self.rotate_90_cw,
            ))
            self.finished.emit(report)
        except Exception as exc:
            logger.exception("Grading failed")
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Criterion row widget  (TAG-style score + evidence)
# ---------------------------------------------------------------------------

class CriterionRow(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.label = label
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)

        lbl = QLabel(label.upper())
        lbl.setFixedWidth(90)
        lbl.setStyleSheet("color: #7070a0; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        row.addWidget(lbl)

        self.score_badge = QLabel("—")
        self.score_badge.setFixedSize(72, 32)
        self.score_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.score_badge.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        self.score_badge.setStyleSheet("border-radius: 6px; background: #1e1e35; color: #555577;")
        row.addWidget(self.score_badge)

        self.tier_label = QLabel("")
        self.tier_label.setStyleSheet("color: #555577; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        self.tier_label.setFixedWidth(90)
        row.addWidget(self.tier_label)

        self.evidence_label = QLabel("—")
        self.evidence_label.setStyleSheet("color: #505075; font-size: 11px;")
        self.evidence_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(self.evidence_label)

        self.setStyleSheet("CriterionRow { background: #0e0e1a; border-radius: 8px; }")

    def update(self, grade: Optional[float], evidence: dict, error: Optional[str]):
        if error:
            self.score_badge.setText("ERR")
            self.score_badge.setStyleSheet("border-radius: 6px; background: #3a1010; color: #ff4444;")
            self.tier_label.setText("ERROR")
            self.tier_label.setStyleSheet("color: #ff4444; font-size: 10px; font-weight: 700;")
            self.evidence_label.setText(error[:80])
            return

        color = _grade_color(grade)
        self.score_badge.setText(_tag_score(grade))
        self.score_badge.setStyleSheet(
            f"border-radius: 6px; background: {color}22; color: {color}; border: 1px solid {color}55;"
        )
        self.tier_label.setText(_grade_tier(grade))
        self.tier_label.setStyleSheet(
            f"font-size: 10px; font-weight: 700; letter-spacing: 1px; color: {color};"
        )

        # Evidence summary
        ev_parts = []
        for k, v in evidence.items():
            if k in ("vlm_reasoning", "vlm_response", "per_corner", "per_edge", "cv"):
                continue
            if isinstance(v, (int, float)):
                ev_parts.append(f"{k}: {v}")
            elif isinstance(v, str) and len(v) < 30:
                ev_parts.append(f"{k}: {v}")
        self.evidence_label.setText("  ·  ".join(ev_parts[:5]) or "—")


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TCG Grader — TAG Portal Style")
        self.setMinimumSize(1280, 760)
        self._settings = load_settings()
        self._worker: Optional[GradeWorker] = None
        self._loaded_path: Optional[Path] = None
        self._last_report: Optional[GradeReport] = None
        self._preview_cam: Optional[UVCCamera] = None
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._update_preview)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #05050d; color: #e8e8f5; }
            QScrollArea { border: none; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top nav bar ──
        nav = QWidget()
        nav.setFixedHeight(52)
        nav.setStyleSheet("background: #0a0a18; border-bottom: 1px solid #1e1e35;")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(24, 0, 24, 0)

        logo = QLabel("TAG  GRADER")
        logo.setFont(QFont("Arial", 13, QFont.Weight.Black))
        logo.setStyleSheet("color: #a89cff; letter-spacing: 3px;")
        nav_layout.addWidget(logo)

        nav_layout.addStretch()

        self.api_indicator = QLabel("⚠ No API Key")
        self.api_indicator.setStyleSheet("color: #ff6d00; font-size: 11px; font-weight: 700;")
        nav_layout.addWidget(self.api_indicator)

        btn_settings = QPushButton("⚙  Settings")
        btn_settings.setFixedHeight(34)
        btn_settings.setStyleSheet("""
            QPushButton { background: #1e1e35; color: #a89cff; border: 1px solid #3a3060;
                          border-radius: 6px; padding: 0 16px; font-weight: 700; font-size: 12px; }
            QPushButton:hover { background: #2a2a4a; }
        """)
        btn_settings.clicked.connect(self._open_settings)
        nav_layout.addWidget(btn_settings)

        root.addWidget(nav)

        # ── Body ──
        body = QHBoxLayout()
        body.setContentsMargins(20, 20, 20, 20)
        body.setSpacing(20)
        root.addLayout(body)

        # ── Left: image + controls ──
        left = QVBoxLayout()
        left.setSpacing(12)
        body.addLayout(left, 55)

        self.image_label = QLabel("Drop a card image here\nor click Load Image")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setStyleSheet(
            "background: #0e0e1a; border: 2px dashed #1e1e35; "
            "border-radius: 12px; color: #333355; font-size: 15px;"
        )
        left.addWidget(self.image_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_load = self._make_btn("📂  Load Image", "#1e1e35", "#a89cff", "#2a2a4a")
        self.btn_load.clicked.connect(self._load_image)
        btn_row.addWidget(self.btn_load)

        self.btn_camera = self._make_btn("📷  Live Preview", "#1e1e35", "#a89cff", "#2a2a4a")
        self.btn_camera.clicked.connect(self._toggle_preview)
        btn_row.addWidget(self.btn_camera)

        self.btn_grade = self._make_btn("▶  GRADE", "#7c6af7", "#ffffff", "#9d8fff")
        self.btn_grade.setEnabled(False)
        self.btn_grade.clicked.connect(self._start_grading)
        btn_row.addWidget(self.btn_grade)

        self.btn_report = self._make_btn("🌐  View Report", "#1e1e35", "#00e676", "#2a2a4a")
        self.btn_report.setEnabled(False)
        self.btn_report.clicked.connect(self._open_report)
        btn_row.addWidget(self.btn_report)

        left.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(4)
        self.progress.setVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar { background: #1e1e35; border: none; border-radius: 2px; }"
            "QProgressBar::chunk { background: #7c6af7; border-radius: 2px; }"
        )
        left.addWidget(self.progress)

        self.status_label = QLabel("Ready — load an image to begin")
        self.status_label.setStyleSheet("color: #555577; font-size: 11px;")
        left.addWidget(self.status_label)

        # ── Right: results ──
        right = QVBoxLayout()
        right.setSpacing(12)
        body.addLayout(right, 45)

        # Overall score hero
        self.score_hero = QWidget()
        self.score_hero.setFixedHeight(110)
        self.score_hero.setStyleSheet(
            "background: linear-gradient(135deg, #0e0e22, #111a2e);"
            "border: 1px solid #1e1e35; border-radius: 12px;"
        )
        hero_layout = QHBoxLayout(self.score_hero)
        hero_layout.setContentsMargins(24, 16, 24, 16)

        score_col = QVBoxLayout()
        self.overall_score = QLabel("—")
        self.overall_score.setFont(QFont("Arial", 40, QFont.Weight.Black))
        self.overall_score.setStyleSheet("color: #555577;")
        score_col.addWidget(self.overall_score)

        self.overall_tier = QLabel("AWAITING GRADE")
        self.overall_tier.setStyleSheet("color: #333355; font-size: 10px; font-weight: 800; letter-spacing: 2px;")
        score_col.addWidget(self.overall_tier)
        hero_layout.addLayout(score_col)

        hero_layout.addStretch()

        meta_col = QVBoxLayout()
        meta_col.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.card_name_label = QLabel(self._settings.get("card_name", "") or "Card Name")
        self.card_name_label.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self.card_name_label.setStyleSheet("color: #e8e8f5;")
        self.card_name_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        meta_col.addWidget(self.card_name_label)

        self.card_set_label = QLabel(self._settings.get("card_set", "") or "Set / Number")
        self.card_set_label.setStyleSheet("color: #555577; font-size: 11px;")
        self.card_set_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        meta_col.addWidget(self.card_set_label)

        self.cert_label = QLabel(f"Cert #{self._settings.get('cert', '—')}")
        self.cert_label.setStyleSheet("color: #3a3060; font-size: 10px; font-family: monospace;")
        self.cert_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        meta_col.addWidget(self.cert_label)
        hero_layout.addLayout(meta_col)

        right.addWidget(self.score_hero)

        # Criterion rows
        rows_widget = QWidget()
        rows_widget.setStyleSheet("background: #0a0a18; border: 1px solid #1e1e35; border-radius: 10px;")
        rows_layout = QVBoxLayout(rows_widget)
        rows_layout.setContentsMargins(0, 6, 0, 6)
        rows_layout.setSpacing(2)

        self.row_centering = CriterionRow("Centering")
        self.row_corners   = CriterionRow("Corners")
        self.row_edges     = CriterionRow("Edges")
        self.row_surface   = CriterionRow("Surface")
        for r in [self.row_centering, self.row_corners, self.row_edges, self.row_surface]:
            rows_layout.addWidget(r)

        right.addWidget(rows_widget)

        # Save path
        self.save_path_label = QLabel("")
        self.save_path_label.setStyleSheet("color: #2a2a4a; font-size: 10px;")
        self.save_path_label.setWordWrap(True)
        right.addWidget(self.save_path_label)

        right.addStretch()

        # Update API indicator
        self._refresh_api_indicator()

    def _make_btn(self, text: str, bg: str, fg: str, hover: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(38)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: {fg}; border: 1px solid #2a2a45;
                border-radius: 7px; padding: 0 16px;
                font-size: 12px; font-weight: 700;
            }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:disabled {{ background: #111122; color: #333355; border-color: #1a1a2a; }}
        """)
        return btn

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self):
        dlg = SettingsDialog(self._settings, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._settings = dlg.get_settings()
            save_settings(self._settings)
            self._refresh_api_indicator()
            self.card_name_label.setText(self._settings.get("card_name", "") or "Card Name")
            self.card_set_label.setText(self._settings.get("card_set", "") or "Set / Number")
            self.cert_label.setText(f"Cert #{self._settings.get('cert', '—')}")

    def _refresh_api_indicator(self):
        has_key = bool(self._settings.get("api_key") or os.environ.get("ANTHROPIC_API_KEY"))
        if has_key:
            self.api_indicator.setText("✓ API Key set")
            self.api_indicator.setStyleSheet("color: #00e676; font-size: 11px; font-weight: 700;")
        else:
            self.api_indicator.setText("⚠ No API Key")
            self.api_indicator.setStyleSheet("color: #ff6d00; font-size: 11px; font-weight: 700;")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Card Image", str(Path.home()),
            "Images (*.jpg *.jpeg *.png *.tif *.tiff)"
        )
        if not path:
            return
        bgr = cv2.imread(path)
        if bgr is None:
            QMessageBox.critical(self, "Error", f"Cannot load: {path}")
            return
        self._loaded_path = Path(path)
        self._show_image(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        self.btn_grade.setEnabled(True)
        self.status_label.setText(f"Loaded: {Path(path).name}")

    def _scan_camera(self):
        if not self._settings.get("api_key") and not os.environ.get("ANTHROPIC_API_KEY"):
            QMessageBox.warning(self, "API Key Missing",
                                "Set your Anthropic API key in Settings before grading.")
            return
        # Stop live preview before capture so the camera is free
        self._stop_preview()
        self._run_worker(use_camera=True, camera_index=self._settings.get("camera_index", 1))

    def _toggle_preview(self):
        """Start/stop live camera preview."""
        if self._preview_timer.isActive():
            self._stop_preview()
            self.btn_camera.setText("📷  Live Preview")
        else:
            self._start_preview()

    def _start_preview(self):
        idx = self._settings.get("camera_index", 1)
        rotate = self._settings.get("rotate_90_cw", False)
        try:
            self._preview_cam = UVCCamera(camera_index=idx, rotate_90_cw=rotate)
            self._preview_timer.start(100)  # ~10 fps
            self.btn_camera.setText("⏹  Stop Preview")
            self.btn_grade.setEnabled(True)
            self.status_label.setText(f"Live preview — Camera {idx}  |  Click ▶ GRADE to capture and grade")
        except Exception as e:
            QMessageBox.critical(self, "Camera Error", str(e))

    def _stop_preview(self):
        self._preview_timer.stop()
        if self._preview_cam:
            self._preview_cam.close()
            self._preview_cam = None
        self.btn_camera.setText("📷  Live Preview")

    def _update_preview(self):
        if not self._preview_cam:
            return
        frame = self._preview_cam.live_frame()
        if frame is not None:
            self._show_image(frame)

    def _start_grading(self):
        if not self._loaded_path and not self._preview_timer.isActive():
            return
        if not self._settings.get("api_key") and not os.environ.get("ANTHROPIC_API_KEY"):
            QMessageBox.warning(self, "API Key Missing",
                                "Set your Anthropic API key in ⚙ Settings before grading.")
            self._open_settings()
            return
        # If live preview is active, capture from camera
        if self._preview_timer.isActive():
            self._stop_preview()
            self._run_worker(use_camera=True,
                             camera_index=self._settings.get("camera_index", 1))
        else:
            self._run_worker(image_path=self._loaded_path)

    def _run_worker(self, **kwargs):
        self.btn_grade.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.btn_camera.setEnabled(False)
        self.btn_report.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText("Grading… (centering → corners / edges / surface in parallel)")

        api_key = self._settings.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        # Default camera_index and rotate_90_cw from settings if caller didn't supply them
        kwargs.setdefault("camera_index", self._settings.get("camera_index", 1))
        kwargs.setdefault("rotate_90_cw", self._settings.get("rotate_90_cw", False))
        self._worker = GradeWorker(api_key=api_key, **kwargs)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_done(self, report: GradeReport):
        self._last_report = report
        self._enable_buttons()
        self.progress.setVisible(False)
        self._display_report(report)

        # Auto-generate HTML report
        if report.capture_path:
            html_path = report.capture_path / "grade_report.html"
            try:
                generate_html_report(
                    report,
                    card_name=self._settings.get("card_name") or "Pokémon Card",
                    card_set=self._settings.get("card_set") or "",
                    cert=self._settings.get("cert") or "—",
                    output_path=html_path,
                )
                self._html_path = html_path
                self.btn_report.setEnabled(True)
                self.save_path_label.setText(f"Report: {html_path}")
            except Exception as e:
                logger.warning("HTML report generation failed: %s", e)

        tier = _grade_tier(report.overall)
        self.status_label.setText(f"Done — {tier}  ({_tag_score(report.overall)} / 1000)")

    def _on_error(self, msg: str):
        self._enable_buttons()
        self.progress.setVisible(False)
        self.status_label.setText(f"Error: {msg[:80]}")
        QMessageBox.critical(self, "Grading Error", msg)

    def _enable_buttons(self):
        self.btn_grade.setEnabled(bool(self._loaded_path) or self._preview_timer.isActive())
        self.btn_load.setEnabled(True)
        self.btn_camera.setEnabled(True)

    def _open_report(self):
        if hasattr(self, "_html_path") and self._html_path.exists():
            if sys.platform == "darwin":
                subprocess.run(["open", str(self._html_path)])
            elif sys.platform == "win32":
                os.startfile(str(self._html_path))
            else:
                subprocess.run(["xdg-open", str(self._html_path)])

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _show_image(self, rgb: np.ndarray):
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg).scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(pix)

    def _display_report(self, report: GradeReport):
        # Overall hero
        color = _grade_color(report.overall)
        self.overall_score.setText(_tag_score(report.overall))
        self.overall_score.setStyleSheet(f"color: {color}; font-size: 40px;")
        self.overall_tier.setText(_grade_tier(report.overall))
        self.overall_tier.setStyleSheet(
            f"color: {color}; font-size: 10px; font-weight: 800; letter-spacing: 2px;"
        )

        # Criterion rows
        def upd(row: CriterionRow, c):
            if c is None:
                row.update(None, {}, "Not graded")
            else:
                row.update(c.grade, c.evidence, c.error)

        upd(self.row_centering, report.centering)
        upd(self.row_corners,   report.corners)
        upd(self.row_edges,     report.edges)
        upd(self.row_surface,   report.surface)

        # Keep the original captured image in preview (don't replace with rectified)
        # User feedback: preserve the original preview photo after analysis
        # The rectified image is available in the HTML report


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("TCG Grader")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
