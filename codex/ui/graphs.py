"""Árvore de habilidades em trilhas por categoria e mapa conceitual."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem,
                               QHBoxLayout, QLabel, QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from ..content import RELATION_TYPES, LEVELS
from ..render import PALETTES
from ..study import LEVEL_NAMES, all_levels, is_recommended_first
from .common import (LEVEL_STARS, MASTERY_COLORS, MASTERY_SYMBOL, RELATION_COLORS, Context, cat_color, cat_icon)
from .gfx import EdgeItem, NodeItem, ZoomView


class SkillTreeView(QWidget):
    NW, NH, GX, GY, LANE_PAD, LABEL_W = 218, 58, 70, 14, 22, 210

    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.sel: str | None = None
        self.nodes: dict[str, NodeItem] = {}
        self.edges: list[EdgeItem] = []
        self.scene = QGraphicsScene()
        self.view = ZoomView(self.scene)
        self.scene.selectionChanged.connect(lambda: None)
        self.info = QTextBrowser()
        self.info.setOpenLinks(False)
        self.info.anchorClicked.connect(lambda u: ctx.openArticle.emit(u.toString().rsplit("/", 1)[1])
                                        if u.toString().startswith("codex://article/") else None)
        top = QHBoxLayout()
        title = QLabel("🌳 Árvore de habilidades")
        title.setObjectName("h")
        hint = QLabel("Clique num nó para ver o caminho de pré-requisitos; duplo clique abre o artigo. "
                      "Nós com brilho dourado são os próximos recomendados.")
        hint.setObjectName("muted")
        top.addWidget(title)
        top.addWidget(hint, 1)
        for text, fn in (("−", lambda: self.zoom(1 / 1.2)), ("+", lambda: self.zoom(1.2)),
                         ("Ajustar", self.fit), ("Focar", self.focus_default)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            top.addWidget(b)
        self.legend = QLabel()
        split = QSplitter()
        split.addWidget(self.view)
        split.addWidget(self.info)
        split.setSizes([1000, 320])
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(split, 1)
        lay.addWidget(self.legend)
        ctx.dataChanged.connect(self.rebuild)
        ctx.themeChanged.connect(lambda _t: self.rebuild())
        self.rebuild()

    def fit(self) -> None:
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self.focus_default()

    def zoom(self, f: float) -> None:
        self.view.scale(f, f)

    def focus_default(self) -> None:
        """Zoom legível, centrado no nó selecionado ou no primeiro recomendado."""
        self.view.resetTransform()
        self.view.scale(0.9, 0.9)
        target = self.sel if self.sel in self.nodes else next(
            (i for i, n in self.nodes.items() if n.glow), next(iter(self.nodes), None))
        if target:
            self.view.centerOn(self.nodes[target])

    # ------------------------------------------------------------ layout
    def _depths(self) -> dict[str, int]:
        lib, depth = self.ctx.lib, {}

        def d(i: str, stack=()) -> int:
            if i in depth:
                return depth[i]
            if i in stack:
                return 0
            ps = [p for p in lib.articles[i].prereqs if p in lib.articles]
            depth[i] = 0 if not ps else 1 + max(d(p, stack + (i,)) for p in ps)
            return depth[i]
        for i in lib.articles:
            d(i)
        return depth

    def rebuild(self) -> None:
        self.scene.clear()
        self.nodes, self.edges = {}, []
        pal = PALETTES[self.ctx.theme]
        lib = self.ctx.lib
        levels = all_levels(lib, self.ctx.db)
        depth = self._depths()
        cats = list(lib.by_category().keys())
        # posições: trilha (categoria) × coluna (profundidade)
        y = 0.0
        pos: dict[str, QPointF] = {}
        lane_rects: list[tuple[str, float, float]] = []
        for cat in cats:
            arts = [a for a in lib.sorted_articles() if a.category == cat]
            cols: dict[int, list[str]] = {}
            for a in arts:
                cols.setdefault(depth[a.id], []).append(a.id)
            rows = max(len(v) for v in cols.values())
            h = rows * (self.NH + self.GY) - self.GY + 2 * self.LANE_PAD
            for c, ids in cols.items():
                for r, i in enumerate(ids):
                    pos[i] = QPointF(self.LABEL_W + c * (self.NW + self.GX), y + self.LANE_PAD + r * (self.NH + self.GY))
            lane_rects.append((cat, y, h))
            y += h + 14
        max_x = max((p.x() for p in pos.values()), default=0) + self.NW + 30
        for cat, ly, lh in lane_rects:
            col = QColor(cat_color(cat))
            band = QGraphicsRectItem(QRectF(0, ly, max_x, lh))
            band.setBrush(QBrush(QColor(col.red(), col.green(), col.blue(), 22)))
            band.setPen(QColor(col.red(), col.green(), col.blue(), 70))
            band.setZValue(0)
            self.scene.addItem(band)
            t = QGraphicsSimpleTextItem(f"{cat_icon(cat)}  {cat}")
            f = QFont()
            f.setPointSize(10)
            f.setBold(True)
            t.setFont(f)
            t.setBrush(QBrush(col))
            t.setPos(12, ly + lh / 2 - 10)
            t.setZValue(1)
            self.scene.addItem(t)
        for i, a in lib.articles.items():
            for p in a.prereqs:
                if p in pos and i in pos:
                    e = EdgeItem(p, i, pos[p] + QPointF(self.NW, self.NH / 2), pos[i] + QPointF(0, self.NH / 2),
                                 cat_color(lib.articles[p].category))
                    self.scene.addItem(e)
                    self.edges.append(e)
        for i, a in lib.articles.items():
            lv = levels[i]
            rec = lv < 3 and not is_recommended_first(a, levels) and (lv > 0 or True)
            locked = is_recommended_first(a, levels) and lv == 0
            sub = f"{MASTERY_SYMBOL[lv]} {LEVEL_NAMES[lv]}  {LEVEL_STARS.get(a.level, '')}" + ("  🔒" if locked else "")
            n = NodeItem(i, a.title, sub, self.NW, self.NH, cat_color(a.category), MASTERY_COLORS[lv], pal["panel"],
                         pal["text"], pal["muted"], pips=lv, dashed=locked,
                         glow="#e0b341" if (rec and not locked and lv < 3) else None,
                         on_click=self.select, on_double=self.ctx.openArticle.emit)
            n.setPos(pos[i])
            self.scene.addItem(n)
            self.nodes[i] = n
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20))
        self.legend.setText("  ".join(f"<span style='color:{MASTERY_COLORS[k]}'>{MASTERY_SYMBOL[k]} {LEVEL_NAMES[k]}</span>"
                                      for k in range(5)) + "   <span style='color:#e0b341'>■ próximo recomendado</span>"
                            "   <span style='color:#8a95a5'>┄ 🔒 pré-requisitos ainda não estudados (só orientação)</span>")
        self.select(self.sel if self.sel in lib.articles else None)

    # ---------------------------------------------------------- seleção
    def _relatives(self, aid: str) -> tuple[set[str], set[str]]:
        lib = self.ctx.lib
        anc: set[str] = set()
        stack = [aid]
        while stack:
            for p in lib.articles[stack.pop()].prereqs:
                if p in lib.articles and p not in anc:
                    anc.add(p)
                    stack.append(p)
        desc: set[str] = set()
        stack = [aid]
        while stack:
            cur = stack.pop()
            for i, a in lib.articles.items():
                if cur in a.prereqs and i not in desc:
                    desc.add(i)
                    stack.append(i)
        return anc, desc

    def select(self, aid: str | None) -> None:
        self.sel = aid
        lib = self.ctx.lib
        if aid is None:
            for n in self.nodes.values():
                n.dim, n.selected = False, False
                n.update()
            for e in self.edges:
                e.set_state("normal")
            self.info.setHtml("<p>Selecione um nó para ver o resumo e o caminho de pré-requisitos.</p>")
            return
        anc, desc = self._relatives(aid)
        keep = anc | desc | {aid}
        for i, n in self.nodes.items():
            n.dim, n.selected = i not in keep, i == aid
            n.update()
        for e in self.edges:
            on_path = (e.src in anc | {aid} and e.dst in anc | {aid}) or (e.src in desc | {aid} and e.dst in desc | {aid})
            e.set_state("active" if on_path else "dim")
        a = lib.articles[aid]
        levels = all_levels(lib, self.ctx.db)
        pal = PALETTES[self.ctx.theme]
        pre = "".join(f"<li>{MASTERY_SYMBOL[levels[p]]} <a href='codex://article/{p}'>{lib.articles[p].title}</a> "
                      f"<span style='color:{MASTERY_COLORS[levels[p]]}'>({LEVEL_NAMES[levels[p]]})</span></li>"
                      for p in a.prereqs if p in lib.articles) or "<li>Nenhum — ponto de partida.</li>"
        nxt = "".join(f"<li><a href='codex://article/{d}'>{lib.articles[d].title}</a></li>" for d in sorted(
            [i for i, x in lib.articles.items() if aid in x.prereqs]))
        col = cat_color(a.category)
        self.info.document().setDefaultStyleSheet(self.ctx.css())
        self.info.setHtml(
            f"<table width='100%'><tr><td bgcolor='{col}' width='6'></td><td bgcolor='{pal['panel2']}' style='padding:6px'>"
            f"<b style='color:{col}'>{cat_icon(a.category)} {a.category}</b><br><span style='font-size:13pt'><b>{a.title}</b></span><br>"
            f"{LEVEL_STARS.get(a.level, '')} {LEVELS.get(a.level, '')} · "
            f"<span style='color:{MASTERY_COLORS[levels[aid]]}'>{MASTERY_SYMBOL[levels[aid]]} {LEVEL_NAMES[levels[aid]]}</span>"
            f"</td></tr></table><p>{a.summary}</p><h4>Antes de continuar</h4><ul>{pre}</ul>"
            f"<h4>Abre caminho para</h4><ul>{nxt or '<li>—</li>'}</ul>"
            f"<p><a href='codex://article/{aid}'><b>▶ Abrir artigo</b></a></p>")


class ConceptMapView(QWidget):
    NODE_W, NODE_H = 230, 54

    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.center_id: str | None = None
        self.scene = QGraphicsScene()
        self.view = ZoomView(self.scene)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(340)
        self.combo.activated.connect(lambda _i: self.set_center(self.combo.currentData()))
        self.btn_open = QPushButton("Abrir artigo do conceito central")
        self.btn_open.clicked.connect(lambda: self.center_id and ctx.openArticle.emit(self.center_id))
        title = QLabel("🗺 Mapa conceitual")
        title.setObjectName("h")
        top = QHBoxLayout()
        for w in (title, QLabel("Conceito central:"), self.combo, self.btn_open):
            top.addWidget(w)
        top.addStretch(1)
        self.legend = QLabel()
        self.legend.setWordWrap(True)
        hint = QLabel("Setas leem-se «origem → (relação) → destino». Clique num nó para recentralizar; duplo clique abre o artigo.")
        hint.setObjectName("muted")
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(hint)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.legend)
        ctx.dataChanged.connect(self.reload)
        ctx.themeChanged.connect(lambda _t: self.set_center(self.center_id))
        self.reload()

    def reload(self) -> None:
        self.combo.clear()
        for a in self.ctx.lib.sorted_articles():
            self.combo.addItem(f"{cat_icon(a.category)} {a.title}", a.id)
        first = self.center_id if self.center_id in self.ctx.lib.articles else (
            "eukaryotic-transcription" if "eukaryotic-transcription" in self.ctx.lib.articles else
            (self.combo.itemData(0) if self.combo.count() else None))
        self.set_center(first)

    def set_center(self, aid: str | None) -> None:
        self.scene.clear()
        self.center_id = aid
        lib, pal = self.ctx.lib, PALETTES[self.ctx.theme]
        self.legend.setText("  ".join(f"<span style='color:{RELATION_COLORS[k]}'>━▶ {v}</span>" for k, v in RELATION_TYPES.items()))
        if not aid or aid not in lib.articles:
            return
        self.combo.setCurrentIndex(max(0, self.combo.findData(aid)))
        levels = all_levels(lib, self.ctx.db)
        art = lib.articles[aid]
        out = [(r["to"], r["type"]) for r in art.relations if r.get("to") in lib.articles]
        inc = list(lib.incoming_relations(aid))
        h, gap = self.NODE_H, 26

        def ys(n: int) -> list[float]:
            total = n * h + max(0, n - 1) * gap
            return [-total / 2 + k * (h + gap) for k in range(n)]
        lx, rx = -420 - self.NODE_W, 420

        def mk(i: str, x: float, y: float, center=False) -> None:
            a, lv = lib.articles[i], levels[i]
            n = NodeItem(i, a.title, f"{MASTERY_SYMBOL[lv]} {LEVEL_NAMES[lv]}", self.NODE_W, h, cat_color(a.category),
                         pal["accent"] if center else MASTERY_COLORS[lv], pal["panel2"] if center else pal["panel"],
                         pal["text"], pal["muted"], pips=lv, glow=pal["accent"] if center else None,
                         on_click=self.set_center, on_double=self.ctx.openArticle.emit)
            n.setPos(x, y)
            self.scene.addItem(n)
        mk(aid, -self.NODE_W / 2, -h / 2, True)
        for (i, t), y in zip(inc, ys(len(inc))):
            mk(i, lx, y)
            self.scene.addItem(EdgeItem(i, aid, QPointF(lx + self.NODE_W, y + h / 2), QPointF(-self.NODE_W / 2, 0),
                                        RELATION_COLORS.get(t, "#888"), RELATION_TYPES.get(t, t), 2.2))
        for (i, t), y in zip(out, ys(len(out))):
            mk(i, rx, y)
            self.scene.addItem(EdgeItem(aid, i, QPointF(self.NODE_W / 2, 0), QPointF(rx, y + h / 2),
                                        RELATION_COLORS.get(t, "#888"), RELATION_TYPES.get(t, t), 2.2))
        if not inc and not out:
            t = QGraphicsSimpleTextItem("Este conceito ainda não tem relações tipadas cadastradas.")
            t.setBrush(QBrush(QColor(pal["muted"])))
            t.setPos(-150, 60)
            self.scene.addItem(t)
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40))
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
