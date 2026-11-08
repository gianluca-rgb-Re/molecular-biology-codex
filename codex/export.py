"""Exportação de resultados: CSV, XLSX (várias planilhas) com colunas selecionáveis."""
from __future__ import annotations
import csv
import datetime as dt
from pathlib import Path

from . import __version__
from .analysis import Rec, SOURCES, class_distribution, domain_frequency, group_architectures, matrix, source_label

COLUMNS: list[tuple[str, str, object]] = [
    ("locus", "Gene", lambda r, s: r.locus),
    ("species", "Espécie", lambda r, s: r.species),
    ("gene_class", "Classe da proteína (inferida dos domínios)", lambda r, s: r.gene_class),
    ("bgc_types", "Tipo de BGC (antiSMASH)", lambda r, s: ", ".join(r.bgc_types) or "—"),
    ("bgc", "Região (BGC)", lambda r, s: r.bgc or "—"),
    ("scaffold", "Scaffold", lambda r, s: r.scaffold),
    ("start", "Início (scaffold)", lambda r, s: r.start),
    ("end", "Fim (scaffold)", lambda r, s: r.end),
    ("strand", "Fita", lambda r, s: r.strand),
    ("aa", "Aminoácidos", lambda r, s: r.aa),
    ("exons", "Éxons", lambda r, s: r.exons),
    ("introns", "Íntrons", lambda r, s: r.introns),
    ("arch", "Arquitetura de domínios (fonte selecionada)", lambda r, s: r.arch_str(s)),
    ("n_domains", "Nº de domínios (fonte selecionada)", lambda r, s: len(r.arch(s))),
    ("pfam", "Domínios Pfam", lambda r, s: "–".join(r.arch("pfam")) or "—"),
    ("tigr", "Domínios TIGRFAM", lambda r, s: "–".join(r.arch("tigr")) or "—"),
    ("module", "Status do módulo antiSMASH", lambda r, s: r.module_status),
    ("gene_kind", "gene_kind (antiSMASH)", lambda r, s: r.gene_kind or "—"),
    ("product", "Produto (anotação do arquivo)", lambda r, s: r.product),
    ("source", "Fonte da anotação", lambda r, s: r.source),
    ("cds", "Verificações da CDS (critérios do app)", lambda r, s: ("OK" if not r.cds_alerts else "; ".join(r.cds_alerts)) if r.cds_checked else "não verificável"),
    ("evidence", "Estágio de evidência (registrado por você)", lambda r, s: r.evidence),
    ("edited", "Modelo gênico editado pelo usuário", lambda r, s: "sim" if r.edited else "não"),
]
COLUMN_KEYS = [c[0] for c in COLUMNS]
COLUMN_LABELS = {c[0]: c[1] for c in COLUMNS}
DEFAULT_KEYS = ["locus", "gene_class", "bgc_types", "scaffold", "start", "end", "strand", "aa", "exons", "arch", "module", "source"]


def table(recs: list[Rec], keys: list[str] | None = None, source: str = "antismash") -> tuple[list[str], list[list]]:
    keys = [k for k in (keys or DEFAULT_KEYS) if k in COLUMN_LABELS]
    getters = {c[0]: c[2] for c in COLUMNS}
    return [COLUMN_LABELS[k] for k in keys], [[getters[k](r, source) for k in keys] for r in recs]


def write_csv(path: str | Path, recs: list[Rec], keys: list[str] | None = None, source: str = "antismash") -> int:
    head, rows = table(recs, keys, source)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:      # BOM: o Excel abre acentos corretamente
        w = csv.writer(fh, delimiter=";")
        w.writerow(head)
        w.writerows(rows)
    return len(rows)


def _style_sheet(ws, header_row: int = 1) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    for c in ws[header_row]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    if ws.max_row > header_row:
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(ws.max_column)}{ws.max_row}"
    for i, col in enumerate(ws.columns, 1):
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[get_column_letter(i)].width = min(60, max(10, width + 2))


def csv_bytes(recs: list[Rec], keys: list[str] | None = None, source: str = "antismash") -> bytes:
    import io
    head, rows = table(recs, keys, source)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(head)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def write_xlsx(path, recs: list[Rec], keys: list[str] | None = None, source: str = "antismash", meta: dict | None = None) -> int:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Genes"
    head, rows = table(recs, keys, source)
    ws.append(head)
    for r in rows:
        ws.append(r)
    _style_sheet(ws)
    cols, mrows = matrix(recs, source)
    wm = wb.create_sheet("Matriz de domínios")
    wm.append(["Gene", "Classe da proteína", "Tipo de BGC"] + cols)
    for r, counts in mrows:
        wm.append([r.locus, r.gene_class, ", ".join(r.bgc_types) or "—"] + [c if c else None for c in counts])
    _style_sheet(wm)
    wf = wb.create_sheet("Frequência de domínios")
    wf.append(["Domínio", "Proteínas com o domínio", "Frequência relativa", "Cópias totais", "Categoria"])
    for f in domain_frequency(recs, source):
        wf.append([f["domain"], f["proteins"], round(f["freq"], 4), f["copies"], f["category"]])
    _style_sheet(wf)
    wa = wb.create_sheet("Arquiteturas")
    wa.append(["Arquitetura (ordem preservada)", "Nº de proteínas", "Genes", "Observações (critérios do app)"])
    for g in group_architectures(recs, source):
        wa.append([g["arch_str"], g["n"], ", ".join(g["loci"]), "; ".join(g["notes"])])
    _style_sheet(wa)
    wc = wb.create_sheet("Classes")
    wc.append(["Classe da proteína (inferida dos domínios)", "Nº de proteínas"])
    for k, v in class_distribution(recs):
        wc.append([k, v])
    wc.append([])
    wc.append(["Tipo de BGC (antiSMASH)", "Nº de genes-âncora"])
    for k, v in class_distribution(recs, "bgc"):
        wc.append([k, v])
    _style_sheet(wc)
    wn = wb.create_sheet("Leia-me")
    m = meta or {}
    for line in [("Molecular Biology Codex", f"v{__version__}"), ("Gerado em", dt.datetime.now().strftime("%Y-%m-%d %H:%M")),
                 ("Fonte dos domínios nas planilhas", SOURCES.get(source, source)), ("Genes exportados", len(recs)),
                 ("Espécie(s)", m.get("species", "")), ("Arquivo(s) de origem", m.get("files", "")), ("", ""),
                 ("Dados originais", "Identificadores de domínios, coordenadas, tipo de BGC, gene_kind e status do módulo vêm do arquivo (antiSMASH/Funannotate)."),
                 ("Inferências do app", "Classe da proteína (a partir dos domínios), verificações da CDS, agrupamento de arquiteturas e observações."),
                 ("Status do módulo antiSMASH", "Classificação original do antiSMASH; NÃO indica por si só truncamento do gene ou da proteína."),
                 ("Domínios", "Nomes do antiSMASH sem o prefixo «PKS_» na exibição (KS = PKS_KS no arquivo); demais nomes originais. antiSMASH, Pfam e TIGRFAM são fontes diferentes e não foram misturados, salvo pedido.")]:
        wn.append(list(line))
    wn.column_dimensions["A"].width = 38
    wn.column_dimensions["B"].width = 110
    wb.save(path if hasattr(path, "write") else str(path))
    return len(rows)
