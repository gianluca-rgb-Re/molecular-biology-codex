"""Relatório HTML autônomo (sem Qt): imprimir como PDF pelo navegador. Mesmo conteúdo do relatório PDF do desktop."""
from __future__ import annotations
import datetime as dt
import html

from . import __version__, analysis, genoteca, svgviz
from .analysis import Rec, SOURCES

CSS = """body{font-family:'DejaVu Sans',Arial,sans-serif;color:#1c2430;max-width:1000px;margin:24px auto;font-size:13px}
h1{color:#1f3a5f}h2{color:#1f3a5f;border-bottom:1px solid #1f3a5f;margin-top:28px}h3{color:#2c5282}
table{border-collapse:collapse;width:100%;margin:8px 0}th{background:#1f3a5f;color:#fff;text-align:left}td,th{border:1px solid #9aa4b2;padding:3px 6px;font-size:12px}
.muted{color:#5b6675;font-size:11px}@media print{body{margin:0}h2{page-break-after:avoid}svg{page-break-inside:avoid}}"""


def _t(head, rows):
    return "<table><tr>" + "".join(f"<th>{html.escape(str(h))}</th>" for h in head) + "</tr>" + "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows) + "</table>"


def report_html(db, recs: list[Rec], species_id: int | None, source: str = "antismash", title: str = "") -> str:
    sp = genoteca.get_species(db, species_id) if species_id else None
    audit = analysis.audit(db, species_id)
    bgcs = genoteca.bgcs_of_species(db, species_id) if species_id else []
    n = len(recs)
    versions = sorted({(genoteca.bgc_meta(b).get("antismash_version") or "") for b in bgcs} - {""})
    annot = sorted({(genoteca.bgc_meta(b).get("annotator") or "") for b in bgcs} - {""})
    p = [f"<h1>{html.escape(title or 'Relatório de análise de genes biossintéticos')}</h1>",
         f"<p class='muted'>Molecular Biology Codex v{__version__} (web) · {dt.datetime.now():%d/%m/%Y %H:%M} · domínios: {html.escape(SOURCES.get(source, source))} · nomes do antiSMASH sem o prefixo «PKS_» · "
         "para PDF: use Imprimir → Salvar como PDF no navegador</p>", "<h2>1. Identificação do genoma</h2>",
         _t(["Campo", "Valor"], [["Espécie", sp["name"] if sp else ", ".join(sorted({r.species for r in recs})) or "—"], ["Linhagem", (sp and sp["strain"]) or "—"],
                                 ["Acesso/scaffold", (sp and sp["genome_accession"]) or "—"], ["Taxonomia", (sp and sp["taxonomy"]) or "—"],
                                 ["Versão do antiSMASH", ", ".join(versions) or "—"], ["Anotação estrutural", ", ".join(annot) or "—"], ["Regiões (BGCs)", len(bgcs)],
                                 ["Genes importados / genes-âncora", f"{audit['total_genes']} / {audit['core']}"]]),
         "<p class='muted'>O relatório cobre apenas os genes/regiões importados (não necessariamente o genoma completo).</p>", "<h2>2. Genes identificados</h2>",
         _t(["Gene", "Classe (domínios)", "Tipo de BGC", "Scaffold", "Início–Fim", "Fita", "aa", "Éxons", "Status do módulo antiSMASH", "Fonte"],
            [[r.locus, r.gene_class, ",".join(r.bgc_types) or "—", r.scaffold, f"{r.start:,}–{r.end:,}".replace(",", "."), r.strand, r.aa, r.exons, r.module_status, r.source] for r in recs]),
         "<h2>3. Distribuição das classes</h2>", svgviz.bar_chart_svg(analysis.class_distribution(recs), "Classe da proteína (inferida dos domínios)", 800, n),
         svgviz.bar_chart_svg(analysis.class_distribution(recs, "bgc"), "Tipo de BGC (antiSMASH)", 800, n, "#d9534f"),
         "<p class='muted'>Classe da proteína e tipo de BGC são informações distintas.</p>", "<h2>4. Frequência dos domínios</h2>"]
    freq = analysis.domain_frequency(recs, source)
    p += [svgviz.bar_chart_svg([(f["domain"], f["proteins"]) for f in freq], "Proteínas com cada domínio", 800, n, None),
          _t(["Domínio", "Proteínas", "Frequência", "Cópias", "Categoria"], [[f["domain"], f["proteins"], f"{100 * f['freq']:.0f}%", f["copies"], f["category"]] for f in freq]),
          "<h2>5. Comparação de arquiteturas</h2>",
          _t(["Arquitetura (ordem preservada)", "Nº", "Genes", "Observações (critérios do app)"], [[g["arch_str"], g["n"], ", ".join(g["loci"]), "; ".join(g["notes"])] for g in analysis.group_architectures(recs, source)]),
          "<h2>6. Diagramas de proteínas</h2>"]
    for i in range(0, max(1, n), 10):
        if recs[i:i + 10]:
            p.append(svgviz.architectures_svg(recs[i:i + 10], source, 1000))
    p += ["<h2>7. Verificações e limitações</h2><h3>Verificações da CDS (critérios do app)</h3><p>"
          + ("Nenhum alerta nos genes verificáveis." if not audit["cds_alerts"] else "; ".join(f"{html.escape(a)}: {html.escape(', '.join(b))}" for a, b in audit["cds_alerts"])) + "</p>",
          "<h3>Candidatos possivelmente não classificados</h3><p>" + ("Nenhum." if not audit["candidates_ignored"] else "; ".join(f"{html.escape(c['locus'])} ({html.escape(c['reason'])})" for c in audit["candidates_ignored"])) + "</p>",
          "<h3>Notas</h3><ul><li><b>Dados originais:</b> identificadores/coordenadas de domínios, tipo de BGC, gene_kind, status do módulo, éxons.</li>"
          "<li><b>Inferências do app:</b> classe da proteína, agrupamentos, observações, verificações da CDS.</li>"
          "<li>O «status do módulo» é a classificação do antiSMASH e não indica truncamento.</li><li>Domínios são predições; antiSMASH, Pfam e TIGRFAM não foram misturados, salvo indicação.</li></ul>"]
    return f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><title>{html.escape(title or 'Relatório')}</title><style>{CSS}</style></head><body>{''.join(p)}</body></html>"
