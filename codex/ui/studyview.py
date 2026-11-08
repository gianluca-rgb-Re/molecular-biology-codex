"""Modo de estudo: flashcards (revisão espaçada), questões, revisão de dificuldades e histórico."""
from __future__ import annotations
import html

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QInputDialog, QLabel, QProgressBar, QPushButton,
                               QRadioButton, QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
                               QWidget)

from .. import gamify
from ..content import format_reference
from ..srs import CONFIDENCE, RATINGS, CardState, preview_interval, schedule
from ..study import build_card_queue, build_item_index
from .common import ArticleBrowser, Context, cat_color, cat_icon


def _p(text: str) -> str:
    return "<p>" + html.escape(str(text)).replace("\n", "<br>") + "</p>"


class StudyView(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.queue: list[str] = []
        self.pos = 0
        self.state = "empty"
        self.stats = {"n": 0, "ok": 0}
        self.xp_start = 0
        self.idx = build_item_index(ctx.lib)
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.addWidget(self.stack)
        self._build_menu()
        self._build_session()
        self._build_history()
        ctx.dataChanged.connect(self._refresh_menu)
        self.setFocusPolicy(Qt.StrongFocus)
        self._refresh_menu()

    # ------------------------------------------------------------------ menu
    def _build_menu(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        h = QLabel("🧠 Modo de estudo")
        h.setObjectName("h")
        l.addWidget(h)
        self.filter = QComboBox()
        self.info = QLabel()
        self.info.setWordWrap(True)
        l.addWidget(QLabel("Filtrar por artigo:"))
        l.addWidget(self.filter)
        l.addWidget(self.info)
        self.btn_cards = QPushButton("🃏  Flashcards — vencidos primeiro, depois novos (20 por sessão)")
        self.btn_quiz = QPushButton("📝  Questões — objetivas, mecanísticas e de interpretação experimental")
        self.btn_diff = QPushButton("♻  Revisar itens com dificuldade")
        self.btn_hist = QPushButton("📈  Histórico de desempenho")
        for b, fn in ((self.btn_cards, lambda: self.start("cards")), (self.btn_quiz, lambda: self.start("quiz")),
                      (self.btn_diff, lambda: self.start("diff")), (self.btn_hist, self._show_history)):
            b.setMinimumHeight(46)
            b.clicked.connect(fn)
            l.addWidget(b)
        tip = QLabel("Como funciona: 1) declare sua confiança, 2) (opcional) escreva sua resposta, 3) mostre a resposta, "
                     "4) avalie: Errei / Difícil / Bom / Fácil. A avaliação define quando o cartão volta. "
                     "Atalhos: Espaço/Enter = mostrar, 1–4 = avaliar.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        l.addWidget(tip)
        l.addStretch(1)
        self.stack.addWidget(w)

    def _refresh_menu(self) -> None:
        self.idx = build_item_index(self.ctx.lib)
        cur = self.filter.currentData()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem("Todos os artigos", None)
        for a in self.ctx.lib.sorted_articles():
            if a.flashcards or a.questions:
                self.filter.addItem(f"{cat_icon(a.category)} {a.title}", a.id)
        self.filter.setCurrentIndex(max(0, self.filter.findData(cur)))
        self.filter.blockSignals(False)
        due = len(self.ctx.db.due_card_ids())
        self.info.setText(
            f"{sum(len(a.flashcards) for a in self.ctx.lib.articles.values())} flashcards · "
            f"{sum(len(a.questions) for a in self.ctx.lib.articles.values())} questões · "
            f"<b>{due}</b> cartão(ões) vencido(s) · {len(self.ctx.db.difficult_item_ids())} item(ns) com dificuldade.")

    # --------------------------------------------------------------- session
    def _build_session(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        top = QHBoxLayout()
        b_exit = QPushButton("← Sair")
        b_exit.clicked.connect(self._exit)
        self.lbl_prog = QLabel()
        self.lbl_prog.setObjectName("muted")
        self.b_open = QPushButton("📖 Abrir artigo")
        self.b_open.clicked.connect(lambda: self.ctx.openArticle.emit(self._cur()[0]) if self.queue and self.pos < len(self.queue) else None)
        self.b_doubt = QPushButton("❓ Registrar dúvida")
        self.b_doubt.clicked.connect(self._doubt)
        top.addWidget(b_exit)
        top.addWidget(self.lbl_prog, 1)
        top.addWidget(self.b_open)
        top.addWidget(self.b_doubt)
        l.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setFixedHeight(10)
        self.bar.setTextVisible(False)
        l.addWidget(self.bar)
        self.view = ArticleBrowser()
        self.view.linkClicked.connect(lambda u: self.ctx.openArticle.emit(u.toString().rsplit("/", 1)[1])
                                      if u.toString().startswith("codex://article/") else None)
        l.addWidget(self.view, 1)
        self.opt_box = QWidget()
        self.opt_lay = QVBoxLayout(self.opt_box)
        self.opt_lay.setContentsMargins(0, 0, 0, 0)
        self.opt_group = QButtonGroup(self)
        l.addWidget(self.opt_box)
        self.answer_edit = QTextEdit()
        self.answer_edit.setPlaceholderText("Sua resposta (opcional nos flashcards; recomendado — escrever ajuda a fixar). "
                                            "Ctrl+Enter para continuar.")
        self.answer_edit.setFixedHeight(84)
        l.addWidget(self.answer_edit)
        self.conf_box = QWidget()
        cl = QHBoxLayout(self.conf_box)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(QLabel("Confiança antes de ver a resposta:"))
        self.conf_group = QButtonGroup(self)
        for v, name in CONFIDENCE.items():
            rb = QRadioButton(name)
            self.conf_group.addButton(rb, v)
            cl.addWidget(rb)
            rb.setChecked(v == 2)
        cl.addStretch(1)
        l.addWidget(self.conf_box)
        self.btn_main = QPushButton("Mostrar resposta  (Espaço)")
        self.btn_main.setObjectName("primary")
        self.btn_main.setMinimumHeight(42)
        self.btn_main.clicked.connect(self._main_action)
        l.addWidget(self.btn_main)
        self.rate_box = QWidget()
        rl = QHBoxLayout(self.rate_box)
        rl.setContentsMargins(0, 0, 0, 0)
        self.rate_btns: dict[int, QPushButton] = {}
        for r, oid in zip(RATINGS, ("bad", "hard", "good", "easy")):
            b = QPushButton()
            b.setObjectName(oid)
            b.setMinimumHeight(48)
            b.clicked.connect(lambda _=False, rr=r: self._rate(rr))
            self.rate_btns[r] = b
            rl.addWidget(b)
        l.addWidget(self.rate_box)
        self.btn_next = QPushButton("Próxima →  (Enter)")
        self.btn_next.setObjectName("primary")
        self.btn_next.setMinimumHeight(42)
        self.btn_next.clicked.connect(self._next)
        l.addWidget(self.btn_next)
        self.toast = QLabel("")
        self.toast.setStyleSheet("color:#6fcf6f; font-weight:bold;")
        l.addWidget(self.toast)
        self.stack.addWidget(w)

    def keyPressEvent(self, e):  # noqa: N802
        if self.stack.currentIndex() == 1:
            k, typing = e.key(), self.answer_edit.hasFocus()
            ctrl = bool(e.modifiers() & Qt.ControlModifier)
            if k in (Qt.Key_Return, Qt.Key_Enter) and (ctrl or not typing):
                (self._main_action if self.state == "ask" else self._next if self.state == "done" else lambda: None)()
                return
            if k == Qt.Key_Space and not typing and self.state == "ask":
                self._main_action()
                return
            if not typing and self.state == "rate" and Qt.Key_1 <= k <= Qt.Key_4:
                self._rate(k - Qt.Key_1)
                return
        super().keyPressEvent(e)

    def start(self, mode: str) -> None:
        aid = self.filter.currentData()
        db = self.ctx.db
        if mode == "cards":
            self.queue = build_card_queue(self.ctx.lib, db, aid)
        elif mode == "quiz":
            ids = [i for i, (a, k, _d) in self.idx.items() if k in ("mcq", "open") and (aid is None or a == aid)]
            res = {i: db.last_result(i) for i in ids}
            ids.sort(key=lambda i: (res[i] is not None, res[i]["correct"] if res[i] else 0))
            self.queue = ids[:10]
        else:
            self.queue = [i for i in db.difficult_item_ids() if i in self.idx and (aid is None or self.idx[i][0] == aid)][:20]
        self.pos, self.stats = 0, {"n": 0, "ok": 0}
        self.xp_start = gamify.profile(self.ctx.lib, db).xp
        self.stack.setCurrentIndex(1)
        self.toast.setText("")
        if not self.queue:
            self.view.document().setDefaultStyleSheet(self.ctx.css())
            self.view.setHtml("<h3>Nada para estudar com este filtro agora.</h3><p>Não há itens vencidos, novos ou com "
                              "dificuldade registrada. Experimente outro artigo ou volte mais tarde.</p>")
            self._set_state("empty")
            return
        self._show_item()
        self.setFocus()

    def _exit(self) -> None:
        self.stack.setCurrentIndex(0)
        self.ctx.dataChanged.emit()

    def _cur(self) -> tuple[str, str, dict]:
        return self.idx[self.queue[self.pos]]

    def _set_state(self, state: str) -> None:
        self.state = state
        kind = self._cur()[1] if self.queue and self.pos < len(self.queue) and state != "empty" else ""
        self.opt_box.setVisible(state == "ask" and kind == "mcq")
        self.answer_edit.setVisible(state == "ask" and kind in ("card", "open"))
        self.conf_box.setVisible(state == "ask")
        self.btn_main.setVisible(state == "ask")
        self.rate_box.setVisible(state == "rate")
        self.btn_next.setVisible(state == "done")
        for b in (self.b_open, self.b_doubt):
            b.setVisible(state != "empty")

    def _show_item(self) -> None:
        if self.pos >= len(self.queue):
            gained = gamify.profile(self.ctx.lib, self.ctx.db).xp - self.xp_start
            pct = 100 * self.stats["ok"] // max(1, self.stats["n"])
            self.view.document().setDefaultStyleSheet(self.ctx.css())
            self.view.setHtml(f"<h2>🎉 Sessão concluída</h2><p><b>{self.stats['n']}</b> item(ns) · "
                              f"<b>{pct}%</b> de acertos/Bom+ · <b>+{gained} XP</b></p>"
                              "<p>Veja o histórico para acompanhar seu desempenho. Itens que você errou voltam em "
                              "«Revisar itens com dificuldade» e, nos cartões, no dia seguinte.</p>")
            self.bar.setValue(self.bar.maximum())
            self._set_state("empty")
            self.lbl_prog.setText("")
            return
        aid, kind, d = self._cur()
        art = self.ctx.lib.articles[aid]
        self.bar.setMaximum(len(self.queue))
        self.bar.setValue(self.pos)
        self.bar.setStyleSheet(f"QProgressBar::chunk {{ background:{cat_color(art.category)}; }}")
        self.lbl_prog.setText(f"{self.pos + 1}/{len(self.queue)} · {cat_icon(art.category)} {art.title}")
        self.answer_edit.clear()
        for b in list(self.opt_group.buttons()):
            self.opt_group.removeButton(b)
            self.opt_lay.removeWidget(b)
            b.deleteLater()
        label = {"card": "Flashcard", "mcq": "Questão objetiva", "open": "Questão discursiva / experimental"}[kind]
        self.view.document().setDefaultStyleSheet(self.ctx.css())
        self.view.setHtml(f"<p class='muted'>{label}</p><h3>{html.escape(d.get('q', ''))}</h3>"
                          + (_p(d["context"]) if d.get("context") else ""))
        if kind == "mcq":
            for i, o in enumerate(d.get("options", [])):
                rb = QRadioButton(f"{chr(65 + i)}) {o}")
                self.opt_group.addButton(rb, i)
                self.opt_lay.addWidget(rb)
        self.btn_main.setText("Responder  (Enter)" if kind == "mcq" else
                              "Mostrar resposta  (Espaço)" if kind == "card" else "Mostrar resposta-modelo  (Ctrl+Enter)")
        self.conf_group.button(2).setChecked(True)
        self._set_state("ask")

    def _conf(self) -> int:
        c = self.conf_group.checkedId()
        return c if c in (1, 2, 3) else 2

    def _refs_html(self, keys) -> str:
        out = [format_reference(self.ctx.lib.refs[k]) for k in (keys or []) if k in self.ctx.lib.refs]
        return ("<p class='muted'>Referências: " + html.escape(" | ".join(out)) + "</p>") if out else ""

    def _main_action(self) -> None:
        if self.state != "ask":
            return
        aid, kind, d = self._cur()
        iid = self.queue[self.pos]
        if kind == "mcq":
            ch = self.opt_group.checkedId()
            if ch < 0:
                self.toast.setStyleSheet("color:#e0a458; font-weight:bold;")
                self.toast.setText("Escolha uma alternativa antes de responder.")
                return
            ok = ch == d["answer"]
            self.ctx.db.record_review(iid, "mcq", aid, ok, None, self._conf(), str(ch))
            self.stats["n"] += 1
            self.stats["ok"] += int(ok)
            parts = [f"<hr><h3>{'✔ Correto' if ok else '✖ Incorreto'}</h3>"]
            if not ok and self._conf() == 3:
                parts.append("<p><b>Atenção:</b> você tinha alta confiança e errou — vale revisar o conceito.</p>")
            for i, (o, e) in enumerate(zip(d["options"], d["explanations"])):
                parts.append(f"<p><b>{chr(65 + i)}) {html.escape(o)}</b> {'✔ (correta)' if i == d['answer'] else '✖'}<br>{html.escape(e)}</p>")
            parts.append(self._refs_html(d.get("refs")))
            self.view.append("".join(parts))
            self.toast.setStyleSheet("color:#6fcf6f; font-weight:bold;")
            self.toast.setText("✔ Resposta registrada")
            self._set_state("done")
            return
        body = d.get("a") if kind == "card" else d.get("model_answer")
        parts = [f"<hr><h4>{'Resposta' if kind == 'card' else 'Resposta-modelo comentada'}</h4>", _p(body)]
        typed = self.answer_edit.toPlainText().strip()
        if typed:
            parts.append("<h4>Sua resposta</h4>" + _p(typed))
        if d.get("explain"):
            parts.append("<h4>Explicação</h4>" + _p(d["explain"]))
        parts.append(self._refs_html(d.get("refs")))
        rel = [r for r in d.get("related", []) if r in self.ctx.lib.articles]
        if rel:
            parts.append("<p>Conceitos relacionados: " + ", ".join(
                f"<a href='codex://article/{r}'>{html.escape(self.ctx.lib.articles[r].title)}</a>" for r in rel) + "</p>")
        self.view.append("".join(parts))
        st = (self.ctx.db.card_state(iid) or CardState()) if kind == "card" else CardState()
        for r, b in self.rate_btns.items():
            b.setText(f"{r + 1} · {RATINGS[r]}" + (f"\n+{preview_interval(st, r, self._conf())} dia(s)" if kind == "card" else ""))
        self._set_state("rate")

    def _rate(self, rating: int) -> None:
        if self.state != "rate":
            return
        aid, kind, _d = self._cur()
        iid = self.queue[self.pos]
        conf = self._conf()
        msg = "✔ Registrado"
        if kind == "card":
            st = schedule(self.ctx.db.card_state(iid) or CardState(), rating, conf)
            self.ctx.db.save_card_state(iid, aid, st)
            msg += f" — próxima revisão em {st.interval} dia(s)"
        self.ctx.db.record_review(iid, kind, aid, rating >= 2, rating, conf,
                                  self.answer_edit.toPlainText() if kind in ("open", "card") else "")
        self.stats["n"] += 1
        self.stats["ok"] += int(rating >= 2)
        self.pos += 1
        self._show_item()
        self.toast.setStyleSheet("color:#6fcf6f; font-weight:bold;")
        self.toast.setText(msg)
        QTimer.singleShot(4000, lambda: self.toast.setText("") if self.toast.text() == msg else None)

    def _next(self) -> None:
        self.pos += 1
        self._show_item()
        self.toast.setText("")

    def _doubt(self) -> None:
        if not self.queue or self.pos >= len(self.queue):
            return
        aid, _k, d = self._cur()
        text, ok = QInputDialog.getMultiLineText(self, "Registrar dúvida", "Descreva sua dúvida:", f"Sobre: {d.get('q', '')[:120]}\n")
        if ok and text.strip():
            self.ctx.db.add_doubt(aid, text.strip(), self.queue[self.pos])
            self.toast.setText("❓ Dúvida registrada")

    # --------------------------------------------------------------- history
    def _build_history(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        b = QPushButton("← Voltar")
        b.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        l.addWidget(b)
        self.t_days = QTableWidget(0, 4)
        self.t_days.setHorizontalHeaderLabels(["Dia", "Itens", "Acertos / Bom+", "Taxa"])
        self.t_art = QTableWidget(0, 4)
        self.t_art.setHorizontalHeaderLabels(["Artigo", "Itens", "Acertos / Bom+", "Taxa"])
        l.addWidget(QLabel("Últimos 14 dias"))
        l.addWidget(self.t_days)
        l.addWidget(QLabel("Desempenho por artigo"))
        l.addWidget(self.t_art)
        self.stack.addWidget(w)

    def _show_history(self) -> None:
        def fill(t: QTableWidget, rows) -> None:
            t.setRowCount(len(rows))
            for r, (name, n, ok) in enumerate(rows):
                for c, v in enumerate([name, str(n), str(ok), f"{100 * ok // max(1, n)}%"]):
                    t.setItem(r, c, QTableWidgetItem(v))
            t.resizeColumnsToContents()
        fill(self.t_days, self.ctx.db.reviews_by_day(14))
        fill(self.t_art, [(self.ctx.lib.articles[a].title if a in self.ctx.lib.articles else a, n, ok)
                          for a, n, ok in self.ctx.db.accuracy_by_article()])
        self.stack.setCurrentIndex(2)
