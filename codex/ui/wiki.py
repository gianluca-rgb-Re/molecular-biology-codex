"""Tela da Wiki: árvore de categorias, busca, artigo, referências, relações e notas."""
from __future__ import annotations
import html
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTabWidget,
                               QTextBrowser, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..content import RELATION_TYPES, LEVELS, format_reference
from ..render import reference_html, render_article
from ..study import all_levels, LEVEL_NAMES
from PySide6.QtGui import QColor
from .common import ArticleBrowser, Context, MASTERY_SYMBOL, ZoomDialog, cat_color, cat_icon


class WikiView(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.current: str | None = None
        self.history: list[str] = []
        self.hist_pos = -1
        self.cited: list[str] = []
        self.note_id: int | None = None
        self._build()
        ctx.dataChanged.connect(self.refresh_tree)
        ctx.themeChanged.connect(lambda _t: self.current and self.open_article(self.current, push=False))
        self.refresh_tree()

    # ------------------------------------------------------------------- UI
    def _build(self) -> None:
        # esquerda
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar conceito, sigla, proteína, técnica… (Ctrl+K)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.on_search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._tree_clicked)
        self.results = QListWidget()
        self.results.itemClicked.connect(lambda it: self.open_article(it.data(Qt.UserRole)))
        self.results.hide()
        self.fav_only = QPushButton("★ Favoritos")
        self.fav_only.setCheckable(True)
        self.fav_only.toggled.connect(lambda _v: self.refresh_tree())
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.search)
        ll.addWidget(self.fav_only)
        ll.addWidget(self.tree, 1)
        ll.addWidget(self.results, 1)
        # centro
        self.btn_back = QPushButton("◀")
        self.btn_fwd = QPushButton("▶")
        self.btn_back.clicked.connect(lambda: self._nav(-1))
        self.btn_fwd.clicked.connect(lambda: self._nav(1))
        self.btn_fav = QPushButton("☆ Favoritar")
        self.btn_fav.clicked.connect(self.toggle_fav)
        self.btn_doubt = QPushButton("? Registrar dúvida")
        self.btn_doubt.clicked.connect(self.add_doubt)
        self.btn_note = QPushButton("✎ Nota")
        self.btn_note.clicked.connect(lambda: self.side.setCurrentIndex(2))
        self.layer = QComboBox()
        self.layer.addItems(["Todas as camadas", "Camada 1 — Entender", "Camada 2 — Mecanismo",
                             "Camada 3 — Pensar como pesquisador"])
        self.layer.currentIndexChanged.connect(lambda _i: self.current and self.open_article(self.current, push=False))
        self.mastery = QLabel("")
        self.mastery.setObjectName("muted")
        self.cap = QComboBox()
        self.cap.addItems(["Sem limite", "Limitar a: Em estudo", "Limitar a: Compreendido"])
        self.cap.setToolTip("Reavalie seu domínio: o nível calculado nunca excede este limite.")
        self.cap.activated.connect(self._set_cap)
        bar = QHBoxLayout()
        for w in (self.btn_back, self.btn_fwd, self.btn_fav, self.btn_doubt, self.btn_note, self.layer):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.mastery)
        bar.addWidget(self.cap)
        self.crumbs = QLabel("")
        self.crumbs.setObjectName("muted")
        self.browser = ArticleBrowser()
        self.browser.linkClicked.connect(self.on_link)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addLayout(bar)
        cl.addWidget(self.crumbs)
        cl.addWidget(self.browser, 1)
        # direita
        self.side = QTabWidget()
        self.ref_list = QListWidget()
        self.ref_list.currentRowChanged.connect(self._show_ref_row)
        self.ref_detail = ArticleBrowser()
        self.ref_detail.linkClicked.connect(lambda u: QDesktopServices.openUrl(u))
        refs = QWidget()
        rl = QVBoxLayout(refs)
        rl.addWidget(self.ref_list, 1)
        rl.addWidget(self.ref_detail, 2)
        self.related = ArticleBrowser()
        self.related.linkClicked.connect(self.on_link)
        self.note_list = QListWidget()
        self.note_list.currentRowChanged.connect(self._select_note)
        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText("Escreva sua nota pessoal sobre este artigo…")
        b_new = QPushButton("Nova")
        b_save = QPushButton("Salvar")
        b_del = QPushButton("Excluir")
        b_new.clicked.connect(self._new_note)
        b_save.clicked.connect(self._save_note)
        b_del.clicked.connect(self._del_note)
        notes = QWidget()
        nl = QVBoxLayout(notes)
        nl.addWidget(self.note_list, 1)
        nl.addWidget(self.note_edit, 1)
        nb = QHBoxLayout()
        for b in (b_new, b_save, b_del):
            nb.addWidget(b)
        nl.addLayout(nb)
        self.side.addTab(refs, "Referências")
        self.side.addTab(self.related, "Relações")
        self.side.addTab(notes, "Notas")
        left.setMinimumWidth(290)
        self.side.setMinimumWidth(330)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(center)
        split.addWidget(self.side)
        split.setSizes([300, 720, 360])
        split.setStretchFactor(1, 1)
        lay = QHBoxLayout(self)
        lay.addWidget(split)

    # ----------------------------------------------------------------- tree
    def refresh_tree(self) -> None:
        levels = all_levels(self.ctx.lib, self.ctx.db)
        favs = self.ctx.db.favorites()
        self.tree.clear()
        for cat, arts in self.ctx.lib.by_category().items():
            ok_n = sum(1 for a in arts if levels[a.id] >= 3)
            node = QTreeWidgetItem([f"{cat_icon(cat)} {cat}  ({ok_n}/{len(arts)})"])
            node.setForeground(0, QColor(cat_color(cat)))
            f = node.font(0)
            f.setBold(True)
            node.setFont(0, f)
            shown = 0
            for a in arts:
                if self.fav_only.isChecked() and a.id not in favs:
                    continue
                star = " ★" if a.id in favs else ""
                it = QTreeWidgetItem([f"{MASTERY_SYMBOL[levels[a.id]]} {a.title}{star}"])
                it.setData(0, Qt.UserRole, a.id)
                node.addChild(it)
                shown += 1
            if shown:
                self.tree.addTopLevelItem(node)
                node.setExpanded(True)
        self._update_header_state()

    def _tree_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        aid = item.data(0, Qt.UserRole)
        if aid:
            self.open_article(aid)

    def on_search(self, text: str) -> None:
        if not text.strip():
            self.results.hide()
            self.tree.show()
            return
        hits = self.ctx.index.search(text)
        self.results.clear()
        for h in hits:
            a = self.ctx.lib.articles[h.article_id]
            it = QListWidgetItem(f"{a.title}\n   {h.snippet[:110]}")
            it.setData(Qt.UserRole, a.id)
            self.results.addItem(it)
        if not hits:
            self.results.addItem(QListWidgetItem("Nenhum resultado. Tente a sigla, o termo em inglês ou um sinônimo."))
        self.tree.hide()
        self.results.show()

    # ------------------------------------------------------------- articles
    def open_article(self, aid: str, push: bool = True, anchor: str = "") -> None:
        art = self.ctx.lib.get(aid)
        if art is None:
            QMessageBox.warning(self, "Artigo não encontrado",
                                f"O artigo '{aid}' não existe na base de conhecimento.\n"
                                "Verifique o link ou execute a validação de conteúdo (Ajuda).")
            return
        if push and aid != self.current:
            self.history = self.history[: self.hist_pos + 1] + [aid]
            self.hist_pos = len(self.history) - 1
        self.current = aid
        self.ctx.db.touch_article(aid)
        layer = self.layer.currentIndex() or None
        try:
            lv = all_levels(self.ctx.lib, self.ctx.db)[aid]
            body, self.cited = render_article(art, self.ctx.lib, self.ctx.theme, layer, self.ctx.fig_dirs, lv,
                                              f"{MASTERY_SYMBOL[lv]} {LEVEL_NAMES[lv]}")
        except Exception as e:  # noqa: BLE001 - página incompleta nunca deve derrubar o app
            body, self.cited = f"<h2>Não foi possível exibir este artigo</h2><p>{html.escape(str(e))}</p>", []
        self.browser.document().setDefaultStyleSheet(self.ctx.css())
        self.browser.setHtml(body)
        if anchor:
            self.browser.scrollToAnchor(anchor)
        self.crumbs.setText(" › ".join(x for x in [art.category, art.subcategory, art.title] if x))
        self._fill_refs()
        self._fill_related(aid)
        self._fill_notes()
        self._update_header_state()

    def _update_header_state(self) -> None:
        aid = self.current
        self.btn_back.setEnabled(self.hist_pos > 0)
        self.btn_fwd.setEnabled(self.hist_pos < len(self.history) - 1)
        if not aid or aid not in self.ctx.lib.articles:
            return
        self.btn_fav.setText("★ Favorito" if self.ctx.db.is_favorite(aid) else "☆ Favoritar")
        lv = all_levels(self.ctx.lib, self.ctx.db)[aid]
        self.mastery.setText(f"Domínio: {MASTERY_SYMBOL[lv]} {LEVEL_NAMES[lv]}")
        row = self.ctx.db.progress_all().get(aid)
        cap = row["manual_cap"] if row else None
        self.cap.setCurrentIndex({None: 0, 2: 1, 3: 2}.get(cap, 0))

    def _nav(self, d: int) -> None:
        pos = self.hist_pos + d
        if 0 <= pos < len(self.history):
            self.hist_pos = pos
            self.open_article(self.history[pos], push=False)

    def toggle_fav(self) -> None:
        if self.current:
            self.ctx.db.toggle_favorite(self.current)
            self._update_header_state()
            self.refresh_tree()

    def _set_cap(self, idx: int) -> None:
        if self.current:
            self.ctx.db.set_manual_cap(self.current, {0: None, 1: 2, 2: 3}[idx])
            self._update_header_state()
            self.ctx.dataChanged.emit()

    def add_doubt(self) -> None:
        if not self.current:
            return
        text, ok = QInputDialog.getMultiLineText(self, "Registrar dúvida", "Qual é a sua dúvida sobre este artigo?")
        if ok and text.strip():
            self.ctx.db.add_doubt(self.current, text.strip())
            self.ctx.dataChanged.emit()

    # ----------------------------------------------------------- side panels
    def _fill_refs(self) -> None:
        self.ref_list.clear()
        for i, k in enumerate(self.cited, 1):
            r = self.ctx.lib.refs.get(k)
            if r:
                st = (r.get("verification") or {}).get("status", "pendente")
                mark = {"verificada": "✔", "verificada_parcial": "◐"}.get(st, "?")
                self.ref_list.addItem(f"[{i}] {mark} {format_reference(r)[:90]}…")
            else:
                self.ref_list.addItem(f"[{i}] ✖ {k} (não está no catálogo)")
        self.ref_detail.document().setDefaultStyleSheet(self.ctx.css())
        self.ref_detail.setHtml("<p class='muted'>✔ verificada · ◐ parcialmente verificada · ? pendente</p>")

    def _show_ref_row(self, row: int) -> None:
        if 0 <= row < len(self.cited):
            self.ref_detail.setHtml(reference_html(self.cited[row], self.ctx.lib, self.ctx.theme))

    def _fill_related(self, aid: str) -> None:
        lib = self.ctx.lib
        art = lib.articles[aid]
        a = lambda i: f"<a href='codex://article/{i}'>{html.escape(lib.articles[i].title)}</a>"  # noqa: E731
        out = ["<h3>Este conceito…</h3><ul>"]
        out += [f"<li>{RELATION_TYPES.get(r.get('type', ''), r.get('type'))} {a(r['to'])}</li>"
                for r in art.relations if r.get("to") in lib.articles]
        out.append("</ul><h3>Outros conceitos…</h3><ul>")
        out += [f"<li>{a(i)} {RELATION_TYPES.get(t, t)} este conceito</li>" for i, t in lib.incoming_relations(aid)]
        out.append("</ul><h3>Mencionado em (backlinks)</h3><ul>")
        out += [f"<li>{a(i)}</li>" for i in sorted(lib.backlinks.get(aid, []))]
        out.append("</ul>")
        self.related.document().setDefaultStyleSheet(self.ctx.css())
        self.related.setHtml("".join(out))

    def _fill_notes(self) -> None:
        self.note_list.clear()
        self.note_id = None
        self.note_edit.clear()
        for n in self.ctx.db.notes(self.current):
            it = QListWidgetItem(f"{n['created'][:10]} — {n['text'][:50]}")
            it.setData(Qt.UserRole, n["id"])
            self.note_list.addItem(it)

    def _select_note(self, row: int) -> None:
        it = self.note_list.item(row)
        if it:
            self.note_id = it.data(Qt.UserRole)
            for n in self.ctx.db.notes(self.current):
                if n["id"] == self.note_id:
                    self.note_edit.setPlainText(n["text"])

    def _new_note(self) -> None:
        self.note_id = None
        self.note_edit.clear()
        self.note_edit.setFocus()

    def _save_note(self) -> None:
        text = self.note_edit.toPlainText().strip()
        if not text or not self.current:
            return
        if self.note_id is None:
            self.note_id = self.ctx.db.add_note(self.current, text)
        else:
            self.ctx.db.update_note(self.note_id, text)
        keep = self.note_id
        self._fill_notes()
        self.note_id = keep

    def _del_note(self) -> None:
        if self.note_id is not None:
            self.ctx.db.delete_note(self.note_id)
            self._fill_notes()

    # ----------------------------------------------------------------- links
    def on_link(self, url: QUrl) -> None:
        s = url.toString()
        if s.startswith("codex://article/"):
            self.open_article(s.rsplit("/", 1)[1])
        elif s.startswith("codex://ref/"):
            key = s.rsplit("/", 1)[1]
            if key in self.cited:
                self.side.setCurrentIndex(0)
                self.ref_list.setCurrentRow(self.cited.index(key))
        elif s.startswith("codex://fig/"):
            name = s.rsplit("/", 1)[1]
            for d in self.ctx.fig_dirs:
                if (Path(d) / name).exists():
                    ZoomDialog(Path(d) / name, self).exec()
                    break
        elif s.startswith("http"):
            QDesktopServices.openUrl(url)
        elif s.startswith("#"):
            self.browser.scrollToAnchor(s[1:])
