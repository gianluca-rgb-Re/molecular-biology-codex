"""Janela do modelo gênico refinado: estrutura, sequências sem íntrons, estatísticas, domínios e simulação/edição."""
from __future__ import annotations
import html
import json
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSplitter, QTabWidget,
                               QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from .. import antismash, genoteca
from ..antismash import CLASS_COLORS, DOMAIN_COLORS, display_name
from ..analysis import source_label
from ..genemodel import GeneModel, first_divergence, wrap_fasta
from ..render import PALETTES
from .common import ArticleBrowser
from .gfx import ZoomView

W = 1100


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


class GeneModelDialog(QDialog):
    def __init__(self, ctx, row, parent=None, on_saved=None):
        super().__init__(parent)
        self.ctx, self.row, self.on_saved = ctx, row, on_saved
        self.gid = row["id"]
        self.meta = genoteca.gene_meta(row)
        self.domains = genoteca.domains_of(row)
        self.original = genoteca.model_for_gene(row, use_user=False)
        self.user_saved = bool(row["user_parts"])
        self.work = genoteca.model_for_gene(row, use_user=True)
        self.theme = ctx.theme
        self.pal = PALETTES[self.theme]
        self.setWindowTitle(f"Modelo gênico — {row['locus_tag']}")
        self.resize(1250, 820)
        lay = QVBoxLayout(self)
        self.header = QLabel()
        self.header.setWordWrap(True)
        lay.addWidget(self.header)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self._tab_structure()
        self._tab_sequences()
        self._tab_stats()
        self._tab_domains()
        self._tab_edit()
        self.refresh_all()

    # ------------------------------------------------------------ utilidades
    def _where(self, a: int, b: int, m: GeneModel) -> str:
        s, e = m.rel_to_local(a, b)
        ss, se = m.to_scaffold(s, e)
        return f"{m.scaffold}:{_fmt(ss)}–{_fmt(se)}"

    def refresh_all(self) -> None:
        m = self.work
        st = m.stats()
        edited = " · <b style='color:#e0a458'>✎ modelo editado por você</b>" if self.user_saved else ""
        span = self._where(0, len(m.genomic), m)
        col = CLASS_COLORS.get(self.row["gene_class"], "#8a95a5")
        self.header.setText(
            f"<span style='font-size:15pt; color:{col}'><b>{html.escape(self.row['locus_tag'])}</b></span> &nbsp; {html.escape(self.row['product'] or '')}"
            f"<br>{self.row['gene_class']} · fita {st['strand']} · {span} · <b>{st['exons']}</b> éxons / <b>{st['introns']}</b> íntrons · "
            f"CDS <b>{_fmt(st['cds_nt'])}</b> nt · proteína <b>{_fmt(st['aa'])}</b> aa{edited}")
        self._draw_structure()
        self._fill_sequences()
        self._fill_stats()
        self._fill_domains()
        self._fill_edit()

    # ------------------------------------------------------------- estrutura
    def _tab_structure(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        self.scene = QGraphicsScene()
        self.view = ZoomView(self.scene)
        self.view.autofit = True
        self.struct_table = QTableWidget(0, 9)
        self.struct_table.setHorizontalHeaderLabels(["Tipo", "Nº", "Comprimento (nt)", "Local (início–fim)", "Scaffold (início–fim)", "CDS (nt)", "aminoácidos",
                                                     "Sítios 5′/3′", "Fase"])
        self.struct_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        sp = QSplitter(Qt.Vertical)
        sp.addWidget(self.view)
        sp.addWidget(self.struct_table)
        sp.setSizes([330, 320])
        l.addWidget(sp)
        self.tabs.addTab(w, "🧬 Estrutura éxon/íntron")

    def _draw_structure(self) -> None:
        sc, m, pal = self.scene, self.work, self.pal
        sc.clear()
        n = len(m.genomic)
        k = W / max(1, n)
        y0 = 70
        t = QGraphicsSimpleTextItem(f"Gene orientado 5′ → 3′ (fita {'+' if m.strand != -1 else '−'}); {_fmt(n)} pb")
        t.setBrush(QBrush(QColor(pal["muted"])))
        t.setPos(0, 0)
        sc.addItem(t)
        f = QFont()
        f.setPointSize(8)
        sc.addLine(0, y0 + 15, W, y0 + 15, QPen(QColor(pal["border"]), 2))
        for i in m.introns():
            x1, x2 = i.a * k, i.b * k
            path = sc.addPolygon(QPolygonF([QPointF(x1, y0 + 15), QPointF((x1 + x2) / 2, y0 - 8), QPointF(x2, y0 + 15)]),
                                 QPen(QColor(pal["muted"]), 1.5), QBrush(Qt.NoBrush))
            path.setToolTip(f"Íntron {i.index}: {i.length} nt · {i.donor}…{i.acceptor} · {i.class_} · fase {i.phase}")
            lab = QGraphicsSimpleTextItem(f"{i.index}")
            lab.setFont(f)
            lab.setBrush(QBrush(QColor(pal["muted"])))
            lab.setPos((x1 + x2) / 2 - 3, y0 - 24)
            sc.addItem(lab)
        for e, (a, b) in enumerate(m.exons_rel, 1):
            r = QGraphicsRectItem(a * k, y0, max(2, (b - a) * k), 30)
            r.setBrush(QBrush(QColor(CLASS_COLORS.get(self.row["gene_class"], "#4cc2b0"))))
            r.setPen(QPen(QColor("#1c2430")))
            r.setToolTip(f"Éxon {e}: {b - a} nt · {self._where(a, b, m)}")
            sc.addItem(r)
            if (b - a) * k > 18:
                tx = QGraphicsSimpleTextItem(str(e))
                tx.setFont(f)
                tx.setBrush(QBrush(QColor("#ffffff")))
                tx.setPos(a * k + 3, y0 + 8)
                sc.addItem(tx)
        # códons de início e parada
        cs = m.exons_rel[0][0] + (m.codon_start - 1)
        sc.addPolygon(QPolygonF([QPointF(cs * k, y0 + 38), QPointF(cs * k - 5, y0 + 48), QPointF(cs * k + 5, y0 + 48)]), QPen(QColor("#6fcf6f")), QBrush(QColor("#6fcf6f")))
        ce = m.exons_rel[-1][1]
        sc.addRect(ce * k - 4, y0 + 38, 8, 8, QPen(QColor("#e06c6c")), QBrush(QColor("#e06c6c")))
        legend = QGraphicsSimpleTextItem("▲ ATG (início)   ■ códon de parada   ▭ éxons   ⌃ íntrons (numerados)")
        legend.setFont(f)
        legend.setBrush(QBrush(QColor(pal["muted"])))
        legend.setPos(0, y0 + 52)
        sc.addItem(legend)
        # domínios mapeados sobre o gene
        rows = {"pks": 0, "pfam": 1, "tigr": 2, "other": 2}
        y1 = y0 + 85
        for d in self.domains:
            if d["end"] <= d["start"]:
                continue
            a, b = m.aa_span_rel(d["start"], d["end"])
            ry = y1 + rows.get(d["kind"], 2) * 24
            r = QGraphicsRectItem(a * k, ry, max(3, (b - a) * k), 18)
            c = QColor(DOMAIN_COLORS.get(d["short"], "#8a95a5"))
            c.setAlpha(210 if d["kind"] == "pks" else 120)
            r.setBrush(QBrush(c))
            r.setPen(QPen(QColor("#1c2430")))
            r.setToolTip(f"{d['name']} · aa {d['start']}–{d['end']} · {d['tool']} · E={d['evalue']}")
            sc.addItem(r)
            tx = QGraphicsSimpleTextItem(d["short"])
            tx.setFont(f)
            tx.setBrush(QBrush(QColor("#ffffff" if d["kind"] == "pks" else pal["text"])))
            tx.setPos(a * k + 2, ry + 2)
            sc.addItem(tx)
        sc.addItem(self._small("Domínios sobre o gene (linha 1: antiSMASH/PKS; linha 2: Pfam; linha 3: TIGRFAM/outros) — repare nos que atravessam íntrons", 0, y1 - 20))
        sc.setSceneRect(sc.itemsBoundingRect().adjusted(-8, -8, 8, 8))
        self.view.fitInView(sc.sceneRect(), Qt.KeepAspectRatio)
        # tabela
        tb, intr, ex = self.struct_table, m.introns(), m.exon_table()
        rows_ = []
        for i, e in enumerate(ex):
            rows_.append(("Éxon", e["n"], e["len"], e["local"], e["scaffold"], f"{_fmt(e['cds_from'])}–{_fmt(e['cds_to'])}", f"{e['aa_from']}–{e['aa_to']}", "", ""))
            if i < len(intr):
                it = intr[i]
                s, en = m.rel_to_local(it.a, it.b)
                rows_.append(("Íntron", it.index, it.length, (s, en), m.to_scaffold(s, en), "", "", f"{it.donor}…{it.acceptor} ({it.class_})", it.phase))
        tb.setRowCount(len(rows_))
        for r, vals in enumerate(rows_):
            for c, v in enumerate(vals):
                txt = f"{_fmt(v[0])}–{_fmt(v[1])}" if isinstance(v, tuple) else (_fmt(v) if isinstance(v, int) and c == 2 else str(v))
                it_ = QTableWidgetItem(txt)
                if vals[0] == "Íntron":
                    it_.setForeground(QColor(self.pal["muted"]))
                tb.setItem(r, c, it_)
        tb.resizeColumnsToContents()

    def _small(self, text: str, x: float, y: float):
        t = QGraphicsSimpleTextItem(text)
        f = QFont()
        f.setPointSize(8)
        t.setFont(f)
        t.setBrush(QBrush(QColor(self.pal["muted"])))
        t.setPos(x, y)
        return t

    # ------------------------------------------------------------ sequências
    def _tab_sequences(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.seq_kind = QComboBox()
        self.seq_kind.addItems(["Genômica (éxons MAIÚSCULOS, íntrons minúsculos)", "cDNA / CDS (sem íntrons)", "Proteína"])
        self.seq_kind.currentIndexChanged.connect(self._fill_sequences)
        bar.addWidget(QLabel("Sequência:"))
        bar.addWidget(self.seq_kind, 1)
        for text, fn in (("📋 Copiar FASTA", self._copy_fasta), ("💾 Exportar FASTA", self._export_fasta), ("💾 GenBank do gene", self._export_gb)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            bar.addWidget(b)
        l.addLayout(bar)
        self.seq_info = QLabel()
        self.seq_info.setObjectName("muted")
        l.addWidget(self.seq_info)
        self.seq_view = QTextEdit()
        self.seq_view.setReadOnly(True)
        self.seq_view.setFont(QFont("monospace", 10))
        l.addWidget(self.seq_view, 1)
        self.tabs.addTab(w, "🔤 Sequências")

    def _seq_text(self) -> tuple[str, str]:
        m, k = self.work, self.seq_kind.currentIndex()
        if k == 0:
            return m.genomic, "gene genômico (com íntrons)"
        if k == 1:
            return m.coding_seq(), "cDNA/CDS (íntrons removidos)"
        return m.protein(), "proteína"

    def _fill_sequences(self) -> None:
        m, k = self.work, self.seq_kind.currentIndex()
        seq, desc = self._seq_text()
        unit = "aa" if k == 2 else "nt"
        self.seq_info.setText(f"{desc}: {_fmt(len(seq))} {unit}"
                              + (f" · {len(m.exons_rel)} éxons unidos, {len(m.exons_rel) - 1} íntrons removidos" if k == 1 else ""))
        out, line = [], 60
        if k == 0:
            mask = [False] * len(seq)
            for a, b in m.exons_rel:
                for i in range(a, b):
                    mask[i] = True
            ex_color, in_color = "#4cc2b0", "#8a95a5"
            for start in range(0, len(seq), line):
                chunk = seq[start:start + line]
                html_ = ""
                for j in range(0, len(chunk), 10):
                    blk = chunk[j:j + 10]
                    cur = ""
                    for q, ch in enumerate(blk):
                        isex = mask[start + j + q]
                        cur += f"<span style='color:{ex_color if isex else in_color}'>{ch.upper() if isex else ch.lower()}</span>"
                    html_ += cur + " "
                out.append(f"<span style='color:#7a8fd9'>{start + 1:>7}</span>  {html_}")
        else:
            for start in range(0, len(seq), line):
                chunk = seq[start:start + line]
                out.append(f"<span style='color:#7a8fd9'>{start + 1:>7}</span>  " + " ".join(chunk[j:j + 10] for j in range(0, len(chunk), 10)))
        self.seq_view.setHtml("<pre style='font-family:monospace'>" + "\n".join(out) + "</pre>")

    def _fasta(self) -> str:
        seq, desc = self._seq_text()
        sp = genoteca.get_species(self.ctx.db, self.row["species_id"])
        return wrap_fasta(self.row["locus_tag"], f"{desc} [{sp['name']}] {len(seq)} {'aa' if self.seq_kind.currentIndex() == 2 else 'nt'}", seq)

    def _copy_fasta(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._fasta())

    def _export_fasta(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, "Exportar FASTA", f"{self.row['locus_tag']}_{['gene', 'cds', 'prot'][self.seq_kind.currentIndex()]}.fasta", "FASTA (*.fasta *.fa)")
        if p:
            Path(p).write_text(self._fasta(), encoding="utf-8")

    def _export_gb(self) -> None:
        from Bio.Seq import Seq
        from Bio.SeqFeature import CompoundLocation, FeatureLocation, SeqFeature
        from Bio.SeqRecord import SeqRecord
        from Bio import SeqIO
        m = self.work
        p, _ = QFileDialog.getSaveFileName(self, "GenBank do gene (abre no Geneious)", f"{self.row['locus_tag']}.gb", "GenBank (*.gb *.gbk)")
        if not p:
            return
        locs = [FeatureLocation(a, b, strand=1) for a, b in m.exons_rel]
        loc = locs[0] if len(locs) == 1 else CompoundLocation(locs)
        rec = SeqRecord(Seq(m.genomic), id=self.row["locus_tag"][:16], name=self.row["locus_tag"][:16],
                        description=f"{self.row['product']} (orientado 5'->3'; scaffold {m.scaffold})", annotations={"molecule_type": "DNA"})
        rec.features.append(SeqFeature(FeatureLocation(0, len(m.genomic), strand=1), type="gene", qualifiers={"locus_tag": [self.row["locus_tag"]]}))
        rec.features.append(SeqFeature(loc, type="CDS", qualifiers={"locus_tag": [self.row["locus_tag"]], "product": [self.row["product"] or ""],
                                                                    "translation": [m.protein()], "codon_start": [m.codon_start]}))
        SeqIO.write(rec, p, "genbank")

    # ---------------------------------------------------------- estatísticas
    def _tab_stats(self) -> None:
        self.stats_view = ArticleBrowser()
        self.tabs.addTab(self.stats_view, "📊 Estatísticas e verificações")

    def _fill_stats(self) -> None:
        m = self.work
        s, c = m.stats(), m.checks()
        ok = lambda v: "<span style='color:#6fcf6f'>✔</span>" if v else "<span style='color:#e06c6c'>✖</span>"  # noqa: E731
        css = f"<style>td {{padding:3px 10px}} th {{text-align:left}}</style>"
        rows = [("Aminoácidos (sem o códon de parada)", _fmt(s["aa"])), ("CDS (nt, com parada)", _fmt(s["cds_nt"])),
                ("Gene genômico (nt)", _fmt(s["genomic_nt"])), ("Éxons / íntrons", f"{s['exons']} / {s['introns']}"),
                ("Total de íntrons (nt)", f"{_fmt(s['intron_total_nt'])} ({100 * s['intron_total_nt'] / max(1, s['genomic_nt']):.1f}% do gene)"),
                ("Tamanho médio do éxon / íntron (nt)", f"{s['mean_exon']:.0f} / {s['mean_intron']:.0f}"),
                ("Menor / maior íntron (nt)", f"{s['min_intron']} / {s['max_intron']}"),
                ("Íntrons por kb de CDS", f"{s['introns_per_kb_cds']:.2f}"),
                ("GC (gene / CDS)", f"{s['gc_genomic']:.1f}% / {s['gc_cds']:.1f}%"), ("GC3 (3ª posição dos códons)", f"{s['gc3']:.1f}%")]
        if "mw_kda" in s:
            rows += [("Massa molecular (calculada)", f"{s['mw_kda']:.1f} kDa"), ("pI teórico", f"{s['pi']:.2f}"),
                     ("Índice de instabilidade", f"{s['instability']:.1f} ({'instável' if s['instability'] > 40 else 'estável'} pelo critério de Guruprasad)"),
                     ("GRAVY (hidropatia média)", f"{s['gravy']:.3f}"), ("Aromaticidade", f"{s['aromaticity']:.3f}")]
        chk = [("Quadro de leitura: comprimento múltiplo de 3", c["frame_multiple_3"]), ("Começa com ATG", c["start_ATG"]),
               ("Termina em códon de parada", c["stop_codon"]), (f"Sem paradas internas (encontradas: {c['internal_stops']})", c["internal_stops"] == 0),
               (f"Íntrons canônicos GT–AG: {c['canonical_introns']} de {c['n_introns']}", c["canonical_introns"] == c["n_introns"])]
        if c["matches_stored"] is not None:
            chk.append(("Proteína do modelo = proteína do arquivo GenBank", c["matches_stored"]))
        comp = s.get("composition", {})
        tot = max(1, sum(comp.values()))
        bars = "".join(f"<tr><td><b>{a}</b></td><td>{v}</td><td>{100 * v / tot:.1f}%</td><td style='color:#4cc2b0'>{'█' * int(40 * v / tot * 4)}</td></tr>"
                       for a, v in sorted(comp.items(), key=lambda kv: -kv[1]))
        self.stats_view.document().setDefaultStyleSheet(self.ctx.css())
        self.stats_view.setHtml(css + "<h3>Estatísticas do modelo</h3><table>" + "".join(f"<tr><td>{a}</td><td><b>{b}</b></td></tr>" for a, b in rows)
                                + "</table><h3>Verificações do modelo</h3><table>" + "".join(f"<tr><td>{ok(v)}</td><td>{a}</td></tr>" for a, v in chk)
                                + "</table><h3>Composição de aminoácidos</h3><table>" + bars + "</table>"
                                "<p class='muted'>Valores calculados a partir da sequência (Biopython/ProtParam). São propriedades teóricas, não medições.</p>")

    # --------------------------------------------------------------- domínios
    def _tab_domains(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)
        self.dom_table = QTableWidget(0, 9)
        self.dom_table.setHorizontalHeaderLabels(["Domínio", "Fonte", "aa início", "aa fim", "Tamanho (aa)", "Éxons", "Scaffold", "E-value", "Observações do arquivo"])
        self.dom_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.dom_note = ArticleBrowser()
        self.dom_note.setMaximumHeight(210)
        l.addWidget(self.dom_table, 1)
        l.addWidget(self.dom_note)
        self.tabs.addTab(w, "🔬 Domínios × éxons")

    def _fill_domains(self) -> None:
        m, tb = self.work, self.dom_table
        doms = [d for d in self.domains if d["end"] > d["start"]]
        tb.setRowCount(len(doms))
        n_aa = len(m.protein())
        for r, d in enumerate(doms):
            e1, e2 = m.exon_of_aa(d["start"]), m.exon_of_aa(d["end"])
            a, b = m.aa_span_rel(d["start"], d["end"])
            vals = [display_name(d["name"]), source_label(d), d["start"], d["end"], d["end"] - d["start"] + 1,
                    f"{e1}" if e1 == e2 else f"{e1}→{e2}", self._where(a, b, m), d["evalue"], " | ".join(d["notes"]) or d["description"]]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if c == 0:
                    it.setToolTip(f"Identificador original no arquivo: {d['name']}")
                if d["kind"] == "pks" and c == 0:
                    it.setForeground(QColor(DOMAIN_COLORS.get(d["short"], "#8a95a5")))
                tb.setItem(r, c, it)
        tb.resizeColumnsToContents()
        pks = sorted((d for d in doms if d["kind"] == "pks"), key=lambda d: d["start"])
        gaps, pos = [], 1
        for d in pks:
            if d["start"] - pos >= 80:
                gaps.append((pos, d["start"] - 1))
            pos = max(pos, d["end"] + 1)
        if pks and n_aa - pos + 1 >= 80:
            gaps.append((pos, n_aa))
        names = [d["short"] for d in pks]
        mod = self.meta.get("module", {})
        txt = [f"<p><b>Cobertura:</b> {sum(d['end'] - d['start'] + 1 for d in pks)} de {n_aa} aa ({100 * sum(d['end'] - d['start'] + 1 for d in pks) / max(1, n_aa):.0f}%) "
               f"estão em domínios PKS/NRPS anotados pelo antiSMASH.</p>"]
        if gaps:
            txt.append("<p><b>Regiões ≥ 80 aa sem domínio PKS/NRPS anotado:</b> " + ", ".join(f"{a}–{b} ({b - a + 1} aa, éxon {m.exon_of_aa(a)}→{m.exon_of_aa(b)})" for a, b in gaps) + "</p>")
        if mod:
            txt.append(f"<p><b>Status do módulo (antiSMASH):</b> {'iterativo' if mod.get('iterative') else 'não iterativo'}; "
                       f"{'completo' if mod.get('complete') else 'incompleto' if mod.get('incomplete') else '—'} (classificação original do antiSMASH; não indica, por si, truncamento)"
                       + (f"; pareamento de monômeros: {', '.join(mod['monomer_pairings'])}" if mod.get("monomer_pairings") else "") + ".</p>")
        if self.row["gene_class"] in ("PKS", "PKS-NRPS") and pks and "ACP" not in names:
            txt.append("<p style='color:#e0a458'><b>Observação:</b> nenhum domínio ACP (PKS_PP) consta entre os domínios antiSMASH desta proteína. Há várias explicações possíveis "
                       "(ACP divergente não detectado pelo HMM, ACP em trans, anotação do gene) — <b>não é uma conclusão sobre truncamento nem sobre atividade</b>. "
                       "Hipóteses a testar: RNA-seq/RT-PCR cobrindo a região C-terminal, reanálise do modelo gênico (aba «Simular / editar»), "
                       "e busca de ACP/PP-binding vizinho.</p>")
        txt.append("<p class='muted'>Domínios são predições (antiSMASH/HMMs). A presença de um domínio não demonstra atividade catalítica.</p>")
        self.dom_note.document().setDefaultStyleSheet(self.ctx.css())
        self.dom_note.setHtml("".join(txt))

    # ------------------------------------------------------ simular / editar
    def _tab_edit(self) -> None:
        w = QWidget()
        l = QHBoxLayout(w)
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>1) Simular retenção de íntrons</b> (marque os íntrons a reter no mRNA):"))
        self.ret_boxes: list[QCheckBox] = []
        self.ret_host = QWidget()
        self.ret_lay = QVBoxLayout(self.ret_host)
        left.addWidget(self.ret_host)
        self.sim_view = ArticleBrowser()
        left.addWidget(self.sim_view, 1)
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>2) Editar os éxons</b> (coordenadas locais do GenBank, 1-based, fita direta; edite as células):"))
        self.edit_table = QTableWidget(0, 3)
        self.edit_table.setHorizontalHeaderLabels(["Éxon", "Início", "Fim"])
        right.addWidget(self.edit_table, 1)
        hb = QHBoxLayout()
        for text, fn in (("＋ Éxon", self._add_exon), ("− Remover", self._del_exon), ("▶ Pré-visualizar", self._preview_edit)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            hb.addWidget(b)
        right.addLayout(hb)
        hb2 = QHBoxLayout()
        b1 = QPushButton("💾 Salvar como meu modelo")
        b1.setObjectName("primary")
        b1.clicked.connect(self._save_user_model)
        b2 = QPushButton("↩ Restaurar modelo original")
        b2.clicked.connect(self._restore_original)
        hb2.addWidget(b1)
        hb2.addWidget(b2)
        right.addLayout(hb2)
        self.edit_note = QLabel("O modelo original do arquivo nunca é apagado. «Meu modelo» é uma hipótese sua (por exemplo, após ver RNA-seq).")
        self.edit_note.setWordWrap(True)
        self.edit_note.setObjectName("muted")
        right.addWidget(self.edit_note)
        l.addLayout(left, 1)
        l.addLayout(right, 1)
        self.tabs.addTab(w, "🧪 Simular / editar")

    def _fill_edit(self) -> None:
        m = self.work
        for b in self.ret_boxes:
            self.ret_lay.removeWidget(b)
            b.deleteLater()
        self.ret_boxes = []
        for i in m.introns():
            cb = QCheckBox(f"Íntron {i.index} — {i.length} nt, {i.donor}…{i.acceptor}, fase {i.phase}")
            cb.stateChanged.connect(self._simulate)
            self.ret_lay.addWidget(cb)
            self.ret_boxes.append(cb)
        self.edit_table.setRowCount(len(m.exons_rel))
        for r, (s, e) in enumerate(m.exons_local()):
            for c, v in enumerate((r + 1, s, e)):
                it = QTableWidgetItem(str(v))
                if c == 0:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.edit_table.setItem(r, c, it)
        self._simulate()

    def _compare_html(self, new: GeneModel, base: GeneModel, title: str) -> str:
        bp, np_ = base.protein(), new.protein()
        full = new.full_translation()
        d = first_divergence(bp, np_)
        stop_in = len(np_) + 1 if "*" in full[:-1] or not full.endswith("*") else None
        lines = [f"<h3>{title}</h3>", f"<p>Proteína original: <b>{len(bp)}</b> aa → resultante: <b>{len(np_)}</b> aa "
                 f"(<b>{len(np_) - len(bp):+d}</b>).</p>"]
        if d is None:
            lines.append("<p style='color:#6fcf6f'>✔ A proteína resultante é idêntica à original.</p>")
        else:
            lines.append(f"<p>Primeira diferença na posição <b>{d}</b> (éxon {base.exon_of_aa(min(d, len(bp)))}).</p>")
            hit = []
            for dm in self.domains:
                if dm["end"] > dm["start"] and dm["kind"] == "pks":
                    state = "perdido" if len(np_) < dm["start"] else "truncado" if len(np_) < dm["end"] else ("alterado a jusante da diferença" if d <= dm["end"] and d >= dm["start"] else "")
                    if d <= dm["end"] and not state:
                        state = "deslocado/alterado"
                    if state:
                        hit.append(f"{dm['short']} ({dm['start']}–{dm['end']}): {state}")
            lines.append("<p><b>Impacto previsto nos domínios PKS:</b> " + ("; ".join(hit) if hit else "nenhum domínio PKS afetado") + ".</p>")
        if stop_in and not full.endswith("*"):
            lines.append("<p style='color:#e0a458'>⚠ Sem códon de parada no quadro: a tradução termina no fim da sequência disponível.</p>")
        if not new.checks()["frame_multiple_3"]:
            lines.append("<p style='color:#e0a458'>⚠ O comprimento da CDS não é múltiplo de 3 (deslocamento de quadro).</p>")
        lines.append("<p class='muted'>Simulação in silico: não prova que o evento ocorra na célula.</p>")
        return "".join(lines)

    def _simulate(self) -> None:
        ret = {i + 1 for i, cb in enumerate(self.ret_boxes) if cb.isChecked()}
        self.sim_view.document().setDefaultStyleSheet(self.ctx.css())
        if not ret:
            self.sim_view.setHtml("<p class='muted'>Marque um ou mais íntrons para ver o efeito da retenção na proteína.</p>")
            return
        self.sim_view.setHtml(self._compare_html(self.work.with_retained(ret), self.work, f"Retenção de íntron(s) {', '.join(map(str, sorted(ret)))}"))

    def _read_edit(self) -> list[tuple[int, int]]:
        out = []
        for r in range(self.edit_table.rowCount()):
            try:
                out.append((int(self.edit_table.item(r, 1).text()), int(self.edit_table.item(r, 2).text())))
            except (ValueError, AttributeError) as e:
                raise ValueError(f"Linha {r + 1}: use números inteiros.") from e
        return out

    def _add_exon(self) -> None:
        r = self.edit_table.rowCount()
        self.edit_table.setRowCount(r + 1)
        last = self.work.exons_local()[-1]
        for c, v in enumerate((r + 1, last[0], last[1])):
            self.edit_table.setItem(r, c, QTableWidgetItem(str(v)))

    def _del_exon(self) -> None:
        r = self.edit_table.currentRow()
        if r >= 0 and self.edit_table.rowCount() > 1:
            self.edit_table.removeRow(r)

    def _preview_edit(self) -> GeneModel | None:
        try:
            new = self.work.with_exons_local(self._read_edit())
        except ValueError as e:
            QMessageBox.warning(self, "Éxons inválidos", str(e))
            return None
        self.sim_view.document().setDefaultStyleSheet(self.ctx.css())
        self.sim_view.setHtml(self._compare_html(new, self.original or self.work, "Pré-visualização do modelo editado vs. original do arquivo"))
        return new

    def _save_user_model(self) -> None:
        new = self._preview_edit()
        if new is None:
            return
        genoteca.save_user_model(self.ctx.db, self.gid, new.exons_local())
        self.user_saved, self.work = True, new
        self.refresh_all()
        if self.on_saved:
            self.on_saved()

    def _restore_original(self) -> None:
        genoteca.save_user_model(self.ctx.db, self.gid, None)
        self.user_saved, self.work = False, self.original
        self.refresh_all()
        if self.on_saved:
            self.on_saved()
