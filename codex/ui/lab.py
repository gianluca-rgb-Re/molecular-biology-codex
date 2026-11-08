"""Laboratório: Genoteca (coleção de genes/BGCs estilo «dex», com antiSMASH/GenBank/Geneious) e cenários de raciocínio."""
from __future__ import annotations
import html
import json
from pathlib import Path

import yaml
from PySide6.QtCore import QPointF, QProcess, QRectF, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import (QBrush, QClipboard, QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QPainter, QPen,
                           QPixmap, QPolygonF)
from PySide6.QtWidgets import (QApplication, QCheckBox, QProgressDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                               QGraphicsPolygonItem, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QTabWidget, QTextEdit,
                               QVBoxLayout, QWidget)

from .. import antismash, genoteca
from ..antismash import CLASS_COLORS, DOMAIN_COLORS
from ..paths import bundled_content_dir, data_dir, user_content_dir
from ..render import PALETTES
from ..antismash import CORE_CLASSES, GENE_KINDS, display_name
from .common import ArticleBrowser, Context
from .genemodel_dialog import GeneModelDialog
from .genome_explorer import GenomeExplorer
from .gfx import ZoomView

CLASS_ICON = {"PKS": "🔴", "NRPS": "🟣", "PKS-NRPS": "🟠", "Terpeno": "🟢", "RiPP": "🔵", "Biossintético": "🟡",
              "Auxiliar": "🌸", "Transporte": "🔷", "Regulador": "🟩", "Resistência": "🟨", "Outro": "⚪"}


def render_gene_card(row, stages: set[int], theme: str, number: int) -> QPixmap:
    """Carta de gene (estilo «dex»): faixa da classe, código, produto e 6 marcadores de evidência."""
    pal = PALETTES[theme]
    w, h = 214, 124
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    col = QColor(CLASS_COLORS.get(row["gene_class"], "#8a95a5"))
    top = max(stages) if stages else 0
    p.setPen(QPen(col, 3))
    p.setBrush(QColor(pal["panel"]))
    p.drawRoundedRect(QRectF(2, 2, w - 4, h - 4), 10, 10)
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawRoundedRect(QRectF(2, 2, w - 4, 28), 10, 10)
    p.drawRect(QRectF(2, 18, w - 4, 12))
    f = QFont()
    f.setPointSize(9)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(QRectF(10, 4, w - 20, 24), Qt.AlignVCenter | Qt.AlignLeft, f"#{number:03d}  {row['gene_class']}")
    p.drawText(QRectF(10, 4, w - 20, 24), Qt.AlignVCenter | Qt.AlignRight, "★" * (1 if top >= 4 else 0) + (" ✔" if top >= 5 else ""))
    f.setPointSize(10)
    p.setFont(f)
    p.setPen(QColor(pal["text"]))
    fm = QFontMetrics(f)
    p.drawText(QPointF(12, 50), fm.elidedText(row["locus_tag"], Qt.ElideMiddle, w - 24))
    f2 = QFont()
    f2.setPointSize(8)
    p.setFont(f2)
    p.setPen(QColor(pal["muted"]))
    fm2 = QFontMetrics(f2)
    p.drawText(QPointF(12, 67), fm2.elidedText(row["product"] or "—", Qt.ElideRight, w - 24))
    n_aa = len(row["protein"] or "")
    try:
        n_ex = len(json.loads(row["parts"] or "[]"))
    except Exception:  # noqa: BLE001
        n_ex = 0
    p.drawText(QPointF(12, 82), (f"{n_aa} aa" if n_aa else "sem sequência") + (f" · {n_ex} éxons" if n_ex else "")
               + ("  ✎ modelo editado" if row["user_parts"] else ""))
    for k, (_s, name, _d, c) in enumerate(genoteca.STAGES):
        x = 16 + k * 31
        p.setPen(QPen(QColor(c), 2))
        p.setBrush(QColor(c) if k in stages else Qt.NoBrush)
        p.drawEllipse(QPointF(x, 102), 8, 8)
        p.setPen(QColor("#0b0f14") if k in stages else QColor(pal["muted"]))
        p.setFont(f2)
        p.drawText(QRectF(x - 8, 94, 16, 16), Qt.AlignCenter, str(k))
    p.end()
    return pm


class Worker(QThread):
    """Executa leitura pesada de arquivos fora da thread da interface."""
    done = Signal(object)
    failed = Signal(str)
    prog = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn(lambda s: self.prog.emit(s)))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


class GeneArrow(QGraphicsPolygonItem):
    def __init__(self, poly: QPolygonF, color: str, gid: int, on_click, tip: str, selected: bool):
        super().__init__(poly)
        self.gid, self._cb = gid, on_click
        self.setBrush(QBrush(QColor(color)))
        self.setPen(QPen(QColor("#ffffff" if selected else "#1c2430"), 3 if selected else 1))
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, e):  # noqa: N802
        self._cb(self.gid)


