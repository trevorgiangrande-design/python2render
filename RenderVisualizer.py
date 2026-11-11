"""Sweep Preview - a VS Code style viewer for camera sweeps around an OBJ.

Run:  python RenderVisualizer.py                    (opens objects\\cup.obj)
      python RenderVisualizer.py objects\\door.obj

Left panel: preset, sweep, angles, culling, distances (several rings at once),
display options, GIF export and "copy settings" (a point_sweep(...) call you can
paste into code). In the 3D view: left-drag to orbit (Z stays up, like Rhino),
right-drag to pan, scroll to move closer, R to reset.

Simulate writes the render CSVs to a temporary folder and plays them back; they are
only copied to render_data when you press "Save render set" (closing asks first).
"""
# 1. Imports ------------------------------------------------------------------
import json
import os
import re
import shutil
import sys
import tempfile

import numpy as np
import pyvista as pv

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QMessageBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

import RenderLocations as L
from RenderPackage import RENDER_DATA_FOLDER, RENDER_TYPES, create_render_set, read_renders

SCRIPTS_FOLDER = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OBJ = os.path.join(SCRIPTS_FOLDER, "objects", "cup.obj")
SCENE_FOLDER = os.path.join(SCRIPTS_FOLDER, "rhino_environments")
PREVIEW_FOLDER = os.path.join(RENDER_DATA_FOLDER, "previews")

# Allowed step sizes - each divides every sweep (180/360) and tilt (90/180) range evenly
LON_STEPS = [5, 10, 15, 20, 30, 45, 60, 90]
LAT_STEPS = [5, 10, 15, 30, 45, 90]
MAX_CULL = 6

# Render simulation
RENDER_TYPE_LABELS = {"default": "Default", "uvw": "UVW", "objectid": "Object ID"}
CAMERA_TO_LIGHT_RATIO = 3        # a camera stays on screen 3x as long as one of its lights
LIGHT_DISPLAY_SCALE = 1.25       # lights are drawn at 1.25x the outer camera ring, not their true distance
DEFAULT_FPS = 12
DEFAULT_FRAMES_PER_LIGHT = 3     # 0.25 s per light at 12 fps - any value from 1 up is allowed
GIF_MAX_WIDTH = 960              # simulation GIFs are recorded at most this wide (keeps files small)
PREVIEW_MAX_SIDE = 400           # the camera preview's longer side, in screen pixels (1024x1024 -> 400x400)
# Render time estimate per image, by render type, until calibrated against real V-Ray renders.
# UVW and Object ID are flat passes with lights off, so they render faster than the lit default.
SECONDS_PER_RENDER = {"default": 20, "uvw": 10, "objectid": 10}
DEFAULT_SECONDS_PER_RENDER = 20  # used for any render type not listed above

