"""Itens gráficos: nós arredondados com faixa de categoria, arestas realçáveis, setas de gene."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsObject, QGraphicsPathItem, QGraphicsView, QStyleOptionGraphicsItem


def wrap2(text: str, fm: QFontMetrics, width: int) -> list[str]:
    """Quebra em até 2 linhas, com reticências na segunda."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if fm.horizontalAdvance(t) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) > 2:
        lines = [lines[0], " ".join(lines[1:])]
    return [fm.elidedText(l, Qt.ElideRight, width) for l in lines]


class NodeItem(QGraphicsObject):
    def __init__(self, aid: str, title: str, subtitle: str, w: float, h: float, stripe: str, border: str, fill: str,
                 text: str, muted: str, pips: int = 0, dashed: bool = False, glow: str | None = None,
                 on_click=None, on_double=None, badge: str = ""):
        super().__init__()
        self.aid, self.title, self.subtitle, self.w, self.h = aid, title, subtitle, w, h
        self.stripe, self.border, self.fill, self.text, self.muted = stripe, border, fill, text, muted
        self.pips, self.dashed, self.glow, self.badge = pips, dashed, glow, badge
        self._click, self._double = on_click, on_double
        self.dim = False
        self.selected = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(2)
        self.setToolTip(f"{title}\n{subtitle}")

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(-4, -4, self.w + 8, self.h + 8)

    def paint(self, p: QPainter, _o: QStyleOptionGraphicsItem, _w=None) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(0.28 if self.dim else 1.0)
        r = QRectF(0, 0, self.w, self.h)
        if self.glow:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self.glow + "40"))
            p.drawRoundedRect(r.adjusted(-4, -4, 4, 4), 12, 12)
        pen = QPen(QColor(self.border), 3 if self.selected else 2)
        if self.dashed:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(QColor(self.fill))
        p.drawRoundedRect(r, 9, 9)
        # faixa de categoria
        clip = QPainterPath()
        clip.addRoundedRect(r, 9, 9)
        p.save()
        p.setClipPath(clip)
        p.fillRect(QRectF(0, 0, 8, self.h), QColor(self.stripe))
        p.restore()
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(self.text))
        fm = QFontMetrics(f)
        for i, line in enumerate(wrap2(self.title, fm, int(self.w - 26))):
            p.drawText(QPointF(16, 17 + i * 14), line)
        f2 = QFont()
        f2.setPointSize(8)
        p.setFont(f2)
        p.setPen(QColor(self.muted))
        p.drawText(QPointF(16, self.h - 9), self.subtitle)
        # pips de nível (4)
        for k in range(4):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self.border) if k < self.pips else QColor(self.muted + "55"))
            p.drawEllipse(QPointF(self.w - 14 - (3 - k) * 11, self.h - 13), 4, 4)
        if self.badge:
            p.setPen(QColor(self.text))
            p.drawText(QPointF(self.w - 22, 15), self.badge)

    def mousePressEvent(self, e):  # noqa: N802
        if self._click:
            self._click(self.aid)

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        if self._double:
            self._double(self.aid)


class EdgeItem(QGraphicsPathItem):
    """Aresta curva com seta. `set_state`: 'normal', 'active' ou 'dim'."""

    def __init__(self, src: str, dst: str, p1: QPointF, p2: QPointF, color: str, label: str = "", width: float = 1.8):
        super().__init__()
        self.src, self.dst, self.color, self.base_w = src, dst, color, width
        path = QPainterPath(p1)
        mx = (p1.x() + p2.x()) / 2
        path.cubicTo(QPointF(mx, p1.y()), QPointF(mx, p2.y()), p2)
        self.setPath(path)
        self.setZValue(1)
        self.head = QPolygonF([p2, QPointF(p2.x() - 10, p2.y() - 5), QPointF(p2.x() - 10, p2.y() + 5)])
        self.label = label
        self.mid = QPointF(mx, (p1.y() + p2.y()) / 2)
        self.set_state("normal")

    def set_state(self, state: str) -> None:
        self.state = state
        c = QColor(self.color)
        c.setAlphaF({"normal": 0.38, "active": 1.0, "dim": 0.08}[state])
        self.setPen(QPen(c, self.base_w * (1.9 if state == "active" else 1.0), Qt.SolidLine, Qt.RoundCap))
        self.update()

    def paint(self, p: QPainter, o, w=None) -> None:  # noqa: ANN001
        super().paint(p, o, w)
        c = QColor(self.color)
        c.setAlphaF({"normal": 0.7, "active": 1.0, "dim": 0.10}[self.state])
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawPolygon(self.head)
        if self.label and self.state != "dim":
            f = QFont()
            f.setPointSize(8)
            p.setFont(f)
            p.setPen(c)
            p.drawText(QPointF(self.mid.x() - 40, self.mid.y() - 7), self.label)


class ZoomView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        if scene.parent() is None:
            scene.setParent(self)   # evita destruir a cena antes da vista (crash ao encerrar)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.autofit = False

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if self.autofit and self.scene() is not None and not self.scene().sceneRect().isEmpty():
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

    def wheelEvent(self, e):  # noqa: N802
        self.autofit = False
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)
