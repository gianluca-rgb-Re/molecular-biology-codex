"""Tela inicial: perfil do pesquisador, XP, sequência, missões, conquistas e progresso por trilha."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import gamify
from ..study import LEVEL_NAMES, all_levels, missions
from .common import MASTERY_COLORS, MASTERY_SYMBOL, Context, cat_color, cat_icon


def _card(title: str, color: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    if color:
        f.setStyleSheet(f"QFrame#card {{ border-top:3px solid {color}; }}")
    lay = QVBoxLayout(f)
    h = QLabel(title)
    h.setObjectName("h")
    lay.addWidget(h)
    return f, lay


class HomeView(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        outer = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        outer.addWidget(self.scroll)
        ctx.dataChanged.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        ctx, lib, db = self.ctx, self.ctx.lib, self.ctx.db
        levels = all_levels(lib, db)
        prof = gamify.profile(lib, db)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setSpacing(14)

        # ---- herói: perfil do pesquisador
        hero = QFrame()
        hero.setObjectName("hero")
        hl = QHBoxLayout(hero)
        avatar = QLabel(f"{prof.level}")
        avatar.setFixedSize(78, 78)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("background:#4cc2b0; color:#0b0f14; border-radius:39px; font-size:26pt; font-weight:bold;")
        mid = QVBoxLayout()
        t = QLabel("Molecular Biology Codex")
        t.setObjectName("big")
        rank = QLabel(f"<b>{prof.rank}</b> · nível {prof.level} · {prof.xp} XP")
        bar = QProgressBar()
        bar.setMaximum(prof.xp_for_next)
        bar.setValue(prof.xp_in_level)
        bar.setFormat(f"{prof.xp_in_level} / {prof.xp_for_next} XP para o nível {prof.level + 1}")
        bar.setFixedHeight(22)
        parts = " · ".join(f"{k}: {v}" for k, v in gamify.xp_breakdown(lib, db).items() if v)
        bar.setToolTip("XP por origem — " + (parts or "ainda nenhum"))
        mid.addWidget(t)
        mid.addWidget(rank)
        mid.addWidget(bar)
        streak = QLabel(f"<span style='font-size:22pt'>🔥</span><br><b>{prof.streak}</b> dia(s)<br>"
                        f"<span style='color:#9aa4b2'>recorde {prof.best_streak}</span>")
        streak.setAlignment(Qt.AlignCenter)
        hl.addWidget(avatar)
        hl.addLayout(mid, 1)
        hl.addWidget(streak)
        grid.addWidget(hero, 0, 0, 1, 3)

        # ---- continuar / revisar
        c, l = _card("▶ Continuar estudando", "#4cc2b0")
        last = db.get_setting("last_article")
        target = last if last in lib.articles else "eukaryotic-transcription"
        if target in lib.articles:
            b = QPushButton(("Retomar: " if last in lib.articles else "Começar: ") + lib.articles[target].title)
            b.setObjectName("primary")
            b.clicked.connect(lambda _=False, i=target: ctx.openArticle.emit(i))
            l.addWidget(b)
        due, diff = len(db.due_card_ids()), len(db.difficult_item_ids())
        l.addWidget(QLabel(f"🃏 {due} cartão(ões) vencido(s)  ·  ♻ {diff} item(ns) com dificuldade"))
        b2 = QPushButton("Ir para o Modo de estudo")
        b2.clicked.connect(lambda: ctx.gotoView.emit("study"))
        l.addWidget(b2)
        grid.addWidget(c, 1, 0)

        # ---- missões
        c, l = _card("🎯 Missões", "#e0a458")
        ms = missions(lib, db, levels)
        for m in ms:
            b = QPushButton(m["text"])
            b.clicked.connect((lambda _=False, i=m["target"]: ctx.openArticle.emit(i)) if m["target"]
                              else (lambda _=False: ctx.gotoView.emit("study")))
            l.addWidget(b)
        l.addWidget(QLabel("Seguem a árvore de pré-requisitos; você pode ler qualquer artigo a qualquer momento."))
        grid.addWidget(c, 1, 1)

        # ---- dúvidas
        c, l = _card("❓ Dúvidas pendentes", "#d9534f")
        dl = QListWidget()
        dl.setMaximumHeight(120)
        for d in db.doubts():
            it = QListWidgetItem(f"{lib.articles[d['article_id']].title if d['article_id'] in lib.articles else d['article_id']}: {d['text'][:70]}")
            it.setData(Qt.UserRole, (d["id"], d["article_id"]))
            dl.addItem(it)
        dl.itemDoubleClicked.connect(lambda it: ctx.openArticle.emit(it.data(Qt.UserRole)[1]))
        l.addWidget(dl)
        res = QPushButton("Marcar como resolvida")

        def resolve() -> None:
            it = dl.currentItem()
            if it:
                db.resolve_doubt(it.data(Qt.UserRole)[0])
                ctx.dataChanged.emit()
        res.clicked.connect(resolve)
        l.addWidget(res)
        grid.addWidget(c, 1, 2)

        # ---- progresso por trilha
        c, l = _card("🗺 Progresso por trilha")
        for cat, arts in lib.by_category().items():
            row = QHBoxLayout()
            name = QLabel(f"{cat_icon(cat)} {cat}")
            name.setMinimumWidth(260)
            pb = QProgressBar()
            tot = 4 * len(arts)
            pb.setMaximum(tot)
            pb.setValue(sum(levels[a.id] for a in arts))
            pb.setFormat(f"{sum(1 for a in arts if levels[a.id] >= 3)}/{len(arts)} compreendidos")
            pb.setStyleSheet(f"QProgressBar::chunk {{ background:{cat_color(cat)}; border-radius:5px; }}")
            row.addWidget(name)
            row.addWidget(pb, 1)
            l.addLayout(row)
        counts = "  ".join(f"<span style='color:{MASTERY_COLORS[k]}'>{MASTERY_SYMBOL[k]} {LEVEL_NAMES[k]}: "
                           f"{sum(1 for v in levels.values() if v == k)}</span>" for k in range(5))
        l.addWidget(QLabel(counts))
        grid.addWidget(c, 2, 0, 1, 2)

        # ---- genoteca resumo
        from .. import genoteca
        gs = genoteca.summary(db)
        c, l = _card("🧬 Genoteca", "#d9534f")
        l.addWidget(QLabel(f"{gs['species']} espécie(s) · {gs['genes']} gene(s) · {gs['bgcs']} BGC(s) · {gs['stages']} evidência(s)"))
        b = QPushButton("Abrir Laboratório")
        b.clicked.connect(lambda: ctx.gotoView.emit("lab"))
        l.addWidget(b)
        grid.addWidget(c, 2, 2)

        # ---- conquistas
        c, l = _card("🏅 Conquistas")
        wrap = QGridLayout()
        for k, (name, desc, done) in enumerate(gamify.achievements(lib, db)):
            lab = QLabel(name)
            lab.setObjectName("badge" if done else "badgeoff")
            lab.setToolTip(desc + (" — conquistada" if done else " — bloqueada"))
            wrap.addWidget(lab, k // 5, k % 5)
        l.addLayout(wrap)
        grid.addWidget(c, 3, 0, 1, 3)

        # ---- recentes e atalhos
        c, l = _card("🆕 Adicionados recentemente")
        for a in sorted(lib.articles.values(), key=lambda a: a.added, reverse=True)[:5]:
            b = QPushButton(f"{cat_icon(a.category)} {a.title}")
            b.clicked.connect(lambda _=False, i=a.id: ctx.openArticle.emit(i))
            l.addWidget(b)
        grid.addWidget(c, 4, 0, 1, 2)
        c, l = _card("⚡ Atalhos")
        for text, view in (("🔎 Busca (Ctrl+K)", "search"), ("🗺 Mapa", "map"), ("🌳 Árvore", "tree"),
                           ("🧠 Estudo", "study"), ("🧪 Laboratório", "lab")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, v=view: ctx.gotoView.emit(v))
            l.addWidget(b)
        grid.addWidget(c, 4, 2)
        grid.setRowStretch(5, 1)
        self.scroll.setWidget(body)
