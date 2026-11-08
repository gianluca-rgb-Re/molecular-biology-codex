"""Figuras: diagramas de proteínas (blocos de domínios) e gráficos de barras. Desenham em qualquer QPainter (tela, PNG, SVG, PDF)."""
from __future__ import annotations
import zlib

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen

from .analysis import Rec, source_label
from .antismash import display_name

_KEY_COLORS = (("KS", "#d9534f"), ("AT", "#e0a458"), ("Acyl_transf", "#e0a458"), ("DH", "#2ea66b"), ("ER", "#3fb0c9"), ("ADH_", "#3fb0c9"),
               ("KR", "#9b59b6"), ("PP", "#4a90d9"), ("ACP", "#4a90d9"), ("MT", "#e67e9c"), ("Methyltransf", "#e67e9c"), ("TE", "#6fcf6f"),
               ("Cond", "#7a8fd9"), ("AMP", "#e07a5f"), ("PCP", "#4cc2b0"), ("SAT", "#c9a227"), ("PT", "#8e9aaf"))
INK, MUTED, PAPER = QColor("#1c2430"), QColor("#5b6675"), QColor("#ffffff")


def domain_color(name: str) -> QColor:
    u = name.upper().replace("PKS_", "")
    for k, c in _KEY_COLORS:
        if u.startswith(k.upper()) or k.upper() in u[:6]:
            return QColor(c)
    h = zlib.crc32(name.encode()) & 0xFFFFFF
    return QColor.fromHsv(h % 360, 110, 200)


def _font(pt: float, bold: bool = False) -> QFont:
    f = QFont("DejaVu Sans")
    f.setPointSizeF(pt)
    f.setBold(bold)
    return f


def paint_architectures(p: QPainter, recs: list[Rec], width: int, source: str = "antismash", title: str = "") -> int:
    """Uma linha por proteína: comprimento proporcional (aa), blocos de domínios na ordem original, nomes originais. Devolve a altura usada."""
    p.setRenderHint(QPainter.Antialiasing)
    y, left, right = 8, 230, 24
    bar_w = width - left - right
    max_aa = max([r.aa for r in recs] + [1])
    if title:
        p.setFont(_font(11, True))
        p.setPen(INK)
        p.drawText(QRectF(8, y, width - 16, 22), Qt.AlignVCenter, title)
        y += 30
    names: dict[str, QColor] = {}
    fm = QFontMetrics(_font(7.5))
    for r in recs:
        p.setFont(_font(9, True))
        p.setPen(INK)
        p.drawText(QRectF(8, y, left - 14, 16), Qt.AlignVCenter, r.locus)
        p.setFont(_font(7.5))
        p.setPen(MUTED)
        p.drawText(QRectF(8, y + 16, left - 14, 14), Qt.AlignVCenter, f"{r.gene_class} · {r.aa} aa · {r.exons} éxons")
        p.drawText(QRectF(8, y + 29, left - 14, 14), Qt.AlignVCenter, f"BGC: {','.join(r.bgc_types) or '—'}")
        L = bar_w * r.aa / max_aa
        p.setPen(QPen(INK, 1))
        p.setBrush(QColor("#eef1f5"))
        p.drawRoundedRect(QRectF(left, y + 6, max(4, L), 22), 3, 3)
        for d in r.doms(source):
            if d.get("end", 0) <= d.get("start", 0):
                continue
            x1, x2 = left + bar_w * d["start"] / max_aa, left + bar_w * d["end"] / max_aa
            dn = display_name(d["name"])
            c = domain_color(dn)
            names.setdefault(dn, c)
            rect = QRectF(x1, y + 3, max(3, x2 - x1), 28)
            p.setPen(QPen(INK, 1))
            p.setBrush(c)
            p.drawRect(rect)
            p.setFont(_font(7.5, True))
            p.setPen(QColor("#ffffff") if c.lightness() < 150 else INK)
            p.drawText(rect, Qt.AlignCenter, fm.elidedText(dn, Qt.ElideRight, int(rect.width()) - 2))
        y += 52
    # régua de aminoácidos
    p.setPen(QPen(MUTED, 1))
    p.setFont(_font(7))
    step = 500 if max_aa > 1500 else 250 if max_aa > 600 else 100
    for a in range(0, max_aa + 1, step):
        x = left + bar_w * a / max_aa
        p.drawLine(int(x), y, int(x), y + 4)
        p.drawText(QRectF(x - 20, y + 4, 40, 12), Qt.AlignCenter, str(a))
    p.drawText(QRectF(8, y, left - 14, 14), Qt.AlignVCenter, "Posição (aa)")
    y += 24
    # legenda: nome original + fonte
    p.setFont(_font(7.5))
    x = 8
    for n, c in names.items():
        w = fm.horizontalAdvance(n) + 26
        if x + w > width - 8:
            x, y = 8, y + 16
        p.setPen(QPen(INK, 1))
        p.setBrush(c)
        p.drawRect(QRectF(x, y + 2, 12, 10))
        p.setPen(INK)
        p.drawText(QRectF(x + 16, y, w, 14), Qt.AlignVCenter, n)
        x += w + 6
    y += 20
    p.setPen(MUTED)
    srcs = sorted({source_label(d) for r in recs for d in r.doms(source)})
    p.drawText(QRectF(8, y, width - 16, 14), Qt.AlignVCenter, "Fonte dos domínios: " + (", ".join(srcs) or "—") + ". Nomes do antiSMASH sem o prefixo «PKS_».")
    return y + 22