class BGCMap(ZoomView):
    """Mapa do BGC (setas por gene, cor pela classe) e trilha de domínios do gene selecionado."""
    WIDTH = 1100

    def __init__(self, theme: str):
        self._scene = QGraphicsScene()
        super().__init__(self._scene)
        self.theme = theme
        self.autofit = True
        self.setMinimumHeight(190)

    def show_genes(self, genes, selected: int | None, on_select, meta: dict | None = None) -> None:
        sc = self._scene
        sc.clear()
        pal = PALETTES[self.theme]
        if not genes:
            t = sc.addText("Selecione um BGC ou espécie com genes posicionados para ver o mapa.")
            t.setDefaultTextColor(QColor(pal["muted"]))
            return
        lo, hi = min(g["start"] for g in genes), max(g["end"] for g in genes)
        span = max(1, hi - lo)
        sc.addLine(0, 46, self.WIDTH, 46, QPen(QColor(pal["border"]), 2))
        meta = meta or {}
        for cs, ce, _st, cprod in meta.get("cores", []):
            x1, x2 = (cs - 1 - lo) / span * self.WIDTH, (ce - lo) / span * self.WIDTH
            band = QGraphicsRectItem(max(0, x1), 14, max(2, min(self.WIDTH, x2) - max(0, x1)), 8)
            band.setBrush(QBrush(QColor("#d9534f")))
            band.setPen(QPen(Qt.NoPen))
            band.setToolTip(f"Núcleo do protocluster ({cprod}): {cs}–{ce}")
            sc.addItem(band)
        f = QFont()
        f.setPointSize(7)
        for g in genes:
            x1 = (g["start"] - lo) / span * self.WIDTH
            x2 = max(x1 + 16, (g["end"] - lo) / span * self.WIDTH)
            head = min(12, (x2 - x1) * 0.45)
            top, bot, mid = 26, 66, 46
            if g["strand"] == -1:
                poly = QPolygonF([QPointF(x2, top), QPointF(x1 + head, top), QPointF(x1, mid), QPointF(x1 + head, bot), QPointF(x2, bot)])
            else:
                poly = QPolygonF([QPointF(x1, top), QPointF(x2 - head, top), QPointF(x2, mid), QPointF(x2 - head, bot), QPointF(x1, bot)])
            tip = f"{g['locus_tag']}\n{g['product']}\n{g['gene_class']} · {g['start']}–{g['end']} ({'+' if g['strand'] != -1 else '−'})"
            item = GeneArrow(poly, CLASS_COLORS.get(g["gene_class"], "#8a95a5"), g["id"], on_select, tip, g["id"] == selected)
            item.setZValue(3 if g["id"] == selected else 2)
            sc.addItem(item)
            lab = QGraphicsSimpleTextItem(g["locus_tag"].split("_")[-1][-6:])
            lab.setFont(f)
            lab.setBrush(QBrush(QColor(pal["muted"])))
            lab.setPos(x1, 68)
            sc.addItem(lab)
        sc.addText("").setPos(0, 0)
        off = meta.get("offset", 0) or 0
        scale = QGraphicsSimpleTextItem((f"{meta.get('scaffold', '')}: " if meta.get("scaffold") else "") +
                                        f"{lo + off + 1:,} – {hi + off:,} pb  ({(hi - lo) / 1000:.1f} kb)".replace(",", ".") +
                                        ("   ▬ barra vermelha = núcleo do protocluster (antiSMASH)" if meta.get("cores") else ""))
        scale.setBrush(QBrush(QColor(pal["muted"])))
        scale.setFont(f)
        scale.setPos(0, 4)
        sc.addItem(scale)
        sel = next((g for g in genes if g["id"] == selected), None)
        if sel is not None:
            self._domain_track(sel, 110)
        sc.setSceneRect(sc.itemsBoundingRect().adjusted(-10, -6, 10, 10))
        self.fitInView(sc.sceneRect(), Qt.KeepAspectRatio)

    def _domain_track(self, g, y: int) -> None:
        sc, pal = self._scene, PALETTES[self.theme]
        n_aa = len(g["protein"] or "")
        doms = genoteca.domains_of(g)
        t = QGraphicsSimpleTextItem(f"Domínios de {g['locus_tag']} ({n_aa} aa)" if doms else
                                    f"{g['locus_tag']}: sem domínios anotados (importe o resultado do antiSMASH para vê-los)")
        t.setBrush(QBrush(QColor(pal["text"])))
        t.setPos(0, y - 22)
        sc.addItem(t)
        W = self.WIDTH
        bar = QGraphicsRectItem(0, y, W, 20)
        bar.setBrush(QBrush(QColor(pal["panel2"])))
        bar.setPen(QPen(QColor(pal["border"])))
        sc.addItem(bar)
        total = max(n_aa, max((d["end"] for d in doms), default=1), 1)
        f = QFont()
        f.setPointSize(8)
        f.setBold(True)
        for d in doms:
            if d["end"] <= d["start"]:
                continue
            x1, x2 = d["start"] / total * W, d["end"] / total * W
            main = d.get("kind") == "pks"
            r = QGraphicsRectItem(x1, (y - 6) if main else (y + 30), max(10 if main else 4, x2 - x1), 32 if main else 12)
            c = QColor(DOMAIN_COLORS.get(d["short"], "#8a95a5") if main else "#6b7685")
            c.setAlpha(255 if main else 150)
            r.setBrush(QBrush(c))
            r.setPen(QPen(QColor("#1c2430")))
            r.setToolTip(f"{d['name']} ({d['start']}–{d['end']} aa) · {d.get('tool', '')}")
            sc.addItem(r)
            if main:
                tx = QGraphicsSimpleTextItem(QFontMetrics(f).elidedText(display_name(d["name"]), Qt.ElideRight, int(max(12, x2 - x1))))
                tx.setFont(f)
                tx.setBrush(QBrush(QColor("#ffffff")))
                tx.setPos(x1 + 3, y + 1)
                sc.addItem(tx)