# Labels on the simulation dots (C with a subscript camera number, L with a subscript light number).
# VTK's built-in font has no subscript digits, so Windows' Segoe UI is used when it is available.
LABEL_FONT_FILE = next((f for f in (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf")
                        if os.path.exists(f)), None)
LABEL_FONT_SIZE = 11
CAMERA_LABEL_LIFT = 2.5          # labels sit this many marker radii above their dot
LIGHT_LABEL_LIFT = 3.5           # (lights use bigger markers)
VTK_FONT_FILE = 4                # VTK's "use this font file" family id
SUBSCRIPT_DIGITS = str.maketrans("0123456789-", "₀₁₂₃₄₅₆₇₈₉₋")

DIRECTIONS = ["south", "west", "north", "east"]
SWEEPS = ["full", "front", "back", "left", "right"]
TILTS = ["above", "full", "below"]
UNIT_ABBREVIATIONS = {"Millimeters": "mm", "Centimeters": "cm", "Meters": "m", "Inches": "in", "Feet": "ft"}


# 2. DESIGN TOKENS --------------------------------------------------------------
# Layout follows the skill's 4px grid. Colours are VS Code's Dark+ / Light+ themes,
# as requested, in place of the skill's default corporate palette.
FONT_BODY = "Segoe UI"      # VS Code's UI font on Windows
FONT_MONO = "Consolas"

SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 16
SPACING_LG = 24

RADIUS_SM = 2
RADIUS_DEFAULT = 4

TYPO_BODY = 13
TYPO_LABEL = 11

SIDEBAR_WIDTH = 288
FIELD_LABEL_WIDTH = 64
VALUE_LABEL_WIDTH = 32
CONTROL_HEIGHT = 24

THEMES = {
    "Dark+": {
        "BG_EDITOR": "#1e1e1e", "BG_SIDEBAR": "#252526", "BG_TABBAR": "#252526", "BG_TAB_ACTIVE": "#1e1e1e",
        "BG_INPUT": "#3c3c3c", "BG_DROPDOWN": "#3c3c3c", "BG_HOVER": "#2a2d2e", "BG_SELECTED": "#04395e",
        "BG_TOOLTIP": "#252526",
        "BORDER": "#3c3c3c", "BORDER_INPUT": "#3c3c3c", "BORDER_HOVER": "#5a5a5a", "FOCUS": "#007fd4",
        "ACCENT": "#0e639c", "ACCENT_HOVER": "#1177bb", "ACCENT_PRESSED": "#0b5181", "SLIDER": "#007acc",
        "BUTTON2": "#3a3d41", "BUTTON2_HOVER": "#45494e", "BUTTON2_PRESSED": "#303235",
        "FG": "#cccccc", "FG_MUTED": "#9d9d9d", "FG_HEADER": "#bbbbbb", "FG_ON_ACCENT": "#ffffff",
        "FG_SELECTED": "#ffffff", "FG_DISABLED": "#6b6b6b",
        "GROOVE": "#4a4a4a", "SCROLL": "rgba(121, 121, 121, 0.4)", "SCROLL_HOVER": "rgba(100, 100, 100, 0.7)",
        "STATUS_BG": "#007acc", "STATUS_FG": "#ffffff", "ERROR": "#f48771",
        "VIEW_BG": "#1e1e1e", "MESH": "#c8c8c8", "LINES": "#6b6b6b",
        "RINGS": ["#4fc1ff", "#c586c0", "#dcdcaa", "#ce9178", "#4ec9b0", "#f44747"],
        "SIM_CAMERA": "#3794ff", "SIM_LIGHT": "#ffcc00", "SIM_LIGHT_DIM": "#6b5a1e", "SIM_GHOST": "#4a4a4a",
    },
    "Light+": {
        "BG_EDITOR": "#ffffff", "BG_SIDEBAR": "#f3f3f3", "BG_TABBAR": "#f3f3f3", "BG_TAB_ACTIVE": "#ffffff",
        "BG_INPUT": "#ffffff", "BG_DROPDOWN": "#ffffff", "BG_HOVER": "#e8e8e8", "BG_SELECTED": "#d6ebff",
        "BG_TOOLTIP": "#f3f3f3",
        "BORDER": "#e5e5e5", "BORDER_INPUT": "#cecece", "BORDER_HOVER": "#a6a6a6", "FOCUS": "#0090f1",
        "ACCENT": "#007acc", "ACCENT_HOVER": "#0062a3", "ACCENT_PRESSED": "#005089", "SLIDER": "#007acc",
        "BUTTON2": "#e4e4e4", "BUTTON2_HOVER": "#d4d4d4", "BUTTON2_PRESSED": "#c8c8c8",
        "FG": "#3b3b3b", "FG_MUTED": "#717171", "FG_HEADER": "#616161", "FG_ON_ACCENT": "#ffffff",
        "FG_SELECTED": "#3b3b3b", "FG_DISABLED": "#a0a0a0",
        "GROOVE": "#c8c8c8", "SCROLL": "rgba(100, 100, 100, 0.4)", "SCROLL_HOVER": "rgba(100, 100, 100, 0.7)",
        "STATUS_BG": "#007acc", "STATUS_FG": "#ffffff", "ERROR": "#a1260d",
        "VIEW_BG": "#ffffff", "MESH": "#9a9a9a", "LINES": "#b4b4b4",
        "RINGS": ["#0070c1", "#af00db", "#795e26", "#a31515", "#267f99", "#cd3131"],
        "SIM_CAMERA": "#0066b8", "SIM_LIGHT": "#bf8803", "SIM_LIGHT_DIM": "#e6d49b", "SIM_GHOST": "#d0d0d0",
    },
}


# 3. QSS THEME --------------------------------------------------------------------
ICON_SVGS = {
    "down": '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
            '<path d="M4 6l4 4 4-4" fill="none" stroke="{c}" stroke-width="1.5"/></svg>',
    "up": '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
          '<path d="M4 10l4-4 4 4" fill="none" stroke="{c}" stroke-width="1.5"/></svg>',
    "check": '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
             '<path d="M3.5 8.5l3 3 6-7" fill="none" stroke="{c}" stroke-width="1.8"/></svg>',
}


def theme_icons(theme_name, t):
    """Write the small chevron / check icons for a theme and return their paths for QSS."""
    folder = os.path.join(tempfile.gettempdir(), "sweep_preview_icons")
    os.makedirs(folder, exist_ok=True)
    colors = {"down": t["FG"], "up": t["FG"], "check": t["FG_ON_ACCENT"]}
    paths = {}
    for name, svg in ICON_SVGS.items():
        path = os.path.join(folder, f"{name}_{theme_name.strip('+').lower()}.svg")
        with open(path, "w") as f:
            f.write(svg.format(c=colors[name]))
        paths[name] = path.replace("\\", "/")
    return paths


def build_qss(t, icons):
    return f"""
QWidget {{
    font-family: '{FONT_BODY}';
    font-size: {TYPO_BODY}px;
    color: {t['FG']};
}}
QMainWindow, #Editor {{ background: {t['BG_EDITOR']}; }}

/* ─── Sidebar ─────────────────────────────────────── */
#Sidebar {{
    background: {t['BG_SIDEBAR']};
    border-right: 1px solid {t['BORDER']};
}}
#SidebarTitle {{
    color: {t['FG_HEADER']};
    font-size: {TYPO_LABEL}px;
    padding: {SPACING_SM}px {SPACING_MD + SPACING_XS}px;
}}
QScrollArea, #SidebarBody {{ background: transparent; border: none; }}

QPushButton[class="section"] {{
    background: transparent;
    color: {t['FG_HEADER']};
    border: none;
    border-top: 1px solid {t['BORDER']};
    border-radius: 0px;
    font-size: {TYPO_LABEL}px;
    font-weight: 700;
    text-align: left;
    padding: {SPACING_XS}px {SPACING_SM}px;
}}
QPushButton[class="section"]:hover {{ background: {t['BG_HOVER']}; }}
QPushButton[class="section"]:pressed {{ background: {t['BG_HOVER']}; }}
QPushButton[class="section"]:focus {{ border: 1px solid {t['FOCUS']}; }}

QLabel[class="field"] {{ color: {t['FG_MUTED']}; font-size: {TYPO_LABEL}px; }}
QLabel[class="value"] {{ color: {t['FG']}; font-family: '{FONT_MONO}'; font-size: {TYPO_LABEL}px; }}
QLabel[class="error"] {{ color: {t['ERROR']}; font-size: {TYPO_LABEL}px; }}

/* ─── Inputs ──────────────────────────────────────── */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {t['BG_INPUT']};
    border: 1px solid {t['BORDER_INPUT']};
    border-radius: {RADIUS_SM}px;
    padding: 0px {SPACING_SM}px;
    min-height: {CONTROL_HEIGHT - 2}px;
    selection-background-color: {t['BG_SELECTED']};
    selection-color: {t['FG_SELECTED']};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {t['BORDER_HOVER']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {t['FOCUS']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {t['FG_DISABLED']}; }}
QComboBox::drop-down {{ border: none; width: {SPACING_MD + SPACING_XS}px; }}
QComboBox::down-arrow {{ image: url({icons['down']}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {t['BG_DROPDOWN']};
    border: 1px solid {t['FOCUS']};
    selection-background-color: {t['BG_SELECTED']};
    selection-color: {t['FG_SELECTED']};
    outline: none;
    padding: 0px;
}}
QComboBox QAbstractItemView::item {{ min-height: {CONTROL_HEIGHT - 4}px; padding: 0px {SPACING_SM}px; }}
QComboBox QAbstractItemView::item:hover {{ background: {t['BG_HOVER']}; }}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: {SPACING_MD}px;
    border: none;
    background: transparent;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {t['BG_HOVER']}; }}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{ background: {t['BORDER_HOVER']}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({icons['up']}); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({icons['down']}); width: 10px; height: 10px; }}

/* ─── Sliders (slim) ──────────────────────────────── */
QSlider {{ min-height: {CONTROL_HEIGHT - 8}px; }}
QSlider::groove:horizontal {{ height: 2px; background: {t['GROOVE']}; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {t['SLIDER']}; border-radius: 1px; }}
QSlider::handle:horizontal {{
    width: 10px; height: 10px;
    margin: -4px 0px;
    border-radius: 5px;
    background: {t['FG']};
}}
QSlider::handle:horizontal:hover {{ background: {t['FOCUS']}; }}
QSlider::handle:horizontal:pressed {{ background: {t['SLIDER']}; }}
QSlider:focus {{ outline: none; }}
QSlider::handle:horizontal:focus {{ background: {t['FOCUS']}; }}
QSlider::handle:horizontal:disabled {{ background: {t['FG_DISABLED']}; }}

/* ─── Buttons ─────────────────────────────────────── */
QPushButton {{
    background: {t['ACCENT']};
    color: {t['FG_ON_ACCENT']};
    border: 1px solid transparent;
    border-radius: {RADIUS_SM}px;
    padding: {SPACING_XS}px {SPACING_SM + SPACING_XS}px;
    min-height: {CONTROL_HEIGHT - 2 * SPACING_XS - 2}px;
}}
QPushButton:hover {{ background: {t['ACCENT_HOVER']}; }}
QPushButton:pressed {{ background: {t['ACCENT_PRESSED']}; }}
QPushButton:focus {{ border-color: {t['FOCUS']}; }}
QPushButton:disabled {{ background: {t['BUTTON2']}; color: {t['FG_DISABLED']}; }}
QPushButton[class="secondary"] {{ background: {t['BUTTON2']}; color: {t['FG']}; }}
QPushButton[class="secondary"]:hover {{ background: {t['BUTTON2_HOVER']}; }}
QPushButton[class="secondary"]:pressed {{ background: {t['BUTTON2_PRESSED']}; }}

/* ─── Checkboxes ──────────────────────────────────── */
QCheckBox {{ spacing: {SPACING_SM}px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {t['BORDER_INPUT']};
    border-radius: {RADIUS_SM + 1}px;
    background: {t['BG_INPUT']};
}}
QCheckBox::indicator:hover {{ border-color: {t['BORDER_HOVER']}; }}
QCheckBox:focus {{ outline: none; }}
QCheckBox::indicator:focus {{ border-color: {t['FOCUS']}; }}
QCheckBox::indicator:checked {{
    background: {t['ACCENT']};
    border-color: {t['ACCENT']};
    image: url({icons['check']});
}}
QCheckBox::indicator:checked:hover {{ background: {t['ACCENT_HOVER']}; }}
QCheckBox:disabled {{ color: {t['FG_DISABLED']}; }}

/* ─── List ────────────────────────────────────────── */
QListWidget {{
    background: {t['BG_INPUT']};
    border: 1px solid {t['BORDER_INPUT']};
    border-radius: {RADIUS_SM}px;
    outline: none;
    font-family: '{FONT_MONO}';
    font-size: {TYPO_LABEL + 1}px;
}}
QListWidget:focus {{ border-color: {t['FOCUS']}; }}
QListWidget::item {{ padding: 2px {SPACING_SM}px; }}
QListWidget::item:hover {{ background: {t['BG_HOVER']}; }}
QListWidget::item:selected {{ background: {t['BG_SELECTED']}; }}

/* ─── Scrollbars (VS Code style overlay) ──────────── */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0px; }}
QScrollBar::handle:vertical {{ background: {t['SCROLL']}; min-height: {SPACING_LG}px; }}
QScrollBar::handle:vertical:hover {{ background: {t['SCROLL_HOVER']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

/* ─── Editor tab bar ──────────────────────────────── */
#TabBar {{ background: {t['BG_TABBAR']}; border-bottom: 1px solid {t['BORDER']}; }}
#Tab {{
    background: {t['BG_TAB_ACTIVE']};
    color: {t['FG']};
    border-top: 1px solid {t['ACCENT']};
    border-right: 1px solid {t['BORDER']};
    padding: {SPACING_SM}px {SPACING_MD}px;
}}

/* ─── Status bar ──────────────────────────────────── */
/* ─── Camera preview (top right of the 3D view) ───── */
#CameraPreview {{
    background: {t['BG_SIDEBAR']};
    border: 1px solid {t['BORDER_INPUT']};
    border-radius: {RADIUS_DEFAULT}px;
}}
#PreviewTitle {{ color: {t['FG']}; font-family: '{FONT_MONO}'; font-size: {TYPO_LABEL + 1}px; }}
#PreviewDetail {{ color: {t['FG_MUTED']}; font-size: {TYPO_LABEL}px; }}

#StatusBar {{ background: {t['STATUS_BG']}; }}
#StatusBar QLabel {{ color: {t['STATUS_FG']}; font-size: {TYPO_LABEL + 1}px; padding: 0px {SPACING_SM}px; }}

QToolTip {{
    background: {t['BG_TOOLTIP']};
    color: {t['FG']};
    border: 1px solid {t['BORDER_INPUT']};
    padding: {SPACING_XS}px;
}}
"""


# 4. WIDGETS ----------------------------------------------------------------------
def field_label(text):
    label = QLabel(text)
    label.setProperty("class", "field")
    label.setFixedWidth(FIELD_LABEL_WIDTH)
    return label


def fit_to_panel(widget):
    """Let a control shrink to the sidebar's width instead of asking for its natural width."""
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    widget.setMinimumWidth(0)
    return widget


def row(label_text, widget):
    if isinstance(widget, (QComboBox, QSpinBox, QDoubleSpinBox)):
        fit_to_panel(widget)
    line = QHBoxLayout()
    line.setContentsMargins(0, 0, 0, 0)
    line.setSpacing(SPACING_SM)
    line.addWidget(field_label(label_text))
    line.addWidget(widget, 1)
    return line


class Section(QWidget):
    """A collapsible VS Code style sidebar section: an uppercase header and a body."""

    def __init__(self, title):
        super().__init__()
        self.title = title.upper()
        self.header = QPushButton()
        self.header.setProperty("class", "section")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.clicked.connect(self.toggle)
        self.body = QWidget()
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(SPACING_MD, SPACING_XS, SPACING_MD, SPACING_SM + SPACING_XS)
        self.content.setSpacing(SPACING_SM - 2)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.header)
        outer.addWidget(self.body)
        self.set_open(True)

    def set_open(self, is_open):
        self.body.setVisible(is_open)
        self.header.setText(("▾  " if is_open else "▸  ") + self.title)

    def toggle(self):
        self.set_open(not self.body.isVisible())

    def add_row(self, label_text, widget):
        self.content.addLayout(row(label_text, widget))

    def add(self, widget_or_layout):
        if isinstance(widget_or_layout, QWidget):
            self.content.addWidget(widget_or_layout)
        else:
            self.content.addLayout(widget_or_layout)


