"""Aba «Análise de PKS»: matriz de domínios, arquiteturas, frequências, comparação, diagramas, exportação e validação."""
from __future__ import annotations
import html
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from .. import analysis, export, genoteca, report, viz
from ..analysis import CORE_CLASSES, SOURCES, Rec, source_label
from ..antismash import display_name
from .common import Context
from .genome_explorer import NumItem


class AnalysisView(QWidget):
    def __init__(self, ctx: Context, open_gene):
        super().__init__()
        self.ctx, self.open_gene = ctx, open_gene
        self.all: list[Rec] = []
        self.recs: list[Rec] = []
        title = QLabel("🧮 Análise comparativa de genes biossintéticos")
        title.setObjectName("h")
        self.species, self.cls, self.bgc, self.source = QComboBox(), QComboBox(), QComboBox(), QComboBox()
        for k, v in SOURCES.items():
            self.source.addItem(v, k)
        self.text = QLineEdit()
        self.text.setPlaceholderText("Filtrar por gene, scaffold ou domínio…")
        self.count = QLabel()
        self.count.setObjectName("muted")
        bar = QHBoxLayout()
        for lab, w in (("Espécie:", self.species), ("Classe da proteína:", self.cls), ("Tipo de BGC:", self.bgc), ("Fonte dos domínios:", self.source)):
            bar.addWidget(QLabel(lab))
            bar.addWidget(w)
        bar.addWidget(self.text, 1)
        self.species.activated.connect(lambda _i: self.reload())
        for w in (self.cls, self.bgc, self.source):
            w.activated.connect(lambda _i: self.apply())
        self.text.textChanged.connect(lambda _t: self.apply())
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(lambda _i: self.refresh_tab())
        self._build_tabs()
        lay = QVBoxLayout(self)
        lay.addWidget(title)
        lay.addLayout(bar)
        lay.addWidget(self.count)
        lay.addWidget(self.tabs, 1)
        ctx.dataChanged.connect(self.reload)
        self.reload()

    # ----------------------------------------------------------------- dados
    @property
    def src(self) -> str:
        return self.source.currentData() or "antismash"

    def reload(self) -> None:
        cur = self.species.currentData()
        self.species.blockSignals(True)
        self.species.clear()
        self.species.addItem("Todas as espécies", None)
        for r in genoteca.species_list(self.ctx.db):
            self.species.addItem(r["name"] + (f" ({r['strain']})" if r["strain"] else ""), r["id"])
        self.species.setCurrentIndex(max(0, self.species.findData(cur)))
        self.species.blockSignals(False)
        self.all = analysis.load_records(self.ctx.db, self.species.currentData())
        for combo, vals, first in ((self.cls, sorted({r.gene_class for r in self.all}), "todas as classes"),
                                   (self.bgc, sorted({t for r in self.all for t in r.bgc_types}), "todos os tipos")):
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(first)
            combo.addItems(vals)
            combo.setCurrentIndex(max(0, combo.findText(cur)))
            combo.blockSignals(False)
        self.apply()

    def apply(self) -> None:
        c = self.cls.currentText() if self.cls.currentIndex() > 0 else None
        b = self.bgc.currentText() if self.bgc.currentIndex() > 0 else None
        self.recs = analysis.filter_records(self.all, c, b, self.text.text())
        self.count.setText(f"{len(self.recs)} de {len(self.all)} genes-âncora (PKS, NRPS, híbridas, NRPS-like, terpeno) · fonte dos domínios: {self.source.currentText()}")
        self.refresh_tab()

    def selected(self) -> list[Rec]:
        ids = {self.mat.item(i.row(), 0).data(Qt.UserRole) for i in self.mat.selectionModel().selectedRows()}
        return [r for r in self.recs if r.id in ids]

    # ------------------------------------------------------------------ abas
    def _table(self) -> QTableWidget:
        t = QTableWidget(0, 0)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSortingEnabled(True)
        return t

    def _build_tabs(self) -> None:
        # matriz
        w = QWidget()
        l = QVBoxLayout(w)
        self.mat = self._table()
        self.mat.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.mat.cellDoubleClicked.connect(lambda r, _c: self.open_gene(self.mat.item(r, 0).data(Qt.UserRole)))
        self.mat_info = QLabel()
        self.mat_info.setWordWrap(True)
        hint = QLabel("Linhas = proteínas; colunas = domínios (nomes do antiSMASH sem o prefixo «PKS_», mais frequentes primeiro). ● = presente (n = cópias). Selecione 2 ou mais linhas e abra «Comparar». "
                      "Clique no cabeçalho para ordenar; duplo clique abre o gene.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        for x in (hint, self.mat, self.mat_info):
            l.addWidget(x, 1 if x is self.mat else 0)
        self.tabs.addTab(w, "Matriz de domínios")
        # arquiteturas
        self.arch = self._table()
        self.tabs.addTab(self.arch, "Arquiteturas")
        # frequência
        w = QWidget()
        l = QVBoxLayout(w)
        self.freq = self._table()
        self.freq_img = QLabel()
        sc = QScrollArea()
        sc.setWidget(self.freq_img)
        sc.setWidgetResizable(False)
        l.addWidget(self.freq, 1)
        l.addWidget(sc, 2)
        self.tabs.addTab(w, "Frequência")
        # comparar
        w = QWidget()
        l = QVBoxLayout(w)
        self.cmp = QTextBrowser()
        self.cmp_img = QLabel()
        sc2 = QScrollArea()
        sc2.setWidget(self.cmp_img)
        l.addWidget(self.cmp, 3)
        l.addWidget(sc2, 2)
        self.tabs.addTab(w, "Comparar")
        # diagramas
        w = QWidget()
        l = QVBoxLayout(w)
        row = QHBoxLayout()
        self.diag_sel = QCheckBox("Usar só os selecionados na matriz (se houver)")
        self.diag_sel.setChecked(True)
        self.diag_sel.clicked.connect(lambda _c: self.refresh_tab())
        row.addWidget(self.diag_sel)
        row.addStretch(1)
        for text, fn in (("💾 PNG", lambda: self.export_diagram("png")), ("💾 SVG", lambda: self.export_diagram("svg"))):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        self.diag_img = QLabel()
        sc3 = QScrollArea()
        sc3.setWidget(self.diag_img)
        l.addLayout(row)
        l.addWidget(sc3, 1)
        self.tabs.addTab(w, "Diagramas")
        # exportar
        w = QWidget()
        l = QHBoxLayout(w)
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Colunas a exportar</b>"))
        self.cols = QListWidget()
        for k in export.COLUMN_KEYS:
            it = QListWidgetItem(export.COLUMN_LABELS[k])
            it.setData(Qt.UserRole, k)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if k in export.DEFAULT_KEYS else Qt.Unchecked)
            self.cols.addItem(it)
        left.addWidget(self.cols)
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Quais registros</b>"))
        self.scope = QComboBox()
        self.scope.addItems(["Filtrados na tela", "Selecionados na matriz", "Todos os genes-âncora da espécie (sem filtros)"])
        right.addWidget(self.scope)
        self.exp_note = QLabel("A fonte dos domínios é a escolhida no topo. Todas as exportações trazem os nomes originais dos domínios e a distinção entre "
                               "dados do arquivo e inferências do app (planilha «Leia-me» no XLSX; seção de notas no PDF).")
        self.exp_note.setWordWrap(True)
        self.exp_note.setObjectName("muted")
        right.addWidget(self.exp_note)
        for text, fn in (("📄 Exportar CSV", self.export_csv), ("📊 Exportar XLSX (Excel)", self.export_xlsx), ("📑 Relatório PDF", self.export_pdf)):
            b = QPushButton(text)
            b.setMinimumHeight(38)
            b.clicked.connect(lambda _=False, f=fn: f())
            right.addWidget(b)
        right.addStretch(1)
        l.addLayout(left, 1)
        l.addLayout(right, 1)
        self.tabs.addTab(w, "Exportar")
        # validação
        w = QWidget()
        l = QVBoxLayout(w)
        b = QPushButton("▶ Rodar verificação científica do conjunto importado")
        b.clicked.connect(self.run_audit)
        self.audit_view = QTextBrowser()
        l.addWidget(b)
        l.addWidget(self.audit_view, 1)
        self.tabs.addTab(w, "Validação")

    def refresh_tab(self) -> None:
        i, s = self.tabs.currentIndex(), self.src
        if i == 0:
            self._fill_matrix(s)
        elif i == 1:
            self._fill_arch(s)
        elif i == 2:
            self._fill_freq(s)
        elif i == 3:
            self._fill_compare(s)
        elif i == 4:
            self._fill_diagrams(s)

    def _fill_matrix(self, s: str) -> None:
        cols, rows = analysis.matrix(self.recs, s)
        t = self.mat
        t.setSortingEnabled(False)
        heads = ["Gene", "Classe da proteína", "Tipo de BGC", "aa", "Éxons", "Arquitetura"] + cols
        t.setColumnCount(len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(rows))
        for i, (r, counts) in enumerate(rows):
            vals = [QTableWidgetItem(r.locus), QTableWidgetItem(r.gene_class), QTableWidgetItem(",".join(r.bgc_types) or "—"), NumItem(r.aa), NumItem(r.exons),
                    QTableWidgetItem(r.arch_str(s))]
            vals[0].setData(Qt.UserRole, r.id)
            for k, it in enumerate(vals):
                t.setItem(i, k, it)
            for j, c in enumerate(counts):
                it = NumItem(c, ("●" if c == 1 else f"● ×{c}") if c else "")
                it.setTextAlignment(Qt.AlignCenter)
                if c:
                    col = viz.domain_color(cols[j])
                    col.setAlpha(150)
                    it.setBackground(col)
                t.setItem(i, 6 + j, it)
        t.setSortingEnabled(True)
        t.resizeColumnsToContents()
        for j, d in enumerate(cols):
            ex = next((x for r in self.recs for x in r.doms(s) if display_name(x["name"]) == d), None)
            t.horizontalHeaderItem(6 + j).setToolTip(source_label(ex) if ex else "")
        fr = analysis.domain_frequency(self.recs, s)
        uni = [f["domain"] for f in fr if f["category"] == "universal"]
        exc = analysis.exclusive_domains(self.recs, s)
        self.mat_info.setText("<b>Compartilhados por todas:</b> " + (", ".join(uni) or "—") + "<br><b>Exclusivos:</b> "
                              + ("; ".join(f"{html.escape(k)} → {html.escape(', '.join(v))}" for k, v in exc.items()) or "—"))

    def _fill_arch(self, s: str) -> None:
        g = analysis.group_architectures(self.recs, s)
        t = self.arch
        t.setSortingEnabled(False)
        t.setColumnCount(4)
        t.setHorizontalHeaderLabels(["Arquitetura (ordem preservada)", "Nº de proteínas", "Genes", "Observações (critérios do app — não são conclusões biológicas)"])
        t.setRowCount(len(g))
        for i, x in enumerate(g):
            for k, it in enumerate([QTableWidgetItem(x["arch_str"]), NumItem(x["n"]), QTableWidgetItem(", ".join(x["loci"])), QTableWidgetItem("; ".join(x["notes"]))]):
                t.setItem(i, k, it)
        t.setSortingEnabled(True)
        t.resizeColumnsToContents()

    def _fill_freq(self, s: str) -> None:
        fr = analysis.domain_frequency(self.recs, s)
        t = self.freq
        t.setSortingEnabled(False)
        t.setColumnCount(5)
        t.setHorizontalHeaderLabels(["Domínio", "Proteínas", "Frequência relativa", "Cópias", "Categoria"])
        t.setRowCount(len(fr))
        for i, f in enumerate(fr):
            for k, it in enumerate([QTableWidgetItem(f["domain"]), NumItem(f["proteins"]), NumItem(f["freq"] * 100, f"{100 * f['freq']:.0f}%"), NumItem(f["copies"]),
                                    QTableWidgetItem(f["category"])]):
                t.setItem(i, k, it)
        t.setSortingEnabled(True)
        t.resizeColumnsToContents()
        img = viz.render_bar_chart([(f["domain"], f["proteins"]) for f in fr], "Proteínas com cada domínio", 900, "", "auto", len(self.recs) or None)
        self.freq_img.setPixmap(QPixmap.fromImage(img))
        self.freq_img.resize(img.size())

    def _fill_compare(self, s: str) -> None:
        sel = self.selected()
        if len(sel) < 2:
            self.cmp.setHtml("<p>Selecione <b>duas ou mais proteínas</b> na aba «Matriz de domínios» (Ctrl/Shift + clique) e volte aqui.</p>")
            self.cmp_img.clear()
            return
        c = analysis.compare(sel, s)
        keys = list(c["rows"][0].keys())
        h = "<table border='1' cellspacing='0' cellpadding='4'><tr><th></th>" + "".join(f"<th>{html.escape(r['Gene'])}</th>" for r in c["rows"]) + "</tr>"
        for k in keys[1:]:
            h += f"<tr><td><b>{k}</b></td>" + "".join(f"<td>{html.escape(str(r[k]))}</td>" for r in c["rows"]) + "</tr>"
        h += "</table><h3>Diferenças entre arquiteturas</h3><ul>"
        for p in c["pairs"]:
            state = "<b>idênticas</b>" if p["identical"] else ("mesmos domínios em <b>ordem diferente</b>" if p["same_set_different_order"] else "diferentes")
            h += (f"<li>{html.escape(p['a'])} × {html.escape(p['b'])}: {state}; distância de edição {p['edit_distance']}; Δ aa = {p['aa_diff']:+d}; "
                  f"compartilhados: {html.escape(', '.join(p['shared']) or '—')}; só em {html.escape(p['a'])}: {html.escape(', '.join(p['only_a']) or '—')}; "
                  f"só em {html.escape(p['b'])}: {html.escape(', '.join(p['only_b']) or '—')}</li>")
        h += "</ul><p><b>Presentes em todas:</b> " + html.escape(", ".join(c["common"]) or "—") + "</p>"
        h += "<p style='color:#9aa4b2'>Ausência de um domínio na lista do antiSMASH não implica truncamento nem perda de função; é uma observação sobre a anotação.</p>"
        self.cmp.setHtml(h)
        img = viz.render_architectures_image(sel, 1300, s)
        self.cmp_img.setPixmap(QPixmap.fromImage(img))
        self.cmp_img.resize(img.size())

    def _diag_recs(self) -> list[Rec]:
        sel = self.selected() if self.diag_sel.isChecked() else []
        return (sel or self.recs)[:40]

    def _fill_diagrams(self, s: str) -> None:
        recs = self._diag_recs()
        if not recs:
            self.diag_img.clear()
            return
        img = viz.render_architectures_image(recs, 1300, s, f"Arquiteturas de domínios — {len(recs)} proteína(s)")
        self.diag_img.setPixmap(QPixmap.fromImage(img))
        self.diag_img.resize(img.size())

    # ------------------------------------------------------------- exportação
    def _scope_recs(self) -> list[Rec]:
        i = self.scope.currentIndex()
        if i == 1:
            return self.selected()
        return self.all if i == 2 else self.recs

    def _keys(self) -> list[str]:
        return [self.cols.item(i).data(Qt.UserRole) for i in range(self.cols.count()) if self.cols.item(i).checkState() == Qt.Checked]

    def _check(self) -> list[Rec] | None:
        recs = self._scope_recs()
        if not recs or not self._keys():
            QMessageBox.information(self, "Exportar", "Não há registros ou colunas selecionados para exportar.")
            return None
        return recs

    def export_csv(self) -> None:
        recs = self._check()
        if recs is None:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Exportar CSV", "genes_biossinteticos.csv", "CSV (*.csv)")
        if p:
            n = export.write_csv(p, recs, self._keys(), self.src)
            QMessageBox.information(self, "Exportado", f"{n} registro(s) em:\n{p}")

    def export_xlsx(self) -> None:
        recs = self._check()
        if recs is None:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Exportar XLSX", "genes_biossinteticos.xlsx", "Excel (*.xlsx)")
        if p:
            n = export.write_xlsx(p, recs, self._keys(), self.src, {"species": ", ".join(sorted({r.species for r in recs}))})
            QMessageBox.information(self, "Exportado", f"{n} registro(s) em 5 planilhas (Genes, Matriz, Frequência, Arquiteturas, Classes) + Leia-me:\n{p}")

    def export_pdf(self) -> None:
        recs = self._scope_recs()
        if not recs:
            QMessageBox.information(self, "Relatório", "Não há genes no recorte escolhido.")
            return
        p, _ = QFileDialog.getSaveFileName(self, "Relatório PDF", "relatorio_pks.pdf", "PDF (*.pdf)")
        if p:
            report.write_pdf(p, self.ctx.db, recs, self.species.currentData(), self.src)
            QMessageBox.information(self, "Relatório gerado", p)

    def export_diagram(self, fmt: str) -> None:
        recs = self._diag_recs()
        if not recs:
            return
        p, _ = QFileDialog.getSaveFileName(self, f"Exportar {fmt.upper()}", f"diagramas_dominios.{fmt}", f"{fmt.upper()} (*.{fmt})")
        if p:
            viz.save_architectures(recs, p, self.src, f"Arquiteturas de domínios — {len(recs)} proteína(s)")

    def run_audit(self) -> None:
        a = analysis.audit(self.ctx.db, self.species.currentData())
        li = lambda xs: "<ul>" + "".join(f"<li>{x}</li>" for x in xs) + "</ul>" if xs else "<p>Nenhum.</p>"  # noqa: E731
        h = (f"<h3>Resumo</h3><p>{a['total_genes']} gene(s) importado(s); {a['core']} genes-âncora (PKS, NRPS, híbridas, NRPS-like, terpeno).</p>"
             "<p style='color:#e0a458'>Esta verificação cobre <b>apenas o que foi importado</b>. Se você importou uma região, os demais genes PKS do genoma não estão aqui — "
             "importe o GenBank do genoma inteiro (antiSMASH) para a lista completa.</p>"
             "<h3>Candidatos possivelmente ignorados (sugestões para revisão)</h3>"
             + li([f"<b>{html.escape(c['locus'])}</b> ({html.escape(c['class'])}): {html.escape(c['reason'])}" for c in a["candidates_ignored"]])
             + "<h3>Posições duplicadas</h3>" + li([f"{html.escape(x)} e {html.escape(y)}" for x, y in a["duplicate_positions"]])
             + "<h3>Proteínas idênticas em loci diferentes</h3>" + li([f"{html.escape(x)} = {html.escape(y)}" for x, y in a["duplicate_proteins"]])
             + "<h3>Verificações da CDS (critérios do app: quadro, ATG, parada, paradas internas, íntrons GT–AG, proteína = arquivo)</h3>"
             + li([f"<b>{html.escape(l)}</b>: {html.escape(', '.join(al))}" for l, al in a["cds_alerts"]])
             + (f"<p>Não verificáveis (sem sequência genômica/éxons): {html.escape(', '.join(a['cds_unchecked']))}</p>" if a["cds_unchecked"] else "")
             + "<h3>Dados originais × inferências</h3><p><b>Originais (arquivo):</b> identificadores e coordenadas de domínios, tipo de BGC, gene_kind, status do módulo, éxons. "
             "<b>Inferências do app:</b> classe da proteína, agrupamentos, observações e verificações acima.</p>")
        self.audit_view.document().setDefaultStyleSheet(self.ctx.css())
        self.audit_view.setHtml(h)
