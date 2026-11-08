"""Relatório PDF acadêmico (Qt: QTextDocument → QPdfWriter), com tabelas, gráficos e diagramas de proteínas."""
from __future__ import annotations
import datetime as dt
import html
from collections import Counter
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSizeF, QUrl
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument

from . import __version__, analysis, genoteca
from .analysis import Rec, SOURCES, source_label
from .viz import render_architectures_image, render_bar_chart

CSS = """
body { font-family:'DejaVu Sans'; font-size:9pt; color:#1c2430; }
h1 { font-size:20pt; color:#1f3a5f; margin-bottom:2px; }
h2 { font-size:13pt; color:#1f3a5f; border-bottom:1px solid #1f3a5f; margin-top:16px; }
h3 { font-size:10.5pt; color:#2c5282; }
th { background-color:#1f3a5f; color:#ffffff; text-align:left; }
.muted { color:#5b6675; font-size:8pt; }
.warn { color:#9c4a00; }
"""


def _table(head: list[str], rows: list[list], widths: list[int] | None = None) -> str:
    h = "".join(f"<th>{html.escape(str(c))}</th>" for c in head)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table border='1' cellspacing='0' cellpadding='3' width='100%'><tr>{h}</tr>{body}</table>"


def build_html(db, recs: list[Rec], species_id: int | None, source: str, doc: QTextDocument, title: str = "") -> str:
    sp = genoteca.get_species(db, species_id) if species_id else None
    audit = analysis.audit(db, species_id)
    bgcs = genoteca.bgcs_of_species(db, species_id) if species_id else []
    files = sorted({b["source_file"] for b in bgcs if b["source_file"]} | ({sp["genome_file"]} if sp and sp["genome_file"] else set()))
    versions = sorted({(genoteca.bgc_meta(b).get("antismash_version") or "") for b in bgcs} - {""})
    annot = sorted({(genoteca.bgc_meta(b).get("annotator") or "") for b in bgcs} - {""})
    n = len(recs)
    out = [f"<h1>{html.escape(title or 'Relatório de análise de genes biossintéticos')}</h1>",
           f"<p class='muted'>Molecular Biology Codex v{__version__} · gerado em {dt.datetime.now():%d/%m/%Y %H:%M} · domínios: {html.escape(SOURCES.get(source, source))} · nomes do antiSMASH sem o prefixo «PKS_»</p>"]
    out.append("<h2>1. Identificação do genoma</h2>")
    ident = [["Espécie", (sp["name"] if sp else ", ".join(sorted({r.species for r in recs})) or "—")],
             ["Linhagem/isolado", (sp["strain"] if sp and sp["strain"] else "—")], ["Acesso/scaffold", (sp["genome_accession"] if sp and sp["genome_accession"] else "—")],
             ["Taxonomia", (sp["taxonomy"] if sp and sp["taxonomy"] else "—")], ["Arquivo(s) de origem", "; ".join(Path(f).name for f in files) or "—"],
             ["Versão do antiSMASH", ", ".join(versions) or "—"], ["Anotação estrutural", ", ".join(annot) or "—"],
             ["Regiões (BGCs) importadas", len(bgcs)], ["Genes importados / genes-âncora", f"{audit['total_genes']} / {audit['core']}"]]
    out.append(_table(["Campo", "Valor"], ident))
    out.append("<p class='muted'>Dados importados do arquivo fornecido; o relatório cobre apenas os genes/regiões importados (não necessariamente o genoma completo).</p>")
    out.append("<h2>2. Resumo dos genes identificados</h2>")
    out.append(f"<p>{n} gene(s) no recorte analisado.</p>")
    out.append(_table(["Gene", "Classe (domínios)", "Tipo de BGC", "Scaffold", "Início–Fim", "Fita", "aa", "Éxons", "Status do módulo antiSMASH", "Fonte"],
                      [[r.locus, r.gene_class, ",".join(r.bgc_types) or "—", r.scaffold, f"{r.start:,}–{r.end:,}".replace(",", "."), r.strand, r.aa, r.exons,
                        r.module_status, r.source] for r in recs]))
    out.append("<h2>3. Distribuição das classes</h2>")
    dist, bdist = analysis.class_distribution(recs), analysis.class_distribution(recs, "bgc")
    doc.addResource(QTextDocument.ImageResource, QUrl("chart_class"), render_bar_chart(dist, "Classe da proteína (inferida dos domínios)", 1000, " gene(s)", "#4a90d9", n))
    doc.addResource(QTextDocument.ImageResource, QUrl("chart_bgc"), render_bar_chart(bdist, "Tipo de BGC (antiSMASH) dos genes-âncora", 1000, " gene(s)", "#d9534f", n))
    out.append("<p><img src='chart_class' width='1000'></p><p><img src='chart_bgc' width='1000'></p>")
    out.append("<p class='muted'>Classe da proteína e tipo de BGC são informações distintas: um gene num BGC híbrido não é automaticamente uma proteína híbrida.</p>")
    out.append("<h2>4. Frequência dos domínios</h2>")
    freq = analysis.domain_frequency(recs, source)
    doc.addResource(QTextDocument.ImageResource, QUrl("chart_dom"), render_bar_chart([(f["domain"], f["proteins"]) for f in freq], "Proteínas com cada domínio ", 1000, "", "auto", n))
    out.append("<p><img src='chart_dom' width='1000'></p>")
    out.append(_table(["Domínio", "Proteínas", "Frequência", "Cópias", "Categoria"], [[f["domain"], f["proteins"], f"{100 * f['freq']:.0f}%", f["copies"], f["category"]] for f in freq]))
    excl = analysis.exclusive_domains(recs, source)
    if excl:
        out.append("<p><b>Domínios exclusivos:</b> " + "; ".join(f"{html.escape(k)} ({html.escape(', '.join(v))})" for k, v in excl.items()) + "</p>")
    out.append("<h2>5. Comparação de arquiteturas</h2>")
    groups = analysis.group_architectures(recs, source)
    out.append(_table(["Arquitetura (ordem preservada)", "Nº", "Genes", "Observações (critérios do app)"], [[g["arch_str"], g["n"], ", ".join(g["loci"]), "; ".join(g["notes"])] for g in groups]))
    out.append("<h2>6. Diagramas de proteínas</h2>")
    for i in range(0, max(1, len(recs)), 8):
        chunk = recs[i:i + 8]
        if not chunk:
            break
        name = f"diag{i}"
        doc.addResource(QTextDocument.ImageResource, QUrl(name), render_architectures_image(chunk, 1400, source))
        out.append(f"<p><img src='{name}' width='1000'></p>")
    out.append("<h2>7. Verificações e limitações</h2>")
    out.append("<h3>Verificações da CDS (critérios do app)</h3>")
    out.append("<p>" + ("Nenhum alerta nos genes verificáveis." if not audit["cds_alerts"] else "; ".join(f"{html.escape(l)}: {html.escape(', '.join(a))}" for l, a in audit["cds_alerts"])) + "</p>")
    if audit["cds_unchecked"]:
        out.append(f"<p class='muted'>Sem sequência genômica/éxons (não verificáveis): {html.escape(', '.join(audit['cds_unchecked']))}.</p>")
    out.append("<h3>Candidatos possivelmente não classificados como PKS/NRPS/terpeno</h3>")
    out.append("<p>" + ("Nenhum." if not audit["candidates_ignored"] else "; ".join(f"{html.escape(c['locus'])} ({html.escape(c['reason'])})" for c in audit["candidates_ignored"])) + "</p>")
    out.append("<h3>Notas metodológicas</h3><ul>"
               "<li><b>Dados originais:</b> identificadores de domínios, coordenadas, tipo de BGC, <i>gene_kind</i> e status do módulo (do antiSMASH/Funannotate).</li>"
               "<li><b>Inferências do app:</b> classe da proteína (por domínios), agrupamento de arquiteturas, observações e verificações da CDS.</li>"
               "<li>O «status do módulo» é a classificação original do antiSMASH e não indica, por si, truncamento da proteína.</li>"
               "<li>Domínios são predições (HMMs); presença de domínio não demonstra atividade catalítica. Fontes (antiSMASH, Pfam, TIGRFAM) não foram misturadas, salvo indicação.</li></ul>")
    return "".join(out)


def write_pdf(path: str | Path, db, recs: list[Rec], species_id: int | None = None, source: str = "antismash", title: str = "") -> None:
    w = QPdfWriter(str(path))
    w.setPageSize(QPageSize(QPageSize.A4))
    w.setPageMargins(QMarginsF(14, 14, 14, 14), QPageLayout.Millimeter)
    w.setResolution(150)
    w.setTitle(title or "Relatório Molecular Biology Codex")
    w.setCreator(f"Molecular Biology Codex v{__version__}")
    doc = QTextDocument()
    doc.setDefaultFont(QFont("DejaVu Sans", 9))
    doc.setDefaultStyleSheet(CSS)
    doc.setHtml(build_html(db, recs, species_id, source, doc, title))
    doc.setPageSize(QSizeF(w.width(), w.height()))
    doc.print_(w)