class StepSlider(QWidget):
    """A slim slider that only lands on allowed values, with the value shown on the right."""

    valueChanged = pyqtSignal(int)

    def __init__(self, choices, value, suffix="°"):
        super().__init__()
        self.choices = choices
        self.suffix = suffix
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(choices) - 1)
        self.slider.setPageStep(1)
        self.value_label = QLabel()
        self.value_label.setProperty("class", "value")
        self.value_label.setFixedWidth(VALUE_LABEL_WIDTH)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(SPACING_SM)
        line.addWidget(self.slider, 1)
        line.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._changed)
        self.setValue(value)

    def value(self):
        return self.choices[self.slider.value()]

    def setValue(self, value):
        nearest = min(range(len(self.choices)), key=lambda i: abs(self.choices[i] - value))
        self.slider.setValue(nearest)
        self.value_label.setText(f"{self.value()}{self.suffix}")

    def _changed(self, _index):
        self.value_label.setText(f"{self.value()}{self.suffix}")
        self.valueChanged.emit(self.value())


class SweepView(QLabel):
    """The 3D viewport.

    PyVista renders off-screen and the picture is shown as an ordinary Qt image.
    (VTK's own Qt viewport widget crashes with this VTK 9.7 / PyQt6 6.12 install.)

    Navigation works like Rhino's perspective view: left-drag turns around the
    vertical (Z) axis and raises/lowers the view, but Z always stays straight up -
    the view never tilts or rolls. Right- or middle-drag pans, the wheel moves the
    camera closer or further, R resets.
    """

    ORBIT_DEGREES_PER_PIXEL = 0.4
    ZOOM_PER_WHEEL_STEP = 1.1
    MAX_ELEVATION = 85.0               # stop short of straight overhead/underneath - past ~87.4°
                                       # VTK silently replaces the up direction (the view would roll)
    WORLD_UP = np.array([0.0, 0.0, 1.0])

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.plotter = pv.Plotter(off_screen=True, window_size=(800, 600))
        self.plotter.add_axes()
        self.names = set()
        self.ready = False              # nothing is drawn until the window is on screen
        self._drag = None

    def start(self):
        """Call once, after the main window has been shown."""
        self.ready = True
        self.reset_view()

    # ---- scene ----

    def set_actor(self, name, polydata, color, opacity=1.0):
        self.plotter.add_mesh(polydata, color=color, opacity=opacity, name=name, reset_camera=False)
        self.names.add(name)

    def set_label_actor(self, name, actor):
        self.plotter.add_actor(actor, name=name, reset_camera=False, render=False)
        self.names.add(name)

    def remove_actor(self, name):
        if name in self.names:
            self.plotter.remove_actor(name, render=False)
            self.names.discard(name)

    def remove_matching(self, prefix):
        for name in [n for n in self.names if n.startswith(prefix)]:
            self.remove_actor(name)

    def set_background(self, color):
        self.plotter.set_background(color)

    def reset_view(self):
        self.plotter.camera_position = [(1, -1.4, 0.9), (0, 0, 0), (0, 0, 1)]
        self.plotter.reset_camera()
        self.refresh()

    def camera_position(self):
        return self.plotter.camera_position

    def refresh(self):
        if not self.ready or self.width() < 2 or self.height() < 2:
            return
        ratio = self.devicePixelRatioF()
        size = [max(2, round(self.width() * ratio)), max(2, round(self.height() * ratio))]
        if list(self.plotter.window_size) != size:
            self.plotter.window_size = size
        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.render()           # camera moves don't trigger a render by themselves
        image = np.ascontiguousarray(self.plotter.screenshot(return_img=True)[:, :, :3])
        height, width, _ = image.shape
        qimage = QImage(image.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimage)
        pixmap.setDevicePixelRatio(ratio)
        self.setPixmap(pixmap)

    def close_plotter(self):
        self.plotter.close()

    # ---- mouse and keyboard ----

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()
        self.place_overlay()

    def place_overlay(self):
        """Keep the camera preview pinned to the top-right corner."""
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            overlay.move(self.width() - overlay.width() - SPACING_MD, SPACING_MD)

    def mousePressEvent(self, event):
        self._drag = (event.position(), event.button())
        self.setFocus()

    def mouseReleaseEvent(self, event):
        self._drag = None

    def mouseMoveEvent(self, event):
        if not self._drag:
            return
        start, button = self._drag
        dx = event.position().x() - start.x()
        dy = event.position().y() - start.y()
        self._drag = (event.position(), button)
        if button == Qt.MouseButton.LeftButton:
            self.orbit(dx, dy)
        else:
            self.pan(dx, dy)
        self.refresh()

    def orbit(self, dx, dy):
        """Turntable orbit: spin around the vertical axis through the focal point, raise or
        lower the view, and keep world Z pointing straight up on screen."""
        camera = self.plotter.camera
        focal = np.array(camera.GetFocalPoint())
        offset = np.array(camera.GetPosition()) - focal
        distance = np.linalg.norm(offset)
        azimuth = np.degrees(np.arctan2(offset[1], offset[0])) - dx * self.ORBIT_DEGREES_PER_PIXEL
        elevation = np.degrees(np.arcsin(np.clip(offset[2] / distance, -1, 1))) + dy * self.ORBIT_DEGREES_PER_PIXEL
        elevation = np.clip(elevation, -self.MAX_ELEVATION, self.MAX_ELEVATION)
        a, e = np.radians(azimuth), np.radians(elevation)
        offset = distance * np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
        camera.SetPosition(*(focal + offset))
        camera.SetViewUp(*self.WORLD_UP)

    def screen_axes(self):
        """The camera's right and up directions, with up kept as close to world Z as possible."""
        camera = self.plotter.camera
        forward = np.array(camera.GetFocalPoint()) - np.array(camera.GetPosition())
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, self.WORLD_UP)
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        return right, up

    def pan(self, dx, dy):
        camera = self.plotter.camera
        position = np.array(camera.GetPosition())
        focal = np.array(camera.GetFocalPoint())
        distance = np.linalg.norm(focal - position)
        right, up = self.screen_axes()
        scale = 2 * distance * np.tan(np.radians(camera.GetViewAngle() / 2)) / max(self.height(), 1)
        shift = (-dx * right + dy * up) * scale
        camera.SetPosition(*(position + shift))
        camera.SetFocalPoint(*(focal + shift))

    def wheelEvent(self, event):
        # move the camera closer/further (like Rhino) rather than narrowing the lens
        steps = event.angleDelta().y() / 120
        self.plotter.camera.Dolly(self.ZOOM_PER_WHEEL_STEP ** steps)
        self.refresh()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_R:
            self.reset_view()
        else:
            super().keyPressEvent(event)


