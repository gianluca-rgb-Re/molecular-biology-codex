"""Janela principal."""
from __future__ import annotations
import html
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
                               QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from .. import gamify
from ..db import UserDB
from ..paths import data_dir, user_content_dir
from ..validate import validate
from .common import Context, qss
from .graphs import ConceptMapView, SkillTreeView
from .home import HomeView
from .lab import LabView
from .studyview import StudyView
from .wiki import WikiView


class MainWindow(QMainWindow):
    NAV = [("home", "🏠  Codex"), ("wiki", "📚  Wiki de conceitos"), ("tree", "🌳  Árvore de habilidades"),
           ("map", "🗺  Mapa conceitual"), ("study", "🧠  Modo de estudo"), ("lab", "🧪  Laboratório")]

    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        from .. import __version__
        self.setWindowTitle(f"Molecular Biology Codex v{__version__}")
        self.resize(1480, 900)
        self.views: dict[str, QWidget] = {
            "home": HomeView(ctx), "wiki": WikiView(ctx), "tree": SkillTreeView(ctx),
            "map": ConceptMapView(ctx), "study": StudyView(ctx), "lab": LabView(ctx)}
        self.stack = QStackedWidget()
        for v in self.views.values():
            self.stack.addWidget(v)
        nav = QWidget()
        nav.setFixedWidth(215)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(0)
        self.nav_btns: dict[str, QPushButton] = {}
        for key, label in self.NAV:
            b = QPushButton(label)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.show_view(k))
            nl.addWidget(b)
            self.nav_btns[key] = b
        nl.addStretch(1)
        root = QWidget()
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(nav)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        ctx.openArticle.connect(self.open_article)
        ctx.gotoView.connect(self.goto)
        self._menus()
        self.apply_theme(ctx.theme)
        self.show_view("home")
        last = ctx.db.get_setting("last_article")
        if last in ctx.lib.articles:      # lembra a página em que o usuário estava
            self.views["wiki"].open_article(last, push=True)
        self.xp_label = QLabel()
        self.statusBar().addPermanentWidget(self.xp_label)
        ctx.dataChanged.connect(self.update_xp)
        self.update_xp()
        self.statusBar().showMessage(f"{len(ctx.lib.articles)} artigos · dados em {data_dir()}")

    def update_xp(self) -> None:
        p = gamify.profile(self.ctx.lib, self.ctx.db)
        self.xp_label.setText(f"🏅 Nv {p.level} · {p.rank} · {p.xp} XP · 🔥 {p.streak} dia(s)")

    # ----------------------------------------------------------- navegação
    def show_view(self, key: str) -> None:
        self.stack.setCurrentWidget(self.views[key])
        for k, b in self.nav_btns.items():
            b.setChecked(k == key)
        if key == "home":
            self.views["home"].rebuild()

    def open_article(self, aid: str) -> None:
        self.show_view("wiki")
        self.views["wiki"].open_article(aid)

    def goto(self, key: str) -> None:
        if key == "search":
            self.show_view("wiki")
            self.views["wiki"].search.setFocus()
            self.views["wiki"].search.selectAll()
        else:
            self.show_view(key)

    # ----------------------------------------------------------------- menus
    def _menus(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("&Arquivo")
        for text, fn in (("Fazer backup do progresso…", self.backup), ("Restaurar backup…", self.restore),
                         ("Exportar notas e dúvidas (Markdown)…", self.export_notes),
                         ("Exportar flashcards (CSV)…", self.export_cards),
                         ("Exportar tudo (JSON)…", self.export_json),
                         ("Abrir pasta de conteúdo do usuário", self.open_user_dir),
                         ("Recarregar conteúdo", self.reload)):
            a = QAction(text, self)
            a.triggered.connect(fn)
            f.addAction(a)
        f.addSeparator()
        q = QAction("Sair", self)
        q.triggered.connect(self.close)
        f.addAction(q)
        v = mb.addMenu("&Exibir")
        t = QAction("Alternar tema escuro/claro", self)
        t.setShortcut(QKeySequence("Ctrl+T"))
        t.triggered.connect(self.toggle_theme)
        v.addAction(t)
        for text, d in (("Aumentar fonte", 1), ("Diminuir fonte", -1)):
            a = QAction(text, self)
            a.triggered.connect(lambda _=False, dd=d: self.change_font(dd))
            v.addAction(a)
        s = QAction("Buscar", self)
        s.setShortcut(QKeySequence("Ctrl+K"))
        s.triggered.connect(lambda: self.goto("search"))
        v.addAction(s)
        h = mb.addMenu("A&juda")
        a = QAction("Validar base de conhecimento…", self)
        a.triggered.connect(self.show_validation)
        h.addAction(a)
        a = QAction("Sobre", self)
        a.triggered.connect(self.about)
        h.addAction(a)

    def apply_theme(self, theme: str) -> None:
        self.ctx.theme = theme
        QApplication.instance().setStyleSheet(qss(theme))
        self.ctx.themeChanged.emit(theme)

    def toggle_theme(self) -> None:
        new = "light" if self.ctx.theme == "dark" else "dark"
        self.ctx.db.set_setting("theme", new)
        self.apply_theme(new)

    def change_font(self, d: int) -> None:
        self.ctx.font_pt = max(8, min(18, self.ctx.font_pt + d))
        self.ctx.db.set_setting("font_pt", str(self.ctx.font_pt))
        self.ctx.themeChanged.emit(self.ctx.theme)

    # ------------------------------------------------------- arquivos/backup
    def _safe(self, fn, ok_msg: str = "") -> None:
        try:
            fn()
            if ok_msg:
                QMessageBox.information(self, "Concluído", ok_msg)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Não foi possível concluir a operação", f"{e}")

    def backup(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, "Salvar backup", "codex-backup.db", "Banco SQLite (*.db)")
        if p:
            self._safe(lambda: self.ctx.db.backup_to(p), f"Backup salvo em:\n{p}")

    def restore(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Restaurar backup", "", "Banco SQLite (*.db)")
        if not p:
            return
        if QMessageBox.question(self, "Restaurar backup",
                                "Isto substitui TODO o seu progresso atual pelo conteúdo do backup. Continuar?"
                                ) != QMessageBox.Yes:
            return

        def go() -> None:
            dest = self.ctx.db.path
            self.ctx.db.close()
            shutil.copyfile(dest, str(dest) + ".antes-da-restauracao")
            UserDB.restore_from(p, dest)
            self.ctx.db.__init__(dest)  # reabre
            self.ctx.dataChanged.emit()
        self._safe(go, "Backup restaurado. Uma cópia do banco anterior foi mantida (.antes-da-restauracao).")

    def export_notes(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, "Exportar notas", "notas-codex.md", "Markdown (*.md)")
        if p:
            titles = {a.id: a.title for a in self.ctx.lib.articles.values()}
            self._safe(lambda: self.ctx.db.export_notes_markdown(p, titles), f"Exportado para:\n{p}")

    def export_cards(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, "Exportar flashcards", "flashcards-codex.csv", "CSV (*.csv)")
        if p:
            self._safe(lambda: self.ctx.db.export_cards_csv(p, self.ctx.lib), f"Exportado para:\n{p}")

    def export_json(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, "Exportar tudo", "codex-dados.json", "JSON (*.json)")
        if p:
            self._safe(lambda: self.ctx.db.export_json(p), f"Exportado para:\n{p}")

    def open_user_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(user_content_dir())))

    def reload(self) -> None:
        self.ctx.reload_content()
        self.statusBar().showMessage(f"Conteúdo recarregado: {len(self.ctx.lib.articles)} artigos.", 5000)

    def show_validation(self) -> None:
        issues = validate(self.ctx.lib, self.ctx.fig_dirs)
        errs = [i for i in issues if i.severity == "erro"]
        warns = [i for i in issues if i.severity == "aviso"]
        w = QTextBrowser(self)
        w.setWindowFlag(Qt.Window)
        w.setWindowTitle("Validação da base de conhecimento")
        w.resize(900, 600)
        txt = (f"<h3>{len(errs)} erro(s), {len(warns)} aviso(s)</h3>"
               "<p><i>Validação estrutural apenas: não substitui a revisão científica.</i></p><ul>"
               + "".join(f"<li><b>{html.escape(i.severity.upper())}</b> {html.escape(i.where)}: {html.escape(i.message)}</li>"
                         for i in errs + warns) + "</ul>")
        w.setHtml(txt)
        w.show()
        self._val = w

    def about(self) -> None:
        from .. import __version__
        QMessageBox.about(self, f"Molecular Biology Codex v{__version__}",
                          "Wiki desktop de biologia molecular com revisão espaçada.\n\n"
                          "Os textos ainda NÃO foram revisados por especialista; confira sempre as referências "
                          "e seu status de verificação.")