class SpeciesDialog(QDialog):
    def __init__(self, parent=None, values: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Espécie")
        v = values or {}
        self.name, self.strain = QLineEdit(v.get("name", "")), QLineEdit(v.get("strain", ""))
        self.acc, self.file = QLineEdit(v.get("genome_accession", "")), QLineEdit(v.get("genome_file", ""))
        self.tax, self.notes = QLineEdit(v.get("taxonomy", "")), QPlainTextEdit(v.get("notes", ""))
        self.notes.setFixedHeight(70)
        b = QPushButton("Procurar…")
        b.clicked.connect(self._browse)
        fr = QHBoxLayout()
        fr.addWidget(self.file)
        fr.addWidget(b)
        form = QFormLayout(self)
        for lab, w in (("Nome da espécie*", self.name), ("Linhagem/isolado", self.strain), ("Acesso do genoma (NCBI)", self.acc),
                       ("Taxonomia/observação", self.tax)):
            form.addRow(lab, w)
        form.addRow("Arquivo do genoma (GenBank/FASTA)", fr)
        form.addRow("Notas", self.notes)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.setMinimumWidth(520)

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Genoma", "", "Sequências (*.gbk *.gb *.gbff *.gbf *.fa *.fasta *.fna);;Todos (*)")
        if p:
            self.file.setText(p)

    def _ok(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Espécie", "Informe o nome da espécie.")
            return
        self.accept()

    def values(self) -> dict:
        return dict(name=self.name.text().strip(), strain=self.strain.text().strip(), genome_accession=self.acc.text().strip(),
                    genome_file=self.file.text().strip(), taxonomy=self.tax.text().strip(), notes=self.notes.toPlainText().strip())


class GenotecaView(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.sid: int | None = None
        self.bid: int | None = None
        self.gid: int | None = None
        self.proc: QProcess | None = None
        self._touched = False
        self._worker = None
        self._build()
        ctx.themeChanged.connect(lambda _t: self.refresh())
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _btn(self, text: str, fn, tip: str = "", primary: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        if primary:
            b.setObjectName("primary")
        b.clicked.connect(lambda _=False: fn())
        return b

    def _build(self) -> None:
        self.stats = QLabel()
        bar = QHBoxLayout()
        title = QLabel("🧬 Genoteca — sua coleção de genes e BGCs")
        title.setObjectName("h")
        bar.addWidget(title)
        bar.addWidget(self.stats, 1)
        for b in (self._btn("＋ Espécie", self.new_species, "Cadastrar espécie/genoma", True),
                  self._btn("⬇ Importar antiSMASH / genoma (GenBank)", self.import_file, "Importa regiões (BGCs) de um GenBank do antiSMASH, "
                            "um genoma exportado do Geneious/NCBI (busca por locus_tag) ou proteínas em FASTA"),
                  self._btn("🔎 Gene no genoma", self.find_in_genome, "Localiza um gene por locus_tag no GenBank do genoma e importa a vizinhança"),
                  self._btn("▶ Rodar antiSMASH", self.run_antismash, "Executa o antiSMASH instalado localmente"),
                  self._btn("🌐 antiSMASH web", lambda: QDesktopServices.openUrl(QUrl(antismash.ANTISMASH_WEB)), "fungiSMASH (site oficial)"),
                  self._btn("＋ Gene manual", self.manual_gene)):
            bar.addWidget(b)
        # esquerda
        self.sp_list, self.bgc_list = QListWidget(), QListWidget()
        self.sp_list.currentRowChanged.connect(self._pick_species)
        self.bgc_list.currentRowChanged.connect(self._pick_bgc)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("<b>Espécies</b>"))
        ll.addWidget(self.sp_list, 2)
        hb = QHBoxLayout()
        hb.addWidget(self._btn("✎ Editar", self.edit_species))
        hb.addWidget(self._btn("🗑 Excluir", self.del_species))
        ll.addLayout(hb)
        ll.addWidget(QLabel("<b>BGCs / regiões</b>"))
        ll.addWidget(self.bgc_list, 2)
        # centro
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar por locus_tag ou produto…")
        self.search.textChanged.connect(self._fill_cards)
        self.cls = QComboBox()
        self.cls.currentIndexChanged.connect(self._fill_cards)
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setIconSize(QSize(214, 124))
        self.grid.setGridSize(QSize(226, 136))
        self.grid.setSpacing(2)
        self.grid.currentItemChanged.connect(lambda cur, _p: self._pick_gene(cur.data(Qt.UserRole) if cur else None))
        self.map = BGCMap(self.ctx.theme)
        self.empty = QLabel()
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        fl = QHBoxLayout()
        fl.addWidget(self.search, 1)
        fl.addWidget(QLabel("Classe:"))
        fl.addWidget(self.cls)
        self.only_core = QCheckBox("Só genes-âncora")
        self.only_core.setToolTip("PKS, NRPS, híbridas, NRPS-like e terpeno sintases")
        self.only_core.clicked.connect(lambda _c: (setattr(self, "_touched", True), self._fill_cards()))
        fl.addWidget(self.only_core)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addLayout(fl)
        cl.addWidget(self.empty)
        sp = QSplitter(Qt.Vertical)
        sp.addWidget(self.grid)
        sp.addWidget(self.map)
        sp.setSizes([420, 230])
        cl.addWidget(sp, 1)
        # direita
        self.detail = ArticleBrowser()
        self.detail.linkClicked.connect(self._detail_link)
        self.ev_list = QListWidget()
        self.ev_list.setMaximumHeight(170)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notas sobre este gene (hipóteses, resultados, próximos passos)…")
        self.notes.setFixedHeight(80)
        self.seq = QPlainTextEdit()
        self.seq.setReadOnly(True)
        self.seq.setFont(QFont("monospace", 8))
        self.seq.setFixedHeight(90)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.detail, 2)
        self.btn_model = self._btn("🔬 Modelo gênico refinado (éxons, cDNA sem íntrons, proteína, estatísticas)", self.open_model, "", True)
        rl.addWidget(self.btn_model)
        rl.addWidget(QLabel("<b>Checklist de evidências</b> (registrado por você)"))
        rl.addWidget(self.ev_list)
        er = QHBoxLayout()
        er.addWidget(self._btn("Registrar/editar", self.set_evidence, "Marca o estágio selecionado com nota e fonte", True))
        er.addWidget(self._btn("Remover", self.rm_evidence))
        rl.addLayout(er)
        rl.addWidget(self.notes)
        rl.addWidget(self._btn("💾 Salvar notas", self.save_notes))
        rl.addWidget(QLabel("<b>Proteína</b>"))
        rl.addWidget(self.seq)
        grid_btn = QHBoxLayout()
        for text, fn, tip in (("📋 FASTA", self.copy_fasta, "Copia a proteína em FASTA"),
                              ("💾 Exportar", self.export_fasta, "Salva FASTA (abre no Geneious)"),
                              ("🧭 BLASTp", self.blast, "Abre o BLASTp do NCBI com esta sequência"),
                              ("📂 Abrir origem", self.open_source, "Abre o arquivo de origem com o programa padrão (ex.: Geneious)"),
                              ("🗑", self.del_gene, "Excluir gene")):
            grid_btn.addWidget(self._btn(text, fn, tip))
        rl.addLayout(grid_btn)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(center)
        split.addWidget(right)
        split.setSizes([230, 700, 380])
        left.setMinimumWidth(210)
        right.setMinimumWidth(340)
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(split, 1)

    # ---------------------------------------------------------------- data
    def refresh(self) -> None:
        s = genoteca.summary(self.db)
        self.stats.setText(f"<span style='color:#9aa4b2'>{s['species']} espécie(s) · {s['genes']} gene(s) · {s['bgcs']} BGC(s) · "
                           f"{s['stages']} evidência(s) registrada(s)</span>")
        self.map.theme = self.ctx.theme
        self.sp_list.blockSignals(True)
        self.sp_list.clear()
        sp = genoteca.species_list(self.db)
        for r in sp:
            n = len(genoteca.genes_of_species(self.db, r["id"]))
            it = QListWidgetItem(f"🍄 {r['name']}" + (f" ({r['strain']})" if r["strain"] else "") + f"\n    {n} gene(s)")
            it.setData(Qt.UserRole, r["id"])
            self.sp_list.addItem(it)
        self.sp_list.blockSignals(False)
        ids = [r["id"] for r in sp]
        if self.sid not in ids:
            self.sid = ids[0] if ids else None
        if self.sid is not None:
            self.sp_list.setCurrentRow(ids.index(self.sid))
        self._fill_bgcs()
        self._fill_cards()

    def _pick_species(self, row: int) -> None:
        it = self.sp_list.item(row)
        self.sid = it.data(Qt.UserRole) if it else None
        self.bid = None
        self._fill_bgcs()
        self._fill_cards()

    def _fill_bgcs(self) -> None:
        self.bgc_list.blockSignals(True)
        self.bgc_list.clear()
        self.bgc_list.addItem("📚 Todos os genes da espécie")
        if self.sid:
            for b in genoteca.bgcs_of_species(self.db, self.sid):
                n = len(genoteca.genes_of_bgc(self.db, b["id"]))
                it = QListWidgetItem(f"🧩 {b['name'].split('.')[-1] if '.region' in b['name'] else b['name']}\n    {b['products'] or '—'} · {n} genes"
                                     + (" · borda" if b["contig_edge"] else ""))
                it.setData(Qt.UserRole, b["id"])
                self.bgc_list.addItem(it)
        self.bgc_list.blockSignals(False)
        ids = [None] + [self.bgc_list.item(i).data(Qt.UserRole) for i in range(1, self.bgc_list.count())]
        self.bgc_list.setCurrentRow(ids.index(self.bid) if self.bid in ids else 0)

    def _pick_bgc(self, row: int) -> None:
        it = self.bgc_list.item(row)
        self.bid = it.data(Qt.UserRole) if it and row > 0 else None
        self.gid = None
        self._fill_cards()

    def _rows(self):
        if self.bid:
            return genoteca.genes_of_bgc(self.db, self.bid)
        return genoteca.genes_of_species(self.db, self.sid) if self.sid else []

    def _bgc_meta_current(self) -> dict:
        if self.bid:
            b = genoteca.get_bgc(self.db, self.bid)
            return genoteca.bgc_meta(b) if b else {}
        return {}

    def _fill_cards(self) -> None:
        rows = self._rows()
        if not self._touched:
            self.only_core.setChecked(not self.bid and len(rows) > 150)
        if self.only_core.isChecked():
            rows = [r for r in rows if r["gene_class"] in CORE_CLASSES]
        classes = sorted({r["gene_class"] for r in rows})
        cur = self.cls.currentText()
        self.cls.blockSignals(True)
        self.cls.clear()
        self.cls.addItem("todas")
        self.cls.addItems(classes)
        self.cls.setCurrentIndex(max(0, self.cls.findText(cur)))
        self.cls.blockSignals(False)
        q, c = self.search.text().strip().lower(), self.cls.currentText()
        show = [r for r in rows if (c == "todas" or r["gene_class"] == c) and (not q or q in r["locus_tag"].lower() or q in (r["product"] or "").lower())]
        self.grid.clear()
        for n, r in enumerate(show, 1):
            it = QListWidgetItem(QIcon(render_gene_card(r, set(genoteca.evidence_of(self.db, r["id"])), self.ctx.theme, n)), "")
            it.setData(Qt.UserRole, r["id"])
            it.setSizeHint(QSize(226, 136))
            it.setToolTip(f"{r['locus_tag']} — {r['product']}")
            self.grid.addItem(it)
        if not self.db.con.execute("SELECT 1 FROM species").fetchone():
            self.empty.setText("<h2>Sua Genoteca está vazia</h2><p>Cadastre uma espécie, importe o resultado do antiSMASH (GenBank) "
                               "ou adicione o caso do projeto.</p>")
            self.empty.show()
            ex = self._btn("🎯 Adicionar o caso do projeto (Rickiella edulis / RICKED_008071)", self.seed, "", True)
            ex.setParent(self.empty)
            ex.move(20, 120)
            ex.show()
        else:
            self.empty.hide()
        self.map.show_genes(self._map_rows(show), self.gid, self._pick_gene, self._bgc_meta_current())
        if self.gid not in [r["id"] for r in show]:
            self.gid = None
            self._render_detail()

    def _map_rows(self, rows):
        return [r for r in rows if r["end"] > r["start"]]

    def _pick_gene(self, gid: int | None) -> None:
        self.gid = gid
        self._render_detail()
        rows = self._map_rows(self._rows())
        self.map.show_genes(rows, gid, self._pick_gene, self._bgc_meta_current())
        for i in range(self.grid.count()):
            if self.grid.item(i).data(Qt.UserRole) == gid and self.grid.currentRow() != i:
                self.grid.blockSignals(True)
                self.grid.setCurrentRow(i)
                self.grid.blockSignals(False)

    # ------------------------------------------------------------- detalhe
    def _render_detail(self) -> None:
        self.ev_list.clear()
        self.notes.clear()
        self.seq.clear()
        self.btn_model.setEnabled(False)
        self.detail.document().setDefaultStyleSheet(self.ctx.css())
        if not self.gid:
            if self.bid:
                self.detail.setHtml(self._bgc_html())
            else:
                self.detail.setHtml("<h3>Selecione uma carta</h3><p>Cada carta é um gene. Os 6 círculos mostram o estágio de evidência: "
                                    "0 predito → 1 transcrito → 2 proteína → 3 atividade → 4 produto → 5 identidade confirmada. "
                                    "Só você os preenche, com base nos seus dados.</p>")
            return
        g = genoteca.get_gene(self.db, self.gid)
        sp = genoteca.get_species(self.db, g["species_id"])
        bgc = genoteca.get_bgc(self.db, g["bgc_id"]) if g["bgc_id"] else None
        ev = genoteca.evidence_of(self.db, self.gid)
        meta = genoteca.gene_meta(g)
        model = genoteca.model_for_gene(g)
        self.btn_model.setEnabled(model is not None)
        col = CLASS_COLORS.get(g["gene_class"], "#8a95a5")
        pal = PALETTES[self.ctx.theme]
        doms = genoteca.domains_of(g)
        pks = [d for d in doms if d["kind"] == "pks"]
        chips = " – ".join(f"<span style='color:{DOMAIN_COLORS.get(d['short'], '#8a95a5')}'><b>{html.escape(display_name(d['name']))}</b></span>"
                           + (f"<span style='color:{pal['muted']}'>({d['start']}–{d['end']})</span>" if d["end"] > d["start"] else "") for d in pks) or "não anotados"
        other = [d for d in doms if d["kind"] != "pks"]
        top = max(ev) if ev else 0
        off = g["offset"] or 0
        if g["end"] > g["start"]:
            pos = (f"{html.escape(g['scaffold'] or g['contig'] or '')}:{(g['start'] + off + 1):,}–{(g['end'] + off):,} ({'+' if g['strand'] != -1 else '−'})").replace(",", ".")
            if off:
                pos += f"<br><span style='color:{pal['muted']}'>&nbsp;&nbsp;&nbsp;&nbsp;(local à região: {g['start'] + 1}–{g['end']})</span>"
        else:
            pos = "posição não informada"
        stats = ""
        if model is not None:
            st = model.stats()
            stats = (f"🧬 <b>{st['exons']}</b> éxons / <b>{st['introns']}</b> íntrons · CDS {st['cds_nt']:,} nt · <b>{st['aa']:,} aa</b>"
                     + (f" · {st['mw_kda']:.1f} kDa · pI {st['pi']:.2f}" if "mw_kda" in st else "")).replace(",", ".")
        elif g["protein"]:
            stats = f"📏 {len(g['protein'])} aa"
        mod = meta.get("module", {})
        modtxt = ""
        if mod:
            modtxt = (f"<br>⚙ Status do módulo antiSMASH ({mod.get('type', '').upper()}): " + ("iterativo, " if mod.get("iterative") else "") +
                      ("completo" if mod.get("complete") else "incompleto" if mod.get("incomplete") else "—") + " <span style='color:#9aa4b2'>(classificação original; não indica truncamento)</span>"
                      + (f" · {', '.join(mod['monomer_pairings'])}" if mod.get("monomer_pairings") else ""))
        funcs = meta.get("gene_functions", [])
        ftxt = ("<br>🏷 " + "; ".join(html.escape(f.split(") ", 1)[-1]) for f in funcs[:6])) if funcs else ""
        wiki = {"PKS": "fungal-pks", "PKS-NRPS": "pks-nrps-hybrids-and-domain-analysis", "NRPS": "pks-nrps-hybrids-and-domain-analysis"}.get(g["gene_class"])
        links = f" · <a href='codex://article/{wiki}'>📖 Estudar: {html.escape(self.ctx.lib.articles[wiki].title)}</a>" if wiki in self.ctx.lib.articles else ""
        self.detail.setHtml(
            f"<table width='100%'><tr><td bgcolor='{col}' width='7'></td><td bgcolor='{pal['panel2']}' style='padding:8px'>"
            f"<span style='color:{col}'><b>{CLASS_ICON.get(g['gene_class'], '')} {g['gene_class']}</b></span>"
            f"{' · <span style=color:#e0a458>✎ modelo editado</span>' if g['user_parts'] else ''}<br>"
            f"<span style='font-size:14pt'><b>{html.escape(g['locus_tag'])}</b></span><br>{html.escape(g['product'] or '')}</td></tr></table>"
            f"<p>🍄 <i>{html.escape(sp['name'])}</i>{' · ' + html.escape(sp['strain']) if sp['strain'] else ''}<br>"
            f"📍 {pos}<br>{stats}<br>"
            f"🧩 BGC: {html.escape(bgc['name'].split('.')[-1]) + ' (' + html.escape(bgc['products'] or '') + ')' if bgc else '—'}<br>"
            f"🔬 Domínios: {chips}" + (f" <span style='color:{pal['muted']}'>+ {len(other)} Pfam/TIGRFAM</span>" if other else "")
            + f"{modtxt}{ftxt}<br>"
            f"🔖 antiSMASH: {GENE_KINDS.get(g['kind'], g['kind'])}<br>"
            f"🏅 Evidência: <b>{genoteca.STAGES[top][1]}</b> ({len(ev)}/6){links}</p>")
        for s_, name, desc, c in genoteca.STAGES:
            r = ev.get(s_)
            it = QListWidgetItem((f"✔ {s_} · {name}" + (f" — {r['note'][:50]}" if r and r["note"] else "")) if r else f"○ {s_} · {name} — {desc}")
            it.setForeground(QColor(c if r else pal["muted"]))
            it.setData(Qt.UserRole, s_)
            self.ev_list.addItem(it)
        self.notes.setPlainText(g["notes"] or "")
        self.seq.setPlainText(g["protein"] or "")

    def _bgc_html(self) -> str:
        b = genoteca.get_bgc(self.db, self.bid)
        meta = genoteca.bgc_meta(b)
        pal = PALETTES[self.ctx.theme]
        genes = genoteca.genes_of_bgc(self.db, self.bid)
        off = meta.get("offset", 0) or 0
        by_cls: dict[str, int] = {}
        for g in genes:
            by_cls[g["gene_class"]] = by_cls.get(g["gene_class"], 0) + 1
        cls = " ".join(f"<span style='color:{CLASS_COLORS.get(k, '#8a95a5')}'><b>{k}: {v}</b></span>" for k, v in sorted(by_cls.items(), key=lambda kv: -kv[1]))
        cores = "; ".join(f"{c[0] + off:,}–{c[1] + off:,} ({'+' if c[2] != -1 else '−'}, {c[3]})".replace(",", ".") for c in meta.get("cores", [])) or "—"
        core_genes = [g for g in genes if g["gene_class"] in CORE_CLASSES]
        rows = "".join(f"<li><b>{html.escape(g['locus_tag'])}</b> — {g['gene_class']}, {len(g['protein'] or '')} aa</li>" for g in core_genes) or "<li>—</li>"
        return (f"<table width='100%'><tr><td bgcolor='#d9534f' width='7'></td><td bgcolor='{pal['panel2']}' style='padding:8px'>"
                f"<b style='color:#d9534f'>🧩 Região biossintética</b><br><span style='font-size:14pt'><b>{html.escape(b['name'])}</b></span><br>"
                f"{html.escape(b['products'] or '')}</td></tr></table>"
                f"<p>📍 {html.escape(meta.get('scaffold', b['contig'] or ''))}:{(b['start'] + off + 1):,}–{(b['end'] + off):,} · {(b['end'] - b['start']) / 1000:.1f} kb".replace(",", ".")
                + f"<br>🧬 {len(genes)} genes: {cls}<br>🎯 Núcleo(s): {cores}<br>"
                f"🚧 Borda de contig: {'sim' if b['contig_edge'] else 'não'} · categoria: {html.escape(meta.get('category', '') or '—')}"
                f" · candidato: {html.escape(meta.get('kind', '') or '—')}<br>"
                f"📜 Regra de detecção: <span style='color:{pal['muted']}'>{html.escape(meta.get('rules', '') or '—')}</span><br>"
                + (f"🧪 SMILES do esqueleto previsto pelo antiSMASH (apenas predição): <code>{html.escape(meta['smiles'])}</code><br>" if meta.get("smiles") else "")
                + f"🛠 antiSMASH {html.escape(meta.get('antismash_version', '') or '—')} · anotação {html.escape(meta.get('annotator', '') or '—')}</p>"
                f"<p><b>Genes-âncora desta região:</b></p><ul>{rows}</ul>"
                "<p class='muted'>Região e limites são predições do antiSMASH. Clique numa seta do mapa ou numa carta para ver o gene.</p>")

    def open_model(self) -> None:
        if not self.gid:
            return
        g = genoteca.get_gene(self.db, self.gid)
        if genoteca.model_for_gene(g) is None:
            QMessageBox.information(self, "Modelo gênico", "Este gene não tem sequência genômica e éxons importados (importe o GenBank).")
            return
        self._model_dlg = GeneModelDialog(self.ctx, g, self, on_saved=self._after_change)
        self._model_dlg.show()

    def _detail_link(self, url: QUrl) -> None:
        s = url.toString()
        if s.startswith("codex://article/"):
            self.ctx.openArticle.emit(s.rsplit("/", 1)[1])

    def _stage(self) -> int | None:
        it = self.ev_list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def set_evidence(self) -> None:
        s = self._stage()
        if self.gid is None or s is None:
            QMessageBox.information(self, "Evidência", "Selecione um gene e um estágio da lista.")
            return
        if s == 0:
            QMessageBox.information(self, "Evidência", "O estágio 0 (predito) é registrado na importação.")
            return
        cur = genoteca.evidence_of(self.db, self.gid).get(s)
        txt, ok = QInputDialog.getMultiLineText(self, f"Estágio {s} · {genoteca.STAGES[s][1]}",
                                                f"{genoteca.STAGES[s][2]}\nDescreva a evidência (método, condição, data, arquivo/caderno):",
                                                cur["note"] if cur else "")
        if ok:
            genoteca.record_evidence(self.db, self.gid, s, txt.strip(), "usuário")
            self._after_change()

    def rm_evidence(self) -> None:
        s = self._stage()
        if self.gid and s:
            genoteca.remove_evidence(self.db, self.gid, s)
            self._after_change()

    def save_notes(self) -> None:
        if self.gid:
            genoteca.update_gene_notes(self.db, self.gid, self.notes.toPlainText())

    def _after_change(self) -> None:
        keep = self.gid
        self._fill_cards()
        self._pick_gene(keep)
        self.ctx.dataChanged.emit()

    def _fasta(self) -> str | None:
        if not self.gid:
            return None
        g = genoteca.get_gene(self.db, self.gid)
        sp = genoteca.get_species(self.db, g["species_id"])
        if not g["protein"]:
            QMessageBox.information(self, "Proteína", "Este gene não tem sequência de proteína registrada.")
            return None
        return antismash.to_fasta(g["locus_tag"], f"{g['product']} [{sp['name']}]", g["protein"])

    def copy_fasta(self) -> None:
        f = self._fasta()
        if f:
            QApplication.clipboard().setText(f)

    def export_fasta(self) -> None:
        f = self._fasta()
        if f:
            tag = genoteca.get_gene(self.db, self.gid)["locus_tag"]
            p, _ = QFileDialog.getSaveFileName(self, "Exportar FASTA", f"{tag}.fasta", "FASTA (*.fasta *.fa)")
            if p:
                Path(p).write_text(f, encoding="utf-8")

    def blast(self) -> None:
        if not self.gid:
            return
        g = genoteca.get_gene(self.db, self.gid)
        if not g["protein"]:
            QMessageBox.information(self, "BLASTp", "Sem sequência de proteína para consultar.")
            return
        QDesktopServices.openUrl(QUrl("https://blast.ncbi.nlm.nih.gov/Blast.cgi?PROGRAM=blastp&PAGE_TYPE=BlastSearch&QUERY=" + g["protein"]))

    def open_source(self) -> None:
        if not self.gid:
            return
        g = genoteca.get_gene(self.db, self.gid)
        f = None
        if g["bgc_id"]:
            f = genoteca.get_bgc(self.db, g["bgc_id"])["source_file"]
        f = f or genoteca.get_species(self.db, g["species_id"])["genome_file"]
        if f and Path(f).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(f))
        else:
            QMessageBox.information(self, "Arquivo de origem", "Nenhum arquivo de origem existente associado a este gene. "
                                    "Informe o arquivo do genoma na ficha da espécie.")

    def del_gene(self) -> None:
        if self.gid and QMessageBox.question(self, "Excluir gene", "Excluir este gene e suas evidências?") == QMessageBox.Yes:
            genoteca.delete_gene(self.db, self.gid)
            self.gid = None
            self.refresh()
            self.ctx.dataChanged.emit()

    # --------------------------------------------------------------- ações
    def new_species(self, prefill: dict | None = None) -> int | None:
        d = SpeciesDialog(self, prefill)
        if d.exec() == QDialog.Accepted:
            self.sid = genoteca.add_species(self.db, **{k: v for k, v in d.values().items() if k != "genome_accession"} | {"accession": d.values()["genome_accession"]})
            self.refresh()
            self.ctx.dataChanged.emit()
            return self.sid
        return None

    def edit_species(self) -> None:
        if not self.sid:
            return
        d = SpeciesDialog(self, dict(genoteca.get_species(self.db, self.sid)))
        if d.exec() == QDialog.Accepted:
            genoteca.update_species(self.db, self.sid, **d.values())
            self.refresh()

    def del_species(self) -> None:
        if self.sid and QMessageBox.question(self, "Excluir espécie", "Excluir a espécie com TODOS os seus genes, BGCs e evidências?") == QMessageBox.Yes:
            genoteca.delete_species(self.db, self.sid)
            self.sid = self.bid = self.gid = None
            self.refresh()
            self.ctx.dataChanged.emit()

    def _choose_species(self, stem: str = "") -> int | None:
        sp = genoteca.species_list(self.db)
        if not sp:
            return self.new_species({"name": stem.replace("_", " ")} if stem else None)
        names = [r["name"] for r in sp] + ["(nova espécie…)"]
        cur = next((i for i, r in enumerate(sp) if r["id"] == self.sid), 0)
        pick, ok = QInputDialog.getItem(self, "Espécie", "Associar a qual espécie?", names, cur, False)
        if not ok:
            return None
        return self.new_species() if pick == names[-1] else sp[names.index(pick)]["id"]

    def _run_bg(self, fn, then, text: str = "Lendo o arquivo… (genomas grandes podem levar alguns minutos)") -> None:
        dlg = QProgressDialog(text, None, 0, 0, self)
        dlg.setWindowTitle("Importando")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.show()
        w = Worker(fn)
        w.prog.connect(lambda s: dlg.setLabelText(f"{text}\n{s}"))

        def ok(res) -> None:
            dlg.close()
            try:
                then(res)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Não foi possível importar", str(e))

        def bad(msg: str) -> None:
            dlg.close()
            QMessageBox.critical(self, "Não foi possível ler o arquivo", f"{msg}\n\nConfirme se é um GenBank válido (antiSMASH, Funannotate, NCBI ou Geneious).")
        w.done.connect(ok)
        w.failed.connect(bad)
        self._worker = w
        w.start()

    def _species_for(self, info, path: str) -> int | None:
        sid = genoteca.ensure_species_from_info(self.db, info, path)
        return sid if sid is not None else self._choose_species(Path(path).stem)

    def import_file(self, path: str | None = None) -> None:
        p = path or QFileDialog.getOpenFileName(self, "Importar", "", "GenBank/FASTA (*.gbk *.gb *.gbff *.gbf *.gb.gz *.fa *.fasta *.faa);;Todos (*)")[0]
        if not p:
            return
        if Path(p).suffix.lower() in (".fa", ".fasta", ".faa"):
            try:
                sid = self._choose_species(Path(p).stem)
                if sid is None:
                    return
                recs = antismash.read_fasta_proteins(p)
                for tag, seq in recs:
                    gid = genoteca.add_manual_gene(self.db, sid, tag, "proteína importada (FASTA)")
                    self.db.con.execute("UPDATE genes SET protein=? WHERE id=?", (seq, gid))
                self.db.con.commit()
                self.sid = sid
                self.refresh()
                self.ctx.dataChanged.emit()
                QMessageBox.information(self, "Importação concluída", f"{len(recs)} proteína(s) importada(s) do FASTA.")
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Não foi possível importar", str(e))
            return
        self._run_bg(lambda prog: antismash.parse_genbank(p, prog), lambda regions: self._after_regions(p, regions))

    def _after_regions(self, p: str, regions) -> None:
        if regions:
            sid = self._species_for(regions[0].info, p)
            if sid is None:
                return
            n_genes = 0
            for b in regions:
                genoteca.add_bgc(self.db, sid, b, "antiSMASH", p)
                n_genes += len(b.genes)
            self.sid, self.bid, self.gid = sid, None, None
            self.refresh()
            self.ctx.dataChanged.emit()
            cls: dict[str, int] = {}
            for b in regions:
                for g in b.genes:
                    if g.gene_class in CORE_CLASSES:
                        cls[g.gene_class] = cls.get(g.gene_class, 0) + 1
            QMessageBox.information(self, "Importação concluída",
                                    f"{len(regions)} região(ões) (BGC) e {n_genes} gene(s) importados.\nGenes-âncora: "
                                    + (", ".join(f"{k}: {v}" for k, v in cls.items()) or "nenhum")
                                    + "\n\nUse a aba «Explorador do genoma» para classificar e ordenar.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("GenBank sem regiões do antiSMASH")
        box.setText("Este GenBank não contém regiões do antiSMASH.\n\n• Triagem por anotação: localiza PKS/NRPS/híbridas/terpeno sintases pelos IDs Pfam "
                    "(db_xref do Funannotate/InterPro) ou pelo texto do produto. É uma HEURÍSTICA; o antiSMASH é a referência.\n"
                    "• Gene específico: importa um gene (e vizinhos) por locus_tag.")
        b1 = box.addButton("Triagem por anotação (genoma inteiro)", QMessageBox.AcceptRole)
        b2 = box.addButton("Importar um gene (locus_tag)", QMessageBox.ActionRole)
        box.addButton("Cancelar", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b1:
            self._run_bg(lambda prog: antismash.screen_genome(p, prog), lambda res: self._after_screen(p, res),
                         "Triando o genoma por anotação Pfam/texto…")
        elif box.clickedButton() is b2:
            tag, ok = QInputDialog.getText(self, "Gene específico", "locus_tag (ex.: RICKED_008071):")
            if ok and tag.strip():
                self._add_gene_from_file(p, tag.strip())

    def _after_screen(self, p: str, res) -> None:
        genes, info, n_cds = res
        if not genes:
            QMessageBox.information(self, "Triagem", f"Nenhum gene candidato encontrado entre {n_cds} CDS.\nO arquivo pode não ter anotação Pfam/produto "
                                    "informativos. Rode o antiSMASH (botões ▶/🌐) e importe o resultado.")
            return
        sid = self._species_for(info, p)
        if sid is None:
            return
        for g in genes:
            genoteca.add_gene(self.db, sid, g, None, commit=False)
        self.db.con.commit()
        self.sid, self.bid, self.gid = sid, None, None
        self.refresh()
        self.ctx.dataChanged.emit()
        cls: dict[str, int] = {}
        for g in genes:
            cls[g.gene_class] = cls.get(g.gene_class, 0) + 1
        QMessageBox.information(self, "Triagem concluída", f"{len(genes)} gene(s) candidato(s) entre {n_cds} CDS (heurística Pfam/texto):\n"
                                + ", ".join(f"{k}: {v}" for k, v in sorted(cls.items(), key=lambda kv: -kv[1]))
                                + "\n\nOs domínios aqui são inferidos dos IDs Pfam, sem coordenadas. Para domínios posicionados e regiões, use o antiSMASH.")

    def _add_gene_from_file(self, path: str, tag: str) -> None:
        self._run_bg(lambda prog: antismash.find_gene(path, tag), lambda res: self._after_gene(path, tag, res), "Procurando o gene…")

    def _after_gene(self, path: str, tag: str, res) -> None:
        b, found = res
        if not b:
            QMessageBox.warning(self, "Não encontrado", f"'{tag}' não está em {Path(path).name}.")
            return
        sid = self._species_for(b.info, path)
        if sid is None:
            return
        bid = genoteca.add_bgc(self.db, sid, b, "GenBank", path)
        self.sid, self.bid = sid, bid
        self.refresh()
        row = next((r for r in genoteca.genes_of_bgc(self.db, bid) if r["locus_tag"] == found), None)
        if row:
            self._pick_gene(row["id"])
        self.ctx.dataChanged.emit()

    def find_in_genome(self) -> None:
        sid = self.sid
        sp = genoteca.get_species(self.db, sid) if sid else None
        f = sp["genome_file"] if sp and sp["genome_file"] and Path(sp["genome_file"]).exists() else QFileDialog.getOpenFileName(
            self, "GenBank do genoma", "", "GenBank (*.gbk *.gb *.gbff *.gbf)")[0]
        if not f:
            return
        tag, ok = QInputDialog.getText(self, "Gene no genoma", "locus_tag (ex.: RICKED_008071):")
        if ok and tag.strip():
            self._add_gene_from_file(f, tag.strip())

    def manual_gene(self) -> None:
        sid = self.sid or self._choose_species()
        if not sid:
            return
        tag, ok = QInputDialog.getText(self, "Novo gene", "locus_tag / identificador:")
        if not ok or not tag.strip():
            return
        prod, _ = QInputDialog.getText(self, "Novo gene", "Produto/descrição (opcional):")
        cls, ok = QInputDialog.getItem(self, "Novo gene", "Classe:", list(CLASS_COLORS), 0, False)
        if ok:
            self.gid = genoteca.add_manual_gene(self.db, sid, tag.strip(), prod, cls)
            self.sid = sid
            self.refresh()
            self.ctx.dataChanged.emit()

    def seed(self) -> None:
        self.gid = genoteca.seed_project_case(self.db)
        self.refresh()
        self.ctx.dataChanged.emit()

    def run_antismash(self) -> None:
        exe = antismash.antismash_path()
        if not exe:
            QMessageBox.information(self, "antiSMASH não encontrado",
                                    "O comando `antismash` não está instalado neste computador.\n\nOpções:\n"
                                    "1) Use o site (botão «antiSMASH web»), baixe o resultado e importe o GenBank da região.\n"
                                    "2) Instale localmente (ver docs/ANTISMASH.md) e tente de novo.")
            return
        f, _ = QFileDialog.getOpenFileName(self, "Entrada para o antiSMASH", "", "GenBank/FASTA (*.gbk *.gb *.gbff *.fa *.fasta *.fna)")
        if not f:
            return
        out = data_dir() / "antismash_runs" / Path(f).stem
        out.mkdir(parents=True, exist_ok=True)
        cmd = antismash.build_command(f, str(out), "fungi", Path(f).suffix.lower() in (".fa", ".fasta", ".fna"))
        log = QPlainTextEdit()
        log.setWindowTitle("antiSMASH — execução local (pode levar de minutos a horas)")
        log.resize(800, 420)
        log.setReadOnly(True)
        log.show()
        self._log = log
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(lambda: log.appendPlainText(bytes(self.proc.readAllStandardOutput()).decode(errors="replace")))
        self.proc.finished.connect(lambda code, _s: self._antismash_done(code, out, f))
        log.appendPlainText("$ " + " ".join(cmd))
        self.proc.start(cmd[0], cmd[1:])

    def _antismash_done(self, code: int, out: Path, src: str) -> None:
        self._log.appendPlainText(f"\nTerminado com código {code}.")
        gbks = sorted(out.glob("*region*.gbk"))
        if code == 0 and gbks and QMessageBox.question(self, "antiSMASH concluído", f"{len(gbks)} região(ões) encontrada(s). Importar para a Genoteca?") == QMessageBox.Yes:
            sid = self._choose_species(Path(src).stem)
            if sid:
                for g in gbks:
                    for b in antismash.parse_genbank(g):
                        genoteca.add_bgc(self.db, sid, b, "antiSMASH (local)", str(g))
                self.sid = sid
                self.refresh()
                self.ctx.dataChanged.emit()


def load_lab_scenarios() -> list[dict]:
    out: dict[str, dict] = {}
    for d in (bundled_content_dir() / "lab", user_content_dir() / "lab"):
        if d.exists():
            for f in sorted(d.glob("*.yaml")):
                try:
                    data = yaml.safe_load(f.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and data.get("id"):
                        out[data["id"]] = data
                except Exception:  # noqa: BLE001
                    continue
    return list(out.values())


class ScenariosView(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.scenarios = load_lab_scenarios()
        self.listw = QListWidget()
        self.listw.setMaximumWidth(300)
        for s in self.scenarios:
            self.listw.addItem("🧪 " + s["title"].split("(")[0].strip())
        self.listw.currentRowChanged.connect(self.show_scenario)
        self.ctxview = ArticleBrowser()
        self.ctxview.linkClicked.connect(lambda u: ctx.openArticle.emit(u.toString().rsplit("/", 1)[1]) if u.toString().startswith("codex://article/") else None)
        self.ctxview.setMaximumHeight(340)
        self.prompts = QWidget()
        self.pl = QVBoxLayout(self.prompts)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.prompts)
        right = QVBoxLayout()
        right.addWidget(self.ctxview)
        right.addWidget(sc, 1)
        lay = QHBoxLayout(self)
        lay.addWidget(self.listw)
        lay.addLayout(right, 1)
        ctx.themeChanged.connect(lambda _t: self.show_scenario(self.listw.currentRow()))
        if self.scenarios:
            self.listw.setCurrentRow(0)
        else:
            self.ctxview.setHtml("<p>Nenhum cenário encontrado em content/lab/.</p>")

    def show_scenario(self, row: int) -> None:
        if not (0 <= row < len(self.scenarios)):
            return
        s, esc = self.scenarios[row], html.escape
        pal = PALETTES[self.ctx.theme]
        parts = [f"<h2>{esc(s['title'])}</h2>",
                 f"<table width='100%'><tr><td bgcolor='#d9a441' width='6'></td><td bgcolor='{pal['panel2']}' style='padding:6px'>"
                 "<b style='color:#d9a441'>DADOS SIMULADOS — didáticos.</b> Não representam resultados publicados nem experimentos reais.</td></tr></table>",
                 f"<p>{esc(s.get('context', ''))}</p>"]
        for t in s.get("tables", []) or []:
            parts.append(f"<p><b>{esc(t.get('title', ''))}</b></p><table border='1' cellspacing='0' cellpadding='5'><tr>"
                         + "".join(f"<th>{esc(str(h))}</th>" for h in t["headers"]) + "</tr>"
                         + "".join("<tr>" + "".join(f"<td>{esc(str(c))}</td>" for c in r) + "</tr>" for r in t["rows"]) + "</table>")
        rel = [r for r in s.get("related", []) or [] if r in self.ctx.lib.articles]
        if rel:
            parts.append("<p>Conceitos para revisar: " + ", ".join(f"<a href='codex://article/{r}'>{esc(self.ctx.lib.articles[r].title)}</a>" for r in rel) + "</p>")
        self.ctxview.document().setDefaultStyleSheet(self.ctx.css())
        self.ctxview.setHtml("".join(parts))
        while self.pl.count():
            w = self.pl.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, p in enumerate(s.get("prompts", []) or [], 1):
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            q = QLabel(f"<b>Pergunta {i}.</b> {esc(p['q'])}")
            q.setWordWrap(True)
            ed = QTextEdit()
            ed.setPlaceholderText("1) Escreva sua hipótese/raciocínio antes de ver a resposta comentada…")
            ed.setMaximumHeight(90)
            ans = ArticleBrowser()
            ans.hide()
            ans.document().setDefaultStyleSheet(self.ctx.css())
            ans.setHtml("<p>" + esc(p.get("commented", "")).replace("\n", "<br>") + "</p>")
            ans.setMinimumHeight(130)
            btn = QPushButton("2) Mostrar resposta comentada")
            btn.clicked.connect(lambda _=False, a=ans, b=btn: (a.show(), b.hide()))
            for w in (q, ed, btn, ans):
                cl.addWidget(w)
            self.pl.addWidget(card)
        self.pl.addStretch(1)


class LabView(QTabWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.geno = GenotecaView(ctx)
        self.explorer = GenomeExplorer(ctx, self.open_gene)
        self.addTab(self.geno, "🧬 Genoteca")
        self.addTab(self.explorer, "🗺 Explorador do genoma")
        from .analysis_view import AnalysisView
        self.analysis = AnalysisView(ctx, self.open_gene)
        self.addTab(self.analysis, "🧮 Análise de PKS")
        self.addTab(ScenariosView(ctx), "🧪 Cenários de raciocínio")
        ctx.dataChanged.connect(self.geno.refresh)

    def open_gene(self, gid: int) -> None:
        g = genoteca.get_gene(self.ctx.db, gid)
        if not g:
            return
        self.setCurrentIndex(0)
        self.geno.sid, self.geno.bid = g["species_id"], g["bgc_id"]
        self.geno.refresh()
        self.geno.bid = g["bgc_id"]
        self.geno._fill_bgcs()
        self.geno._fill_cards()
        self.geno._pick_gene(gid)