def architectures_height(recs: list[Rec], title: str = "") -> int:
    return (30 if title else 8) + 52 * len(recs) + 24 + 20 * 3 + 30


def render_architectures_image(recs: list[Rec], width: int = 1400, source: str = "antismash", title: str = "") -> QImage:
    h = architectures_height(recs, title) + 40
    img = QImage(width, h, QImage.Format_ARGB32)
    img.fill(PAPER)
    p = QPainter(img)
    used = paint_architectures(p, recs, width, source, title)
    p.end()
    return img.copy(0, 0, width, min(h, used + 4))


def save_architectures(recs: list[Rec], path: str, source: str = "antismash", title: str = "", width: int = 1400) -> None:
    """PNG ou SVG conforme a extensão do arquivo."""
    if path.lower().endswith(".svg"):
        from PySide6.QtSvg import QSvgGenerator
        h = architectures_height(recs, title) + 40
        g = QSvgGenerator()
        g.setFileName(path)
        g.setSize(QSize(width, h))
        g.setViewBox(QRectF(0, 0, width, h))
        g.setTitle(title or "Arquiteturas de domínios")
        g.setDescription("Molecular Biology Codex: nomes de domínios = identificadores originais do arquivo")
        p = QPainter(g)
        p.fillRect(0, 0, width, h, PAPER)
        paint_architectures(p, recs, width, source, title)
        p.end()
    else:
        render_architectures_image(recs, width, source, title).save(path)


def render_bar_chart(items: list[tuple[str, float]], title: str, width: int = 900, unit: str = "", color: str = "#4a90d9", percent_of: float | None = None) -> QImage:
    """Gráfico de barras horizontais simples (rótulos à esquerda, valores à direita)."""
    rows = max(1, len(items))
    h = 46 + rows * 24 + 12
    img = QImage(width, h, QImage.Format_ARGB32)
    img.fill(PAPER)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setFont(_font(10, True))
    p.setPen(INK)
    p.drawText(QRectF(8, 8, width - 16, 22), Qt.AlignVCenter, title)
    left, right = 250, 110
    top = max([v for _l, v in items] + [1])
    fm = QFontMetrics(_font(8.5))
    for i, (lab, v) in enumerate(items):
        y = 40 + i * 24
        p.setFont(_font(8.5))
        p.setPen(INK)
        p.drawText(QRectF(8, y, left - 14, 20), Qt.AlignVCenter | Qt.AlignRight, fm.elidedText(lab, Qt.ElideRight, left - 20))
        w = (width - left - right) * v / top
        p.setPen(Qt.NoPen)
        p.setBrush(domain_color(lab) if color == "auto" else QColor(color))
        p.drawRect(QRectF(left, y + 2, max(2, w), 16))
        txt = f"{v:g}{unit}" + (f" ({100 * v / percent_of:.0f}%)" if percent_of else "")
        p.setPen(MUTED)
        p.drawText(QRectF(left + w + 6, y, right + 40, 20), Qt.AlignVCenter, txt)
    p.end()
    return img
