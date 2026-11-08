"""Tema, contexto compartilhado e widgets reutilizáveis."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QDialog, QLabel, QScrollArea, QSlider, QTextBrowser, QVBoxLayout, QHBoxLayout)

from ..content import Library
from ..db import UserDB
from ..render import PALETTES, html_css
from ..search import SearchIndex
from ..study import LEVEL_NAMES

MASTERY_COLORS = {0: "#5b6675", 1: "#6c8aa8", 2: "#e0a458", 3: "#4cc2b0", 4: "#6fcf6f"}
MASTERY_SYMBOL = {0: "○", 1: "◔", 2: "◑", 3: "◕", 4: "●"}
RELATION_COLORS = {
    "forma_de": "#8e9aaf", "participa_de": "#4cc2b0", "regula": "#e0a458", "antes_de": "#6cb6ff",
    "necessario_para": "#c792ea", "pode_causar": "#e06c6c", "medido_por": "#7bd88f", "diferente_de": "#d9d9d9",
}


from ..render import CATEGORY_STYLE, LEVEL_STARS, cat_color, cat_icon  # noqa: F401,E402


def qss(theme: str) -> str:
    p = PALETTES[theme]
    return f"""
    QWidget {{ background:{p['bg']}; color:{p['text']}; font-family:'Segoe UI','Noto Sans',sans-serif; font-size:10.5pt; }}
    QFrame#card {{ background:{p['panel']}; border:1px solid {p['border']}; border-radius:8px; }}
    QFrame#card QLabel {{ background:transparent; }}
    QLabel#h {{ color:{p['accent']}; font-size:12pt; font-weight:bold; background:transparent; }}
    QLabel#muted {{ color:{p['muted']}; background:transparent; }}
    QPushButton {{ background:{p['panel2']}; border:1px solid {p['border']}; border-radius:6px; padding:5px 12px; }}
    QPushButton:hover {{ border-color:{p['accent']}; }}
    QPushButton:checked {{ background:{p['accent']}; color:#0b0f14; }}
    QPushButton#nav {{ text-align:left; padding:10px 14px; border:none; border-radius:0; background:{p['panel']}; }}
    QPushButton#nav:checked {{ background:{p['bg']}; color:{p['accent']}; border-left:3px solid {p['accent']}; }}
    QPushButton#primary {{ background:{p['accent']}; color:#0b0f14; font-weight:bold; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QListWidget, QTreeWidget, QTableWidget, QTextBrowser {{
        background:{p['panel']}; border:1px solid {p['border']}; border-radius:6px; }}
    QLineEdit, QComboBox {{ padding:5px; }}
    QListWidget::item, QTreeWidget::item {{ padding:3px; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background:{p['panel2']}; color:{p['accent']}; }}
    QTabWidget::pane {{ border:1px solid {p['border']}; }}
    QTabBar::tab {{ background:{p['panel']}; padding:6px 12px; border:1px solid {p['border']}; }}
    QTabBar::tab:selected {{ color:{p['accent']}; background:{p['panel2']}; }}
    QFrame#hero {{ background:{p['panel']}; border:1px solid {p['accent']}; border-radius:12px; }}
    QFrame#hero QLabel {{ background:transparent; }}
    QLabel#big {{ font-size:22pt; font-weight:bold; background:transparent; }}
    QLabel#badge {{ background:{p['panel2']}; border:1px solid {p['border']}; border-radius:10px; padding:6px 10px; }}
    QLabel#badgeoff {{ background:{p['bg']}; border:1px dashed {p['border']}; border-radius:10px; padding:6px 10px; color:{p['muted']}; }}
    QPushButton#good {{ background:#2e7d4f; color:white; font-weight:bold; padding:9px 14px; }}
    QPushButton#bad {{ background:#a33a3a; color:white; font-weight:bold; padding:9px 14px; }}
    QPushButton#hard {{ background:#a8741a; color:white; font-weight:bold; padding:9px 14px; }}
    QPushButton#easy {{ background:#1f6f8b; color:white; font-weight:bold; padding:9px 14px; }}
    QProgressBar {{ background:{p['panel2']}; border:1px solid {p['border']}; border-radius:6px; text-align:center; }}
    QProgressBar::chunk {{ background:{p['accent']}; border-radius:5px; }}
    QMenuBar, QMenu, QStatusBar {{ background:{p['panel']}; }}
    QMenu::item:selected {{ background:{p['panel2']}; }}
    QGraphicsView {{ border:1px solid {p['border']}; background:{p['bg']}; }}
    QScrollArea {{ border:none; }}
    QHeaderView::section {{ background:{p['panel2']}; border:1px solid {p['border']}; padding:4px; }}
    """


class Context(QObject):
    """Estado compartilhado entre as telas."""
    openArticle = Signal(str)
    dataChanged = Signal()
    themeChanged = Signal(str)
    gotoView = Signal(str)

    def __init__(self, lib: Library, db: UserDB, fig_dirs: list[Path]):
        super().__init__()
        self.lib, self.db, self.fig_dirs = lib, db, fig_dirs
        self.index = SearchIndex(lib)
        self.theme = db.get_setting("theme", "dark")
        self.font_pt = int(db.get_setting("font_pt", "11") or 11)

    def reload_content(self) -> None:
        self.lib.load()
        self.index = SearchIndex(self.lib)
        self.dataChanged.emit()

    def css(self) -> str:
        return html_css(self.theme, self.font_pt)

    def level_label(self, lv: int) -> str:
        return f"{MASTERY_SYMBOL[lv]} {LEVEL_NAMES[lv]}"


class ArticleBrowser(QTextBrowser):
    """QTextBrowser que renderiza SVG/PNG e abre figuras ampliadas com duplo clique."""
    linkClicked = Signal(QUrl)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self.linkClicked.emit)

    def loadResource(self, rtype: int, url: QUrl):  # noqa: N802
        path = url.toLocalFile() if url.isLocalFile() else url.toString()
        if path.lower().endswith(".svg") and Path(path).exists():
            r = QSvgRenderer(path)
            size = r.defaultSize()
            if size.isEmpty():
                return None
            scale = 1500 / max(1, size.width())
            img = QImage(int(size.width() * scale), int(size.height() * scale), QImage.Format_ARGB32)
            img.fill(QColor("white"))
            p = QPainter(img)
            r.render(p, QRectF(0, 0, img.width(), img.height()))
            p.end()
            return img
        return super().loadResource(rtype, url)


class ZoomDialog(QDialog):
    """Visualizador ampliável de figuras (SVG/PNG)."""

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(path.name)
        self.resize(1100, 760)
        self._pix = self._load(path)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.label)
        self.scroll.setWidgetResizable(False)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(30, 300)
        self.slider.setValue(100)
        self.slider.valueChanged.connect(self._apply)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Zoom:"))
        top.addWidget(self.slider)
        lay.addLayout(top)
        lay.addWidget(self.scroll)
        self._apply(100)

    @staticmethod
    def _load(path: Path) -> QPixmap:
        if path.suffix.lower() == ".svg":
            r = QSvgRenderer(str(path))
            s = r.defaultSize()
            scale = 2000 / max(1, s.width())
            img = QImage(int(s.width() * scale), int(s.height() * scale), QImage.Format_ARGB32)
            img.fill(QColor("white"))
            p = QPainter(img)
            r.render(p, QRectF(0, 0, img.width(), img.height()))
            p.end()
            return QPixmap.fromImage(img)
        return QPixmap(str(path))

    def _apply(self, pct: int) -> None:
        w = max(50, int(self._pix.width() * pct / 100 * 0.5))
        pm = self._pix.scaledToWidth(w, Qt.SmoothTransformation)
        self.label.setPixmap(pm)
        self.label.resize(pm.size())
