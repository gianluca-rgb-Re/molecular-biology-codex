"""Explorador de genoma: regiões (BGCs) e genes-âncora classificados, ordenáveis e filtráveis."""
from __future__ import annotations
import csv
import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import genoteca
from ..antismash import CLASS_COLORS, display_name
from .common import Context


class NumItem(QTableWidgetItem):
    """Item que ordena por valor numérico (guardado em UserRole+1)."""

    def __init__(self, value: float, text: str | None = None):
        super().__init__(text if text is not None else f"{value:,.0f}".replace(",", "."))
        self.setData(Qt.UserRole + 1, float(value))
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other) -> bool:  # noqa: N802
        a, b = self.data(Qt.UserRole + 1), other.data(Qt.UserRole + 1)
        return (a if a is not None else 0) < (b if b is not None else 0)


def _alerts(row) -> list[str]:
    from .. import analysis
    return analysis._cds_alerts(row)[0]


class GenomeExplorer(QWidget):
    def __init__(self, ctx: Context, open_gene):
        super().__init__()
        self.ctx, self.open_gene = ctx, open_gene
        self.sid: int | None = None
        title = QLabel("🗺 Explorador do genoma — classificação dos genes-âncora e das regiões biossintéticas")
        title.setObjectName("h")
        self.species = QComboBox()
        self.species.currentIndexChanged.connect(self._species_changed)
        self.cls = QComboBox()
        self.cls.currentIndexChanged.connect(self.refresh_tables)
        self.prod = QComboBox()
        self.prod.currentIndexChanged.connect(self.refresh_tables)
        self.text = QLineEdit()
        self.text.setPlaceholderText("Filtrar por locus, scaffold ou domínio…")
        self.text.textChanged.connect(self.refresh_tables)
        top = QHBoxLayout()
        for w in (QLabel("Espécie:"), self.species, QLabel("Classe:"), self.cls, QLabel("Tipo de BGC:"), self.prod, self.text):
            top.addWidget(w)
        for text, fn in (("💾 Exportar CSV (genes)", self.export_genes), ("💾 Exportar CSV (regiões)", self.export_regions)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            top.addWidget(b)
        self.chips = QLabel()
        self.chips.setWordWrap(True)
        self.genes_t = self._table(["#", "Locus", "Classe da proteína", "Tipo de BGC", "Scaffold", "Início (scaffold)", "Fita", "aa", "Éxons", "Arquitetura (antiSMASH)",
                                    "Status do módulo antiSMASH", "Evidência", "Fonte da anotação", "Verificações da CDS (app)"])
        self.regions_t = self._table(["Região", "Scaffold", "Início", "Fim", "kb", "Tipo(s)", "Genes", "Genes-âncora", "Borda de contig", "Fonte"])
        self.genes_t.horizontalHeader().setSortIndicator(5, Qt.AscendingOrder)      # ordem do genoma
        self.regions_t.horizontalHeader().setSortIndicator(2, Qt.AscendingOrder)
        self.genes_t.cellDoubleClicked.connect(self._open)
        sp = QSplitter(Qt.Vertical)
        a, b = QWidget(), QWidget()
        la, lb = QVBoxLayout(a), QVBoxLayout(b)
        la.setContentsMargins(0, 0, 0, 0)
        lb.setContentsMargins(0, 0, 0, 0)
        la.addWidget(QLabel("<b>Genes-âncora</b> (clique no cabeçalho para ordenar; duplo clique abre a carta)"))
        la.addWidget(self.genes_t)
        lb.addWidget(QLabel("<b>Regiões biossintéticas (BGCs)</b>"))
        lb.addWidget(self.regions_t)
        sp.addWidget(a)
        sp.addWidget(b)
        sp.setSizes([480, 220])
        lay = QVBoxLayout(self)
        lay.addWidget(title)
        lay.addLayout(top)
        lay.addWidget(self.chips)
        lay.addWidget(sp, 1)
        ctx.dataChanged.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSortingEnabled(True)
        t.setAlternatingRowColors(False)
        return t

    def refresh(self) -> None:
        cur = self.species.currentData()
        self.species.blockSignals(True)
        self.species.clear()
        self.species.addItem("Todas as espécies", None)
        for r in genoteca.species_list(self.ctx.db):
            self.species.addItem(r["name"] + (f" ({r['strain']})" if r["strain"] else ""), r["id"])
        self.species.setCurrentIndex(max(0, self.species.findData(cur)))
        self.species.blockSignals(False)
        self.sid = self.species.currentData()
        self.refresh_tables()

    def _species_changed(self) -> None:
        self.sid = self.species.currentData()
        self.refresh_tables()

    def _gene_rows(self) -> list[dict]:
        out = []
        for r in genoteca.all_core_genes(self.ctx.db, self.sid):
            doms = [d for d in genoteca.domains_of(r) if d["kind"] == "pks"]
            meta = genoteca.gene_meta(r)
            mod = meta.get("module", {})
            parts = json.loads(r["parts"] or "[]")
            out.append({"row": r, "locus": r["locus_tag"], "cls": r["gene_class"], "prod": (r["bgc_products"] or "—"), "scaf": r["scaffold"] or r["contig"] or "",
                        "pos": (r["offset"] or 0) + (r["start"] or 0) + 1, "strand": "+" if (r["strand"] or 1) != -1 else "−", "aa": len(r["protein"] or ""),
                        "exons": len(parts), "doms": "–".join(display_name(d["name"]) for d in sorted(doms, key=lambda d: (d["start"], d["end"]))) or "—",
                        "mod": "completo" if mod.get("complete") else "incompleto" if mod.get("incomplete") else "—",
                        "src": (r["bgc_name"] and "antiSMASH") or (meta.get("screen") and f"triagem {meta['screen']} (heurística)") or "manual",
                        "cds": "não verificável" if genoteca.model_for_gene(r) is None else ("OK" if not _alerts(r) else "; ".join(_alerts(r))),
                        "ev": genoteca.top_stage(self.ctx.db, r["id"]), "id": r["id"]})
        return out

    def refresh_tables(self) -> None:
        rows = self._gene_rows()
        classes = sorted({r["cls"] for r in rows})
        prods = sorted({p for r in rows for p in r["prod"].split(",") if p and p != "—"})
        for combo, items, label in ((self.cls, classes, "todas"), (self.prod, prods, "todos")):
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(label)
            combo.addItems(items)
            combo.setCurrentIndex(max(0, combo.findText(cur)))
            combo.blockSignals(False)
        c, p, q = self.cls.currentText(), self.prod.currentText(), self.text.text().strip().lower()
        show = [r for r in rows if (c == "todas" or r["cls"] == c) and (p == "todos" or p in r["prod"].split(","))
                and (not q or q in r["locus"].lower() or q in r["scaf"].lower() or q in r["doms"].lower())]
        t = self.genes_t
        t.setSortingEnabled(False)
        t.setRowCount(len(show))
        stage_names = [s[1] for s in genoteca.STAGES]
        for i, r in enumerate(show):
            vals = [NumItem(i + 1), QTableWidgetItem(r["locus"]), QTableWidgetItem(r["cls"]), QTableWidgetItem(r["prod"]), QTableWidgetItem(r["scaf"]),
                    NumItem(r["pos"]), QTableWidgetItem(r["strand"]), NumItem(r["aa"]), NumItem(r["exons"]), QTableWidgetItem(r["doms"]),
                    QTableWidgetItem(r["mod"]), NumItem(r["ev"], f"{r['ev']} · {stage_names[r['ev']]}"), QTableWidgetItem(r["src"]), QTableWidgetItem(r["cds"])]
            vals[2].setForeground(QColor(CLASS_COLORS.get(r["cls"], "#8a95a5")))
            vals[1].setData(Qt.UserRole, r["id"])
            vals[10].setToolTip("Classificação original do antiSMASH; não indica, por si, truncamento do gene ou da proteína.")
            if r["cds"] not in ("OK", "não verificável"):
                vals[12].setForeground(QColor("#e0a458"))
            for k, it in enumerate(vals):
                t.setItem(i, k, it)
        t.setSortingEnabled(True)
        t.resizeColumnsToContents()
        # regiões
        regs = []
        for s in genoteca.species_list(self.ctx.db):
            if self.sid and s["id"] != self.sid:
                continue
            for b in genoteca.bgcs_of_species(self.ctx.db, s["id"]):
                regs.append((s, b))
        rt = self.regions_t
        rt.setSortingEnabled(False)
        rt.setRowCount(len(regs))
        for i, (s, b) in enumerate(regs):
            meta = genoteca.bgc_meta(b)
            off = meta.get("offset", 0) or 0
            genes = genoteca.genes_of_bgc(self.ctx.db, b["id"])
            core = [g["locus_tag"] for g in genes if g["gene_class"] in ("PKS", "NRPS", "PKS-NRPS", "NRPS-like", "Terpeno")]
            vals = [QTableWidgetItem(b["name"]), QTableWidgetItem(meta.get("scaffold", b["contig"] or "")), NumItem(off + b["start"] + 1), NumItem(off + b["end"]),
                    NumItem((b["end"] - b["start"]) / 1000, f"{(b['end'] - b['start']) / 1000:.1f}"), QTableWidgetItem(b["products"] or "—"), NumItem(len(genes)),
                    QTableWidgetItem(", ".join(core) or "—"), QTableWidgetItem("sim" if b["contig_edge"] else "não"), QTableWidgetItem(b["source"] or "")]
            for k, it in enumerate(vals):
                rt.setItem(i, k, it)
        rt.setSortingEnabled(True)
        rt.resizeColumnsToContents()
        # resumo
        by_cls: dict[str, int] = {}
        for r in rows:
            by_cls[r["cls"]] = by_cls.get(r["cls"], 0) + 1
        by_prod: dict[str, int] = {}
        for _s, b in regs:
            for pr in (b["products"] or "—").split(","):
                by_prod[pr] = by_prod.get(pr, 0) + 1
        self.chips.setText("<b>Genes-âncora:</b> " + (" &nbsp; ".join(f"<span style='color:{CLASS_COLORS.get(k, '#8a95a5')}'><b>{k}: {v}</b></span>"
                                                                     for k, v in sorted(by_cls.items(), key=lambda kv: -kv[1])) or "nenhum")
                           + " &nbsp;|&nbsp; <b>Regiões por tipo:</b> " + (" &nbsp; ".join(f"{k}: {v}" for k, v in sorted(by_prod.items(), key=lambda kv: -kv[1])) or "nenhuma"))
        self._shown, self._regs = show, regs

    def _open(self, row: int, _col: int) -> None:
        it = self.genes_t.item(row, 1)
        if it:
            self.open_gene(it.data(Qt.UserRole))

    def export_genes(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, "Exportar genes", "genes_ancora.csv", "CSV (*.csv)")
        if p:
            with open(p, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow([self.genes_t.horizontalHeaderItem(c).text() for c in range(self.genes_t.columnCount())])
                for r in range(self.genes_t.rowCount()):
                    w.writerow([self.genes_t.item(r, c).text() for c in range(self.genes_t.columnCount())])

    def export_regions(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, "Exportar regiões", "regioes_bgc.csv", "CSV (*.csv)")
        if p:
            with open(p, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow([self.regions_t.horizontalHeaderItem(c).text() for c in range(self.regions_t.columnCount())])
                for r in range(self.regions_t.rowCount()):
                    w.writerow([self.regions_t.item(r, c).text() for c in range(self.regions_t.columnCount())])