class CameraPreview(QFrame):
    """Top-right inset: what the active camera will see.

    Uses the render list's own camera position, target, FOV and output size, and lights
    the object from the active light's direction (or a headlight when no light is on).
    """

    def __init__(self, view):
        super().__init__(view)
        self.setObjectName("CameraPreview")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_SM, SPACING_SM, SPACING_SM, SPACING_SM)
        layout.setSpacing(SPACING_XS)
        self.title = QLabel(objectName="PreviewTitle")      # the output file name
        self.detail = QLabel(objectName="PreviewDetail")    # size, FOV, camera
        self.image = QLabel()
        layout.addWidget(self.title)
        layout.addWidget(self.detail)
        layout.addWidget(self.image)
        self.plotter = pv.Plotter(off_screen=True, window_size=(PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE))
        view.overlay = self
        self.hide()

    def set_scene(self, mesh, t):
        self.plotter.set_background(t["VIEW_BG"])
        self.plotter.add_mesh(mesh, color=t["MESH"], name="mesh", reset_camera=False)

    def preview_size(self, dimensions):
        """Fit the render's width x height inside PREVIEW_MAX_SIDE (smaller if the 3D view is small)."""
        width, height = dimensions
        view = self.parentWidget()
        longest = min(PREVIEW_MAX_SIDE, view.width() * 0.45, view.height() * 0.7)
        scale = longest / max(width, height)
        return max(1, round(width * scale)), max(1, round(height * scale))

    def show_camera(self, camera, light_index):
        width, height = self.preview_size(camera["dimensions"])
        ratio = self.devicePixelRatioF()
        self.plotter.window_size = [round(width * ratio), round(height * ratio)]

        position = np.array(camera["camera"], dtype=float)
        target = np.array(camera["target"], dtype=float)
        direction = (target - position) / np.linalg.norm(target - position)
        up = (0, 0, 1) if abs(direction[2]) < 0.999 else (0, 1, 0)   # straight down: any up will do
        self.plotter.camera_position = [tuple(position), tuple(target), up]
        # V-Ray's FOV is horizontal; VTK wants the vertical angle
        vertical = np.degrees(2 * np.arctan(np.tan(np.radians(camera["fov"]) / 2) * camera["dimensions"][1]
                                            / camera["dimensions"][0]))
        self.plotter.camera.view_angle = vertical

        self.plotter.remove_all_lights()
        if light_index is None:
            self.plotter.add_light(pv.Light(light_type="headlight"))
        else:
            self.plotter.add_light(pv.Light(position=camera["lights"][light_index], focal_point=tuple(target),
                                            light_type="scene light"))
            self.plotter.add_light(pv.Light(light_type="headlight", intensity=0.15))   # faint fill so shadows aren't black

        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.render()
        image = np.ascontiguousarray(self.plotter.screenshot(return_img=True)[:, :, :3])
        h, w, _ = image.shape
        pixmap = QPixmap.fromImage(QImage(image.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy())
        pixmap.setDevicePixelRatio(ratio)
        self.image.setPixmap(pixmap)
        self.image.setFixedSize(width, height)

        if light_index is None or light_index >= len(camera["images"]):
            self.title.setText(f"{camera['name']}  (camera only)")
        else:
            self.title.setText(camera["images"][light_index])
        w_px, h_px = camera["dimensions"]
        self.detail.setText(f"{w_px} × {h_px} px  ·  FOV {camera['fov']:g}°  ·  {camera['name']}")
        self.adjustSize()
        self.show()
        self.raise_()
        self.parentWidget().place_overlay()

    def close_plotter(self):
        self.plotter.close()


# ---- geometry helpers (shared by the viewport and the GIF recorder) ----

def load_mesh(path, y_up):
    mesh = pv.read(path)
    if y_up:
        mesh = mesh.rotate_x(90, point=(0, 0, 0))   # Rhino "Map Z to OBJ Y" -> back to Z-up
    return mesh


def camera_markers(points, marker_radius):
    sphere = pv.Sphere(radius=marker_radius, theta_resolution=12, phi_resolution=12)
    return pv.PolyData(np.array(points, dtype=float)).glyph(geom=sphere, scale=False, orient=False)


def lines_to_centre(points):
    vertices = np.array(list(points) + [(0.0, 0.0, 0.0)], dtype=float)
    centre = len(points)
    lines = np.array([[2, i, centre] for i in range(len(points))]).ravel()
    return pv.PolyData(vertices, lines=lines)


def simulation_schedule(light_counts, frames_per_light, ratio=CAMERA_TO_LIGHT_RATIO):
    """The playback order: one (camera index, light index) pair per frame.

    Each light is lit for frames_per_light frames, one after another, and a camera
    stays on screen for ratio x frames_per_light frames. With the default 3 lights
    the lights exactly fill the camera's time. A camera with fewer lights is shown
    alone (light index None) for the remaining frames; a camera with more lights
    stays on screen until its last light has played.
    """
    frames = []
    for camera, light_count in enumerate(light_counts):
        camera_frames = max(ratio * frames_per_light, light_count * frames_per_light)
        for frame in range(camera_frames):
            light = frame // frames_per_light
            frames.append((camera, light if light < light_count else None))
    return frames


def subscript_label(letter, number):
    """'C', 12 -> 'C₁₂' (or 'C12' if no font with subscript digits was found)."""
    return f"{letter}{str(number).translate(SUBSCRIPT_DIGITS) if LABEL_FONT_FILE else number}"


def point_labels(points, labels, color, font_size, lift=0.0):
    """Text centred just above each point (raised by `lift` along Z, which always points up on
    screen), drawn on top of everything so markers never hide it."""
    from vtkmodules.vtkCommonCore import vtkStringArray
    from vtkmodules.vtkRenderingCore import vtkActor2D
    from vtkmodules.vtkRenderingLabel import vtkLabeledDataMapper

    data = pv.PolyData(np.array(points, dtype=float) + np.array([0.0, 0.0, lift]))
    names = vtkStringArray()
    names.SetName("labels")
    for label in labels:
        names.InsertNextValue(label)
    data.GetPointData().AddArray(names)

    mapper = vtkLabeledDataMapper()
    mapper.SetInputData(data)
    mapper.SetLabelModeToLabelFieldData()
    mapper.SetFieldDataName("labels")
    text = mapper.GetLabelTextProperty()
    text.SetFontSize(font_size)
    text.SetColor(*[int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)])
    text.SetShadow(False)
    text.SetBold(False)
    text.SetItalic(False)
    text.SetJustificationToCentered()
    text.SetVerticalJustificationToBottom()
    if LABEL_FONT_FILE:
        text.SetFontFamily(VTK_FONT_FILE)
        text.SetFontFile(LABEL_FONT_FILE)
    actor = vtkActor2D()
    actor.SetMapper(mapper)
    actor._label_source = data            # keep the labelled points alive with the actor
    return actor


_IMAGES_PER_CAMERA = {}


def images_per_camera(render_type):
    """How many images one camera produces for a render type (default = one per light condition),
    read from RenderPackage itself so it stays right if those defaults change."""
    if render_type not in _IMAGES_PER_CAMERA:
        sample = RENDER_TYPES[render_type]("Camera0", (1.0, 1.0, 1.0))
        _IMAGES_PER_CAMERA[render_type] = len(sample.output.name_list())
    return _IMAGES_PER_CAMERA[render_type]


def format_duration(seconds):
    minutes, _ = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days} d {hours} h {minutes} min"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min" if minutes else f"{round(seconds)} s"


def compress_schedule(frames):
    """Merge runs of identical frames: [((camera, light), number_of_frames), ...]."""
    runs = []
    for key in frames:
        if runs and runs[-1][0] == key:
            runs[-1][1] += 1
        else:
            runs.append([key, 1])
    return [(key, count) for key, count in runs]


def draw_sim_state(add, remove, camera, light_index, t, marker_radius):
    """Draw one moment of the simulation: the active camera, its lights, and the lit light.
    `add(name, mesh, color)` / `remove(name)` let the window and the GIF recorder share this."""
    add("sim_camera", camera_markers([camera["camera"]], marker_radius * 1.8), t["SIM_CAMERA"])
    add("sim_camera_line", lines_to_centre([camera["camera"]]), t["SIM_CAMERA"])
    if camera["lights"]:
        add("sim_lights", camera_markers(camera["lights"], marker_radius * 1.4), t["SIM_LIGHT_DIM"])
    if light_index is None:
        remove("sim_light")
        remove("sim_light_line")
    else:
        light = camera["lights"][light_index]
        add("sim_light", camera_markers([light], marker_radius * 2.2), t["SIM_LIGHT"])
        add("sim_light_line", lines_to_centre([light]), t["SIM_LIGHT"])


def read_scene_info(obj_path):
    """<name>_scene.json from RhinoSceneInfo - next to the .obj (where the .3dm usually is),
    else the old scripts\\rhino_environments folder. None if there isn't one."""
    name = os.path.splitext(os.path.basename(obj_path))[0]
    for folder in (os.path.dirname(os.path.abspath(obj_path)), SCENE_FOLDER):
        path = os.path.join(folder, f"{name}_scene.json")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    return None


