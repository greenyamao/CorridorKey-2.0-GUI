"""Modern Studio Dark Theme for CorridorKey 2.0 GUI."""

# Professional Studio Palette (calm, high-contrast, easy on the eyes)
CORRIDOR_YELLOW = "#FFB800"
ACCENT_BLUE = "#3B82F6"
ACCENT_CYAN = "#38BDF8"
CORRIDOR_GREEN = "#10B981"

BG_CANVAS = "#131316"
BG_DARK = BG_CANVAS
PANEL_BG = "#18181C"
CARD_BG = "#1A1A1E"
INPUT_BG = "#222228"
INPUT_HOVER = "#2A2A32"
BORDER_SUBTLE = "#28282E"
BORDER_FOCUS = "#3B82F6"

TEXT_PRIMARY = "#FFFFFF"        # Pure white for main text and headers
TEXT_SECONDARY = "#E2E8F0"      # Bright silver for labels and settings (crisp, high contrast)
TEXT_MUTED = "#94A3B8"          # Clear light slate for secondary info (never black-on-black)

DARK_WORKBENCH_QSS = f"""
QMainWindow {{
    background-color: {BG_CANVAS};
    color: {TEXT_PRIMARY};
}}

QWidget {{
    background-color: transparent;
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI Variable Text", "Segoe UI", -apple-system, sans-serif;
    font-size: 12px;
}}

QLabel {{
    color: {TEXT_SECONDARY};
}}

/* Flat Section Card */
QFrame.flat-card {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 6px;
}}

/* Splitters */
QSplitter::handle {{
    background-color: {BG_CANVAS};
}}
QSplitter::handle:horizontal {{
    width: 3px;
}}
QSplitter::handle:vertical {{
    height: 3px;
}}

/* ScrollBars: Subtle, modern 4px overlay bars */
QScrollBar:vertical {{
    background: transparent;
    width: 5px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #3A3A42;
    min-height: 28px;
    border-radius: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: #52525E;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 5px;
    margin: 0px;
}}
QScrollBar::handle:horizontal {{
    background: #3A3A42;
    min-width: 28px;
    border-radius: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #52525E;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* Tooltips */
QToolTip {{
    background-color: #202026;
    color: #FFFFFF;
    border: 1px solid #444450;
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 11px;
}}

/* Default Buttons */
QPushButton {{
    background-color: #222228;
    color: #FFFFFF;
    border: 1px solid #363640;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: #2A2A32;
    border-color: #4C4C5A;
}}
QPushButton:pressed {{
    background-color: #1A1A20;
}}
QPushButton:disabled {{
    background-color: #1E1E24;
    border-color: #282830;
    color: #7A7A88;
}}

/* Flat Inputs */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background-color: {INPUT_BG};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 4px;
    padding: 4px 8px;
    color: #FFFFFF;
    min-height: 20px;
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {{
    background-color: {INPUT_HOVER};
    border-color: #40404C;
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
    border: 1px solid {BORDER_FOCUS};
}}
QComboBox QAbstractItemView {{
    background-color: #202026;
    color: #FFFFFF;
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 4px;
    selection-background-color: {ACCENT_BLUE};
    selection-color: #FFFFFF;
    padding: 4px;
}}

/* Checkboxes with authentic checkmark icon */
QCheckBox {{
    spacing: 7px;
    font-size: 11px;
    color: {TEXT_SECONDARY};
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    background-color: {INPUT_BG};
    border: 1px solid #40404C;
    border-radius: 3px;
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT_BLUE};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT_BLUE};
    border-color: {ACCENT_BLUE};
    image: url(:/qfluentwidgets/images/icons/Accept_white.svg);
    padding: 1px;
}}

/* Sliders */
QSlider::groove:horizontal {{
    height: 4px;
    background: #282830;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT_BLUE};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: #FFFFFF;
    border: 1px solid #CCCCCC;
    width: 12px;
    height: 12px;
    margin-top: -4px;
    margin-bottom: -4px;
    border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{
    background: #E5F0FF;
}}

/* Pill Buttons */
QPushButton.pill-btn {{
    background-color: #222228;
    color: #FFFFFF;
    border: 1px solid #363640;
    border-radius: 5px;
    padding: 5px 12px;
    font-weight: 600;
    font-size: 11px;
}}
QPushButton.pill-btn:hover {{
    background-color: #2A2A32;
    border-color: #4C4C5A;
}}
QPushButton.pill-btn:pressed {{
    background-color: #1A1A20;
}}
QPushButton.pill-btn:disabled {{
    background-color: #1E1E24;
    border-color: #2C2C34;
    color: #6C6C78;
}}

/* Primary Action Button (Render) */
QPushButton.primary-btn {{
    background-color: {ACCENT_BLUE};
    color: #FFFFFF;
    border: none;
    border-radius: 5px;
    padding: 6px 16px;
    font-weight: 700;
    font-size: 12px;
}}
QPushButton.primary-btn:hover {{
    background-color: #2563EB;
}}
QPushButton.primary-btn:pressed {{
    background-color: #1D4ED8;
}}
QPushButton.primary-btn:disabled {{
    background-color: #222228;
    border: 1px solid #303038;
    color: #7A7A88;
}}

/* Amber Accent Button */
QPushButton.yellow-btn {{
    background-color: #D97706;
    color: #FFFFFF;
    border: 1px solid #F59E0B;
    border-radius: 5px;
    padding: 4px 12px;
    font-weight: 700;
    font-size: 11px;
}}
QPushButton.yellow-btn:hover {{
    background-color: #B45309;
    border-color: #FBBF24;
}}
QPushButton.yellow-btn:disabled {{
    background-color: #222228;
    color: #6C6C78;
}}
"""