# 5. MAIN WINDOW --------------------------------------------------------------------
class SweepPreview(QMainWindow):

    def __init__(self, obj_path):
        super().__init__()
        self.setWindowTitle("Sweep Preview")
        self.resize(1280, 800)
        self._applying = False          # True while the code itself is setting controls
        self.theme_name = "Dark+"
        self.y_up = True
        self.rings = []                 # [(distance, points), ...] from the last redraw
        self.simulating = False         # True while a render list is being played back
        self.sim_cameras = []           # one dict per camera row of the render list
        self.sim_frames = []            # (camera index, light index) per frame
        self.sim_index = 0
        self.sim_last = None
        self.last_default_csv = None
        self.temp_folder = None         # simulated render sets live here until saved
        self.temp_paths = {}            # render type -> temporary CSV path
        self.unsaved = False            # True when the latest simulated set hasn't been saved
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)   # the default rounds to ~16 ms steps on Windows
        self.timer.timeout.connect(self.sim_step)

        self.view = SweepView()
        self.preview = CameraPreview(self.view)
        self._build_ui()
        self.load_object(obj_path)

    # ---- layout -----------------------------------------------------------------

    def _build_ui(self):
        sidebar = QFrame(objectName="Sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(0)
        side_layout.addWidget(QLabel("SWEEP PREVIEW", objectName="SidebarTitle"))

        body = QWidget(objectName="SidebarBody")
        self.sections = QVBoxLayout(body)
        self.sections.setContentsMargins(0, 0, 0, 0)
        self.sections.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        side_layout.addWidget(scroll, 1)

        self._build_object_section()
        self._build_sweep_section()
        self._build_angle_section()
        self._build_distance_section()
        self._build_render_section()
        self._build_simulate_section()
        self._build_display_section()
        self._build_export_section()
        self.sections.addStretch(1)

        tab_bar = QFrame(objectName="TabBar")
        tab_layout = QHBoxLayout(tab_bar)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)
        self.tab = QLabel(objectName="Tab")
        tab_layout.addWidget(self.tab)
        tab_layout.addStretch(1)

        editor = QWidget(objectName="Editor")
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)
        editor_layout.addWidget(tab_bar)
        editor_layout.addWidget(self.view, 1)

        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(sidebar)
        main_layout.addWidget(editor, 1)

        status = QFrame(objectName="StatusBar")
        status.setFixedHeight(SPACING_LG - 2)
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(SPACING_XS, 0, SPACING_XS, 0)
        status_layout.setSpacing(0)
        self.status_message = QLabel()
        self.status_units = QLabel()
        self.status_count = QLabel()
        status_layout.addWidget(self.status_message, 1)
        status_layout.addWidget(self.status_units)
        status_layout.addWidget(self.status_count)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(main, 1)
        root_layout.addWidget(status)
        self.setCentralWidget(root)

    def _add_section(self, title):
        section = Section(title)
        self.sections.addWidget(section)
        return section

    def _combo(self, values, labels=None):
        combo = QComboBox()
        for value, label in zip(values, labels or [v.title() for v in values]):
            combo.addItem(label, value)
        combo.currentIndexChanged.connect(self.on_control_changed)
        return combo

    def _spin(self, maximum):
        spin = QSpinBox()
        spin.setRange(0, maximum)
        spin.valueChanged.connect(self.on_control_changed)
        return spin

    def _button(self, text, handler, secondary=False):
        button = QPushButton(text)
        if secondary:
            button.setProperty("class", "secondary")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(handler)
        return button

    def _build_object_section(self):
        section = self._add_section("Object")
        self.object_label = QLabel()
        self.object_label.setProperty("class", "value")
        section.add_row("File", self.object_label)
        self.y_up_box = QCheckBox("OBJ is Y-up (Rhino export)")
        self.y_up_box.setChecked(self.y_up)
        self.y_up_box.toggled.connect(self.on_y_up_changed)
        section.add(self.y_up_box)
        section.add(self._button("Open OBJ…", self.on_open_obj, secondary=True))

    def _build_sweep_section(self):
        section = self._add_section("Sweep")
        presets = list(L.SWEEP_PRESETS) + ["custom"]
        self.preset_combo = QComboBox()
        for name in presets:
            self.preset_combo.addItem(name.title(), name)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        section.add_row("Preset", self.preset_combo)
        self.direction_combo = self._combo(DIRECTIONS)
        section.add_row("Start", self.direction_combo)
        self.sweep_combo = self._combo(SWEEPS)
        section.add_row("Sweep", self.sweep_combo)
        self.tilt_combo = self._combo(TILTS)
        section.add_row("Tilt", self.tilt_combo)

    def _build_angle_section(self):
        section = self._add_section("Angles")
        self.lon_slider = StepSlider(LON_STEPS, 15)
        self.lon_slider.valueChanged.connect(self.on_control_changed)
        section.add_row("Lon step", self.lon_slider)
        self.lat_slider = StepSlider(LAT_STEPS, 30)
        self.lat_slider.valueChanged.connect(self.on_control_changed)
        section.add_row("Lat step", self.lat_slider)
        self.lon_cull = self._spin(MAX_CULL)
        section.add_row("Lon cull", self.lon_cull)
        self.lat_cull = self._spin(MAX_CULL)
        section.add_row("Lat cull", self.lat_cull)
        self.error_label = QLabel()
        self.error_label.setProperty("class", "error")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        section.add(self.error_label)

    def _build_distance_section(self):
        section = self._add_section("Distances")
        self.distance_list = QListWidget()
        self.distance_list.setUniformItemSizes(True)
        self.distance_list.setFixedHeight(4 * (CONTROL_HEIGHT - 2) + 2)
        section.add(self.distance_list)
        self.distance_spin = fit_to_panel(QDoubleSpinBox())
        self.distance_spin.setDecimals(1)
        self.distance_spin.setRange(0.1, 1_000_000)
        add_line = QHBoxLayout()
        add_line.setSpacing(SPACING_SM)
        add_line.addWidget(self.distance_spin, 1)
        add_line.addWidget(self._button("Add", self.on_add_distance))
        add_line.addWidget(self._button("Remove", self.on_remove_distance, secondary=True))
        section.add(add_line)

    def _build_render_section(self):
        section = self._add_section("Render")
        self.test_edit = fit_to_panel(QLineEdit())
        self.test_edit.setPlaceholderText("test name")
        section.add_row("Test", self.test_edit)
        self.folder_edit = fit_to_panel(QLineEdit())
        self.folder_edit.setPlaceholderText("folder in render_data")
        self.folder_edit.textChanged.connect(self.update_folder_hint)
        folder_line = QHBoxLayout()
        folder_line.setSpacing(SPACING_SM)
        folder_line.addWidget(field_label("Folder"))
        folder_line.addWidget(self.folder_edit, 1)
        folder_line.addWidget(self._button("…", self.on_browse_folder, secondary=True))
        section.add(folder_line)
        self.folder_hint = fit_to_panel(QLabel())       # long paths must not widen the sidebar
        self.folder_hint.setProperty("class", "field")
        section.add(self.folder_hint)

        self.type_boxes = {}
        types_line = QHBoxLayout()
        types_line.setSpacing(SPACING_SM)
        for render_type in RENDER_TYPES:
            box = QCheckBox(RENDER_TYPE_LABELS.get(render_type, render_type))
            box.setChecked(True)                      # default: write all three
            box.toggled.connect(self.update_estimate)
            self.type_boxes[render_type] = box
            types_line.addWidget(box)
        types_line.addStretch(1)
        section.add(types_line)
        self.overwrite_box = QCheckBox("Overwrite an existing test")
        section.add(self.overwrite_box)
        actions = QHBoxLayout()
        actions.setSpacing(SPACING_SM)
        actions.addWidget(fit_to_panel(self._button("Simulate", self.on_simulate)))
        self.save_set_button = fit_to_panel(self._button("Save render set", self.save_render_set, secondary=True))
        self.save_set_button.setEnabled(False)
        actions.addWidget(self.save_set_button)
        section.add(actions)
        self.render_state = QLabel("Simulate writes temporary files - nothing is kept until you save")
        self.render_state.setProperty("class", "field")
        self.render_state.setWordWrap(True)
        section.add(self.render_state)
        self.render_error = QLabel()
        self.render_error.setProperty("class", "error")
        self.render_error.setWordWrap(True)
        self.render_error.hide()
        section.add(self.render_error)

    def _build_simulate_section(self):
        section = self._add_section("Simulate")
        self.fps_spin = self._plain_spin(1, 60, DEFAULT_FPS)
        self.fps_spin.valueChanged.connect(self.on_fps_changed)
        section.add_row("Speed (fps)", self.fps_spin)
        self.frames_spin = self._plain_spin(1, 600, DEFAULT_FRAMES_PER_LIGHT)
        self.frames_spin.valueChanged.connect(self.on_frames_changed)
        section.add_row("Frames/light", self.frames_spin)
        self.timing_label = QLabel()
        self.timing_label.setProperty("class", "value")
        section.add(self.timing_label)
        self.update_timing_label()
        self.estimate_label = QLabel()
        self.estimate_label.setProperty("class", "value")
        self.estimate_label.setWordWrap(True)
        self.estimate_label.setToolTip(
            "Seconds per image (until calibrated against real renders): "
            + ", ".join(f"{RENDER_TYPE_LABELS.get(t, t)} {s} s" for t, s in SECONDS_PER_RENDER.items()))
        section.add(self.estimate_label)
        buttons = QHBoxLayout()
        buttons.setSpacing(SPACING_SM)
        self.play_button = fit_to_panel(self._button("Play", self.on_play_pause))
        buttons.addWidget(self.play_button)
        buttons.addWidget(fit_to_panel(self._button("Stop", self.stop_simulation, secondary=True)))
        section.add(buttons)
        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.setRange(0, 0)
        self.frame_slider.setEnabled(False)
        self.frame_slider.valueChanged.connect(self.on_frame_slider)
        section.add_row("Frame", self.frame_slider)
        self.save_sim_gif_button = self._button("Save simulation GIF…", self.on_save_simulation_gif, secondary=True)
        self.save_sim_gif_button.setEnabled(False)
        section.add(self.save_sim_gif_button)
        self.sim_progress = QLabel("Press Simulate in the Render section to start")
        self.sim_progress.setProperty("class", "field")
        self.sim_progress.setWordWrap(True)
        section.add(self.sim_progress)
        note = QLabel(f"Cameras stay on screen {CAMERA_TO_LIGHT_RATIO}× as long as each light.\n"
                      f"Lights are drawn at {LIGHT_DISPLAY_SCALE}× the outer ring, not their true distance.")
        note.setProperty("class", "field")
        note.setWordWrap(True)
        section.add(note)

    def _plain_spin(self, minimum, maximum, value):
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def _build_display_section(self):
        section = self._add_section("Display")
        self.lines_box = QCheckBox("Lines to centre")
        self.lines_box.setChecked(True)
        self.lines_box.toggled.connect(self.redraw)
        section.add(self.lines_box)
        self.mesh_box = QCheckBox("Show object")
        self.mesh_box.setChecked(True)
        self.mesh_box.toggled.connect(self.draw_mesh)
        section.add(self.mesh_box)
        self.marker_slider = StepSlider(list(range(1, 11)), 4, suffix="%")
        self.marker_slider.valueChanged.connect(self.redraw)
        section.add_row("Markers", self.marker_slider)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(THEMES))
        self.theme_combo.currentTextChanged.connect(self.apply_theme)
        section.add_row("Theme", self.theme_combo)

    def _build_export_section(self):
        section = self._add_section("Export")
        buttons = QHBoxLayout()
        buttons.setSpacing(SPACING_SM)
        buttons.addWidget(fit_to_panel(self._button("Save GIF", self.on_save_gif)))
        buttons.addWidget(fit_to_panel(self._button("Copy settings", self.on_copy_settings, secondary=True)))
        section.add(buttons)
        hint = QLabel("Settings copy as a point_sweep(...) call.\n"
                      "Left-drag orbit (Z stays up) · right-drag pan · scroll zoom · R reset")
        hint.setWordWrap(True)
        hint.setProperty("class", "field")
        section.add(hint)

    # ---- object --------------------------------------------------------------------

    def load_object(self, path):
        if self.simulating:
            self.stop_simulation()
        self.obj_path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.test_edit.setText(f"{self.name}_test")
        self.folder_edit.setText(self.name)
        self.mesh = load_mesh(path, self.y_up)
        self.preview.hide()
        self.preview.set_scene(self.mesh, THEMES[self.theme_name])
        self.radius = self.mesh.length / 2
        scene = read_scene_info(path)
        self.units = scene["units"] if scene else None
        unit = UNIT_ABBREVIATIONS.get(self.units, "")
        self.distance_spin.setSuffix(f" {unit}" if unit else "")
        self.distance_spin.setValue(round(self.radius * 3, 1))
        self.object_label.setText(os.path.basename(path))
        self.tab.setText(f"{os.path.basename(path)}  —  sweep preview")
        self.status_units.setText(f"{self.units or 'units unknown'}   r = {self.radius:.1f}")

        self._applying = True
        self.distance_list.clear()
        self._applying = False
        self.add_distance(round(self.radius * 3, 1))
        if not self.preset_combo.currentData() or self.preset_combo.currentData() == "custom":
            self.preset_combo.setCurrentIndex(0)
        self.apply_preset(self.preset_combo.currentData())
        self.apply_theme(self.theme_name)
        self.draw_mesh()
        self.view.reset_view()

    def on_open_obj(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open OBJ", os.path.dirname(self.obj_path), "OBJ files (*.obj)")
        if path:
            self.load_object(path)

    def on_y_up_changed(self, checked):
        self.y_up = checked
        self.load_object(self.obj_path)

    # ---- settings ------------------------------------------------------------------------

    def settings(self):
        return {
            "direction": self.direction_combo.currentData(),
            "sweep": self.sweep_combo.currentData(),
            "tilt": self.tilt_combo.currentData(),
            "lon_step": self.lon_slider.value(),
            "lat_step": self.lat_slider.value(),
            "lon_cull": self.lon_cull.value(),
            "lat_cull": self.lat_cull.value(),
        }

    def distances(self):
        return [self.distance_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.distance_list.count())]

    def apply_preset(self, name):
        if name not in L.SWEEP_PRESETS:
            return
        preset = L.SWEEP_PRESETS[name]
        self._applying = True
        self.direction_combo.setCurrentIndex(self.direction_combo.findData(preset["direction"]))
        self.sweep_combo.setCurrentIndex(self.sweep_combo.findData(preset["sweep"]))
        self.tilt_combo.setCurrentIndex(self.tilt_combo.findData(preset["tilt"]))
        self.lon_slider.setValue(preset["lon_step"])
        self.lat_slider.setValue(preset["lat_step"])
        self.lon_cull.setValue(preset["lon_cull"])
        self.lat_cull.setValue(preset["lat_cull"])
        self._applying = False
        self.redraw()

    def matching_preset(self):
        current = self.settings()
        for name, preset in L.SWEEP_PRESETS.items():
            if preset == current:
                return name
        return "custom"

    def on_preset_changed(self, _index):
        if not self._applying:
            self.apply_preset(self.preset_combo.currentData())

    def on_control_changed(self, *_):
        if self._applying:
            return
        self._applying = True
        self.preset_combo.setCurrentIndex(self.preset_combo.findData(self.matching_preset()))
        self._applying = False
        self.redraw()

    # ---- distances ------------------------------------------------------------------------

    def add_distance(self, distance):
        if distance in self.distances():
            self.set_status(f"{distance:.1f} is already in the list")
            return
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, CONTROL_HEIGHT - 2))
        item.setData(Qt.ItemDataRole.UserRole, distance)
        self.distance_list.addItem(item)
        self.refresh_distance_items()
        self.redraw()
        self.view.reset_view()          # re-frame so the new ring fits

    def on_add_distance(self):
        self.add_distance(round(self.distance_spin.value(), 1))

    def on_remove_distance(self):
        rows = sorted({index.row() for index in self.distance_list.selectedIndexes()}, reverse=True)
        if not rows:
            rows = [self.distance_list.count() - 1]
        if self.distance_list.count() - len(rows) < 1:
            self.set_status("Keep at least one distance")
            return
        for r in rows:
            self.distance_list.takeItem(r)
        self.refresh_distance_items()
        self.redraw()
        self.view.reset_view()

    def refresh_distance_items(self):
        rings = THEMES[self.theme_name]["RINGS"]
        unit = UNIT_ABBREVIATIONS.get(self.units, "")
        for i in range(self.distance_list.count()):
            item = self.distance_list.item(i)
            distance = item.data(Qt.ItemDataRole.UserRole)
            item.setText(f"●  {distance:>9.1f} {unit:<2}   {distance / self.radius:4.2f}× r")
            item.setForeground(QColor(rings[i % len(rings)]))

    # ---- drawing ----------------------------------------------------------------------------

    def draw_mesh(self):
        if self.mesh_box.isChecked():
            self.view.set_actor("mesh", self.mesh, THEMES[self.theme_name]["MESH"])
        else:
            self.view.remove_actor("mesh")
        self.view.refresh()

    def marker_radius(self):
        return self.radius * self.marker_slider.value() / 100

    def redraw(self, *_):
        if self._applying or not hasattr(self, "mesh"):
            return
        if self.simulating:              # editing the sweep ends the playback
            self.stop_simulation()       # (stop_simulation redraws the sweep itself)
            return
        t = THEMES[self.theme_name]
        self.view.remove_matching("ring")
        self.view.remove_matching("lines")
        self.rings = []
        try:
            pairs = L.sweep_angles(**self.settings())
        except ValueError as error:
            self.error_label.setText(f"Invalid sweep: {error}")
            self.error_label.show()
            self.status_count.setText("0 cameras")
            self.set_status(f"Invalid sweep: {error}")
            self.update_estimate()
            self.view.refresh()
            return
        self.error_label.hide()

        for i, distance in enumerate(self.distances()):
            points = L.point_sphere(pairs, distance)
            self.rings.append((distance, points))
            color = t["RINGS"][i % len(t["RINGS"])]
            self.view.set_actor(f"ring{i}", camera_markers(points, self.marker_radius()), color)
            if self.lines_box.isChecked():
                self.view.set_actor(f"lines{i}", lines_to_centre(points), t["LINES"], opacity=0.5)

        total = sum(len(points) for _, points in self.rings)
        per_ring = len(pairs)
        self.status_count.setText(f"{total} cameras  ({per_ring} × {len(self.rings)})")
        self.set_status(f"{self.preset_combo.currentText()} sweep")
        self.update_estimate()
        self.view.refresh()

    def update_estimate(self, *_):
        """Images the ticked render lists would produce for the cameras on screen, each type
        timed with its own SECONDS_PER_RENDER."""
        if not hasattr(self, "estimate_label"):
            return
        cameras = sum(len(points) for _, points in self.rings)
        counts = {render_type: cameras * images_per_camera(render_type)
                  for render_type, box in self.type_boxes.items() if box.isChecked()}
        images = sum(counts.values())
        if not images:
            self.estimate_label.setText("Estimated render time: nothing to render")
            return
        seconds = {t: SECONDS_PER_RENDER.get(t, DEFAULT_SECONDS_PER_RENDER) for t in counts}
        total = sum(counts[t] * seconds[t] for t in counts)
        lines = [f"{RENDER_TYPE_LABELS.get(t, t)}: {counts[t]} × {seconds[t]} s = {format_duration(counts[t] * seconds[t])}"
                 for t in counts]
        self.estimate_label.setText(f"Estimated render ≈ {format_duration(total)}  ({images} images)\n" + "\n".join(lines))

    def set_status(self, message):
        self.status_message.setText(message)

    def apply_theme(self, theme_name):
        self.theme_name = theme_name
        t = THEMES[theme_name]
        QApplication.instance().setStyleSheet(build_qss(t, theme_icons(theme_name, t)))
        self.view.set_background(t["VIEW_BG"])
        if hasattr(self, "mesh"):
            self.preview.set_scene(self.mesh, t)
        self.refresh_distance_items()
        self.draw_mesh()
        if self.simulating:              # keep playing, just recolour
            self.draw_sim_static()
            self.draw_sim_frame(min(self.sim_index, len(self.sim_frames) - 1), force=True)
        else:
            self.redraw()

    # ---- export -----------------------------------------------------------------------------

    def settings_code(self):
        preset = self.matching_preset()
        distances = self.distances()
        distance_text = repr(distances[0]) if len(distances) == 1 else repr(distances)
        if preset != "custom":
            return f'point_sweep("{preset}", {distance_text})'
        args = ", ".join(f"{key}={value!r}" for key, value in self.settings().items())
        return f"sweep_points({distance_text}, {args})"

    def on_copy_settings(self):
        code = self.settings_code()
        QGuiApplication.clipboard().setText(code)
        print(code)
        self.set_status(f"Copied: {code}")

    def on_save_gif(self):
        if not self.rings:
            self.set_status("Nothing to save - the sweep is invalid")
            return
        t = THEMES[self.theme_name]
        s = self.settings()
        os.makedirs(PREVIEW_FOLDER, exist_ok=True)
        path = os.path.join(
            PREVIEW_FOLDER,
            f"{self.name}_{s['sweep']}_{s['tilt']}_{s['direction']}_lon{s['lon_step']}_lat{s['lat_step']}"
            f"_x{len(self.rings)}.gif")

        width, height = self.view.width(), self.view.height()
        recorder = pv.Plotter(off_screen=True, window_size=(max(width, 320), max(height, 240)))
        recorder.set_background(t["VIEW_BG"])
        if self.mesh_box.isChecked():
            recorder.add_mesh(self.mesh, color=t["MESH"])
        recorder.camera_position = self.view.camera_position()
        recorder.open_gif(path)
        for i, (_, points) in enumerate(self.rings):                  # rings one after another
            color = t["RINGS"][i % len(t["RINGS"])]
            for n in range(1, len(points) + 1):                       # one camera added per frame
                recorder.add_mesh(camera_markers(points[:n], self.marker_radius()), color=color, name=f"ring{i}")
                if self.lines_box.isChecked():
                    recorder.add_mesh(lines_to_centre(points[:n]), color=t["LINES"], opacity=0.5, name=f"lines{i}")
                recorder.write_frame()
        for _ in range(10):                                             # hold the finished sweep
            recorder.write_frame()
        recorder.close()
        self.set_status(f"Saved {path}")
        print(f"Saved {path}")

    # ---- render set + simulation -------------------------------------------------------------

    def folder_path(self):
        return os.path.join(RENDER_DATA_FOLDER, self.folder_edit.text().strip())

    def update_folder_hint(self, *_):
        if not self.folder_edit.text().strip():
            self.folder_hint.setText("")
            return
        full = os.path.normpath(self.folder_path())
        pipeline = os.path.dirname(os.path.normpath(RENDER_DATA_FOLDER))
        try:
            shown = os.path.relpath(full, pipeline)
        except ValueError:                               # a different drive
            shown = full
        if shown.startswith(".."):
            shown = full
        self.folder_hint.setText(f"→ {shown}")
        self.folder_hint.setToolTip(full)

    def on_browse_folder(self):
        os.makedirs(RENDER_DATA_FOLDER, exist_ok=True)
        chosen = QFileDialog.getExistingDirectory(self, "Folder for the render CSVs", RENDER_DATA_FOLDER)
        if not chosen:
            return
        chosen = os.path.normpath(chosen)
        inside = os.path.commonpath([chosen, os.path.normpath(RENDER_DATA_FOLDER)]) == os.path.normpath(RENDER_DATA_FOLDER)
        self.folder_edit.setText(os.path.relpath(chosen, RENDER_DATA_FOLDER) if inside else chosen)

    def show_render_error(self, message):
        self.render_error.setText(message)
        self.render_error.show()
        self.set_status(message)

    def discard_temp(self):
        if self.temp_folder:
            shutil.rmtree(self.temp_folder, ignore_errors=True)
        self.temp_folder = None
        self.temp_paths = {}
        self.unsaved = False
        self.save_set_button.setEnabled(False)

    def on_simulate(self):
        """Write the render set to a temporary folder and play the default list back.
        Nothing reaches render_data until Save render set is pressed."""
        self.render_error.hide()
        points = [point for _, ring in self.rings for point in ring]
        types = [render_type for render_type, box in self.type_boxes.items() if box.isChecked()]
        if not points:
            self.show_render_error("No cameras to write - the sweep is invalid")
            return
        if not types:
            self.show_render_error("Tick at least one render type to write")
            return
        if self.simulating:
            self.stop_simulation()

        self.discard_temp()
        self.temp_folder = tempfile.mkdtemp(prefix="sweep_preview_")
        try:
            paths = create_render_set(self.test_edit.text().strip(), self.temp_folder, points, types=types)
        except (ValueError, OSError) as error:
            self.discard_temp()
            self.show_render_error(str(error))
            return

        self.temp_paths = {render_type: path for render_type, path in zip(types, paths)}
        self.unsaved = True
        self.save_set_button.setEnabled(True)
        self.render_state.setText(f"Unsaved - {len(points)} cameras × {len(types)} lists in a temporary folder")
        default_csv = self.temp_paths.get("default")
        if default_csv is None:
            self.set_status("Prepared the render set (no default list, so nothing to simulate) - Save to keep it")
            return
        self.last_default_csv = default_csv
        self.start_simulation(default_csv)

    on_write_render_set = on_simulate      # older name, kept so existing calls still work

    def save_render_set(self):
        """Copy the simulated (temporary) CSVs to render_data under the current test name and folder."""
        self.render_error.hide()
        if not self.temp_paths:
            self.show_render_error("Nothing to save - press Simulate first")
            return False
        test_name = self.test_edit.text().strip()
        if not test_name or any(char in test_name for char in '\\/:*?"<>|'):
            self.show_render_error(f"'{test_name}' can't be used as a file name")
            return False
        if not self.folder_edit.text().strip():
            self.show_render_error("Choose a folder to save into")
            return False

        folder = self.folder_path()
        targets = {t: os.path.join(folder, f"{test_name}_{t}.csv") for t in self.temp_paths}
        existing = [path for path in targets.values() if os.path.exists(path)]
        if existing and not self.overwrite_box.isChecked():
            self.show_render_error(f"'{test_name}' already exists in {folder} - use a new test name or tick Overwrite")
            return False
        try:
            os.makedirs(folder, exist_ok=True)
            for render_type, temp_path in self.temp_paths.items():
                shutil.copyfile(temp_path, targets[render_type])
        except OSError as error:
            self.show_render_error(f"Could not save: {error}")
            return False

        self.unsaved = False
        self.save_set_button.setEnabled(False)
        if "default" in targets:
            self.last_default_csv = targets["default"]
        names = ", ".join(os.path.basename(path) for path in targets.values())
        self.render_state.setText(f"Saved {names}")
        self.set_status(f"Saved {len(targets)} render lists to {folder}")
        print(f"Saved {names} -> {folder}")
        return True

    def start_simulation(self, default_csv):
        """Read the default render list back and play it camera by camera, light by light."""
        renders = read_renders(default_csv)
        if not renders:
            self.show_render_error("The default render list is empty")
            return
        outer = max(float(np.linalg.norm(render.camera.startloc)) for render in renders)
        self.sim_cameras = []
        for render in renders:
            centre = np.array(render.camera.endloc, dtype=float)
            lights = []
            for light in render.light.locations()[0]:           # true positions (e.g. 10,000 mm away)
                direction = np.array(light, dtype=float) - centre
                direction /= np.linalg.norm(direction)
                lights.append(tuple(centre + direction * outer * LIGHT_DISPLAY_SCALE))
            number = re.search(r"(\d+)$", render.camera.name)       # Camera12 -> 12 (matches the file names)
            self.sim_cameras.append({
                "name": render.camera.name,
                "number": int(number.group(1)) if number else len(self.sim_cameras),
                "camera": render.camera.startloc,
                "lights": lights,
                "images": render.output.name_list(),
                "target": render.camera.endloc,
                "fov": render.camera.FOV,
                "dimensions": render.output.dimensions,
            })
        self.sim_index = 0
        self.sim_source = os.path.basename(default_csv)
        self.rebuild_schedule()
        self.enter_sim_view()
        self.view.reset_view()                                     # re-frame so the lights fit
        self.timer.start(round(1000 / self.fps_spin.value()))
        self.play_button.setText("Pause")
        self.sim_step()

    def rebuild_schedule(self):
        self.sim_frames = simulation_schedule([len(c["lights"]) for c in self.sim_cameras], self.frames_spin.value())
        self.sim_last = None
        self.frame_slider.blockSignals(True)
        self.frame_slider.setRange(0, max(len(self.sim_frames) - 1, 0))
        self.frame_slider.setEnabled(bool(self.sim_frames))
        self.frame_slider.blockSignals(False)

    def enter_sim_view(self):
        """Swap the sweep rings for the simulation's scene (used by Simulate and by seeking)."""
        self.simulating = True
        self.save_sim_gif_button.setEnabled(True)
        self.view.remove_matching("ring")
        self.view.remove_matching("lines")
        self.sim_last = None
        self.draw_sim_static()

    def label_size(self):
        return round(LABEL_FONT_SIZE * self.view.devicePixelRatioF())

    def draw_sim_static(self):
        t = THEMES[self.theme_name]
        cameras = [c["camera"] for c in self.sim_cameras]
        self.view.set_actor("sim_ghost", camera_markers(cameras, self.marker_radius()), t["SIM_GHOST"])

    def draw_sim_frame(self, index, force=False):
        camera_index, light_index = self.sim_frames[index]
        camera = self.sim_cameras[camera_index]
        if force or self.sim_last != (camera_index, light_index):
            t = THEMES[self.theme_name]
            draw_sim_state(self.view.set_actor, self.view.remove_actor, camera, light_index, t, self.marker_radius())
            # labels only on what is showing: the active camera and its lights
            self.view.set_label_actor("sim_camera_label", point_labels(
                [camera["camera"]], [subscript_label("C", camera["number"])], t["SIM_CAMERA"], self.label_size(),
                lift=self.marker_radius() * CAMERA_LABEL_LIFT))
            self.view.set_label_actor("sim_light_labels", point_labels(
                camera["lights"], [subscript_label("L", i) for i in range(len(camera["lights"]))],
                t["SIM_LIGHT"], self.label_size(), lift=self.marker_radius() * LIGHT_LABEL_LIFT))
            self.preview.show_camera(camera, light_index)
            self.view.refresh()
            self.sim_last = (camera_index, light_index)

        self.set_status(self.sim_caption(camera_index, light_index))
        self.sim_progress.setText(f"{self.sim_source}\nFrame {index + 1} / {len(self.sim_frames)}")
        self.frame_slider.blockSignals(True)            # keep the slider in step without re-seeking
        self.frame_slider.setValue(index)
        self.frame_slider.blockSignals(False)

    def on_frame_slider(self, index):
        """Jump to a frame. Playback keeps going from there if it was playing; otherwise it waits."""
        if not self.sim_frames:
            return
        if not self.simulating:                        # stopped: bring the simulation view back, paused
            self.enter_sim_view()
            self.play_button.setText("Play")
        self.draw_sim_frame(index)
        self.sim_index = index + 1
        if not self.timer.isActive():
            self.play_button.setText("Play")

    def on_frames_changed(self, *_):
        self.update_timing_label()
        if not self.sim_cameras:
            return
        progress = self.sim_index / max(len(self.sim_frames), 1)   # keep roughly the same place
        self.rebuild_schedule()
        self.sim_index = min(round(progress * len(self.sim_frames)), len(self.sim_frames) - 1)
        if self.simulating:
            self.draw_sim_frame(self.sim_index, force=True)

    def sim_caption(self, camera_index, light_index):
        camera = self.sim_cameras[camera_index]
        if light_index is None:
            doing = "camera only"
        else:
            image = camera["images"][light_index] if light_index < len(camera["images"]) else "?"
            doing = f"light {light_index + 1}/{len(camera['lights'])} → {image}"
        return f"{camera['name']} ({camera_index + 1}/{len(self.sim_cameras)})  ·  {doing}"

    def choose_gif_path(self, suggested):
        path, _ = QFileDialog.getSaveFileName(self, "Save simulation GIF", suggested, "GIF images (*.gif)")
        return path

    def on_save_simulation_gif(self):
        """Record the whole simulation as a GIF: one frame per lighting state, each held exactly
        as long as it is on screen during playback."""
        if not self.sim_cameras:
            self.set_status("Simulate a render set first")
            return
        from PIL import Image                                       # installed with imageio

        saved_folder = self.folder_path() if not self.unsaved else os.path.join(RENDER_DATA_FOLDER, "previews")
        suggested = os.path.join(saved_folder, f"{self.test_edit.text().strip() or self.name}_simulation.gif")
        path = self.choose_gif_path(suggested)
        if not path:
            return
        if not path.lower().endswith(".gif"):
            path += ".gif"

        was_playing = self.timer.isActive()
        self.timer.stop()
        t = THEMES[self.theme_name]
        fps = self.fps_spin.value()
        width = min(GIF_MAX_WIDTH, self.view.width())
        height = round(width * self.view.height() / max(self.view.width(), 1))
        recorder = pv.Plotter(off_screen=True, window_size=(width, height))
        recorder.set_background(t["VIEW_BG"])
        if self.mesh_box.isChecked():
            recorder.add_mesh(self.mesh, color=t["MESH"])
        cameras = [c["camera"] for c in self.sim_cameras]
        recorder.add_mesh(camera_markers(cameras, self.marker_radius()), color=t["SIM_GHOST"])
        recorder.camera_position = self.view.camera_position()

        def add(name, mesh, color, opacity=1.0):
            recorder.add_mesh(mesh, color=color, opacity=opacity, name=name, reset_camera=False)

        def remove(name):
            recorder.remove_actor(name, render=False)

        runs = compress_schedule(self.sim_frames)
        images, durations = [], []
        try:
            for n, ((camera_index, light_index), count) in enumerate(runs):
                camera = self.sim_cameras[camera_index]
                draw_sim_state(add, remove, camera, light_index, t, self.marker_radius())
                recorder.add_actor(point_labels(camera["lights"], [subscript_label("L", i) for i in range(len(camera["lights"]))],
                                                t["SIM_LIGHT"], LABEL_FONT_SIZE, lift=self.marker_radius() * LIGHT_LABEL_LIFT),
                                   name="sim_light_labels", reset_camera=False, render=False)
                recorder.add_actor(point_labels([camera["camera"]], [subscript_label("C", camera["number"])],
                                                t["SIM_CAMERA"], LABEL_FONT_SIZE, lift=self.marker_radius() * CAMERA_LABEL_LIFT),
                                   name="sim_camera_label", reset_camera=False, render=False)
                caption = self.sim_caption(camera_index, light_index).replace("→", "->")   # GIF font has no arrow
                recorder.add_text(caption, position="upper_left",
                                  font_size=9, color=t["FG"], name="caption")
                frame = recorder.screenshot(return_img=True)[:, :, :3]
                images.append(Image.fromarray(frame).convert("P", palette=Image.Palette.ADAPTIVE, colors=256))
                durations.append(round(count * 1000 / fps))
                if n % 10 == 0:
                    self.set_status(f"Recording GIF… {n + 1}/{len(runs)}")
                    QApplication.processEvents()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            images[0].save(path, save_all=True, append_images=images[1:], duration=durations, loop=0)
        except OSError as error:
            self.set_status(f"Could not save the GIF: {error}")
            return
        finally:
            recorder.close()
            if was_playing:
                self.timer.start(round(1000 / fps))

        seconds = sum(durations) / 1000
        self.set_status(f"Saved simulation GIF ({len(images)} frames, {seconds:.1f} s) to {path}")
        print(f"Saved {path}")

    def sim_step(self):
        if self.sim_index >= len(self.sim_frames):
            self.timer.stop()
            self.play_button.setText("Replay")
            self.set_status(f"Simulation finished - {len(self.sim_cameras)} cameras from {self.sim_source}")
            return
        self.draw_sim_frame(self.sim_index)
        self.sim_index += 1

    def on_play_pause(self):
        if self.simulating and self.timer.isActive():               # pause
            self.timer.stop()
            self.play_button.setText("Play")
        elif self.simulating and self.sim_index < len(self.sim_frames):   # resume
            self.timer.start(round(1000 / self.fps_spin.value()))
            self.play_button.setText("Pause")
        elif self.last_default_csv and os.path.exists(self.last_default_csv):   # replay / start
            self.start_simulation(self.last_default_csv)
        else:
            self.set_status("Press Simulate in the Render section first")

    def on_fps_changed(self, fps):
        self.update_timing_label()
        if self.timer.isActive():
            self.timer.setInterval(round(1000 / fps))

    def update_timing_label(self, *_):
        fps = self.fps_spin.value()
        light_seconds = self.frames_spin.value() / fps
        self.timing_label.setText(f"{light_seconds:.2f} s per light · "
                                  f"{CAMERA_TO_LIGHT_RATIO * light_seconds:.2f} s per camera")

    def stop_simulation(self):
        self.timer.stop()
        was_simulating = self.simulating
        self.simulating = False
        self.play_button.setText("Play")
        self.view.remove_matching("sim_")
        self.preview.hide()
        if was_simulating:
            self.sim_progress.setText("Stopped - press Play to replay the last render set")
            self.redraw()
            self.view.reset_view()

    def ask_save_on_close(self):
        return QMessageBox.question(
            self, "Unsaved render set",
            "The last simulated render set hasn't been saved.\nSave it to render_data before closing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)

    def closeEvent(self, event):
        if self.unsaved:
            choice = self.ask_save_on_close()
            if choice == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if choice == QMessageBox.StandardButton.Save and not self.save_render_set():
                event.ignore()                    # saving failed - stay open so the error can be read
                return
        self.timer.stop()
        self.discard_temp()                       # temporary CSVs are always cleaned up
        self.view.close_plotter()
        self.preview.close_plotter()
        super().closeEvent(event)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OBJ
    app = QApplication(sys.argv)
    window = SweepPreview(path)
    window.show()
    app.processEvents()             # let the window take its real size before drawing
    window.view.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
