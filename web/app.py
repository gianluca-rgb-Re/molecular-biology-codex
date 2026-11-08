"""Molecular Biology Codex — versão web (Streamlit). Mesmo núcleo científico do desktop (pacote `codex`)."""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from codex import __version__, analysis, export, genoteca, svgviz  # noqa: E402
from codex.analysis import CORE_CLASSES, SOURCES, source_label  # noqa: E402
from codex.antismash import display_name  # noqa: E402
from codex.genemodel import wrap_fasta  # noqa: E402
from session import MAX_MB, WebSession  # noqa: E402

st.set_page_config(page_title=f"Molecular Biology Codex v{__version__}", page_icon="🧬", layout="wide")


def svg(s: str) -> None:
    st.markdown(f'<div style="overflow-x:auto;background:#fff;border-radius:6px;padding:4px">{s}</div>', unsafe_allow_html=True)


def gate() -> None:
    code = os.environ.get("CODEX_ACCESS_CODE", "")
    if code and not st.session_state.get("ok"):
        st.title("🧬 Molecular Biology Codex")
        v = st.text_input("Código de acesso", type="password")
        if v and v == code:
            st.session_state["ok"] = True
            st.rerun()
        st.stop()


gate()
if "sess" not in st.session_state:
    st.session_state["sess"] = WebSession()
S: WebSession = st.session_state["sess"]

st.title("🧬 Molecular Biology Codex")
st.caption(f"v{__version__} · mineração e comparação de domínios biossintéticos (PKS/NRPS) a partir de GenBank do antiSMASH · seus arquivos ficam só nesta sessão")

# ------------------------------------------------------------------ filtros globais (barra lateral)
with st.sidebar:
    st.header("Filtros")
    sps = S.species()
    sp_opts = {"Todas as espécies": None, **{r["name"] + (f" ({r['strain']})" if r["strain"] else ""): r["id"] for r in sps}}
    sp_id = sp_opts[st.selectbox("Espécie", list(sp_opts))]
    all_recs = S.records(sp_id)
    cls = st.selectbox("Classe da proteína", ["todas"] + sorted({r.gene_class for r in all_recs}))
    bgc = st.selectbox("Tipo de BGC", ["todos"] + sorted({t for r in all_recs for t in r.bgc_types}))
    src_label = st.selectbox("Fonte dos domínios", list(SOURCES.values()))
    src = next(k for k, v in SOURCES.items() if v == src_label)
    txt = st.text_input("Gene, scaffold ou domínio")
    recs = analysis.filter_records(all_recs, None if cls == "todas" else cls, None if bgc == "todos" else bgc, txt)
    st.metric("Genes-âncora no recorte", f"{len(recs)} / {len(all_recs)}")
    st.divider()
    if st.button("🗑 Apagar meus dados agora", help="Remove da memória todos os arquivos e resultados desta sessão"):
        S.clear()
        st.rerun()

t_imp, t_genes, t_an, t_exp, t_val, t_about = st.tabs(["📥 Importar", "🧬 Genes", "🧮 Análise de PKS", "📤 Exportar", "✅ Validação", "ℹ Sobre e privacidade"])

# ------------------------------------------------------------------ importar
with t_imp:
    st.write("Envie o GenBank **do antiSMASH** (`*.regionNNN.gbk` — vários de uma vez — ou o GenBank completo anotado). GenBank sem antiSMASH (Funannotate/NCBI) usa uma triagem Pfam/texto (heurística).")
    files = st.file_uploader("Arquivos GenBank", type=["gb", "gbk", "gbff", "gbf", "txt"], accept_multiple_files=True)
    if files and st.button("▶ Processar arquivos", type="primary"):
        for f in files:
            with st.status(f"Lendo {f.name}…", expanded=False) as stt:
                try:
                    r = S.import_bytes(f.name, f.getvalue())
                    stt.update(label=f"{f.name}: {r['regions']} região(ões), {r['genes']} gene(s) — {r['mode']}", state="complete")
                except Exception as e:  # noqa: BLE001
                    stt.update(label=f"{f.name}: não foi possível importar", state="error")
                    st.error(str(e))
        st.rerun()
    if S.imports:
        st.dataframe(pd.DataFrame(S.imports).drop(columns=["species_id"]).rename(columns={"file": "Arquivo", "mode": "Modo", "regions": "Regiões", "genes": "Genes"}),
                     hide_index=True, width="stretch")
    st.caption(f"Limite por arquivo neste servidor: {MAX_MB} MB. Os arquivos enviados são apagados do disco logo após a leitura.")

# ------------------------------------------------------------------ genes
with t_genes:
    if not recs:
        st.info("Nenhum gene no recorte. Importe um GenBank na aba «Importar».")
    else:
        keys = ["locus", "gene_class", "bgc_types", "scaffold", "start", "end", "strand", "aa", "exons", "arch", "module", "source", "cds"]
        head, rows = export.table(recs, keys, src)
        st.dataframe(pd.DataFrame(rows, columns=head), hide_index=True, width="stretch")
        st.caption("«Status do módulo antiSMASH» é a classificação original do antiSMASH e não indica truncamento; «Verificações da CDS» usa critérios próprios do app.")
        st.subheader("Modelo gênico")
        pick = st.selectbox("Gene", [r.locus for r in recs])
        rec = next(r for r in recs if r.locus == pick)
        row = S.gene_row(rec.id)
        m = genoteca.model_for_gene(row)
        if m is None:
            st.warning("Este gene não tem sequência genômica/éxons importados.")
        else:
            doms = genoteca.domains_of(row)
            stt = m.stats()
            c = st.columns(5)
            c[0].metric("Aminoácidos", f"{stt['aa']:,}".replace(",", "."))
            c[1].metric("Éxons / íntrons", f"{stt['exons']} / {stt['introns']}")
            c[2].metric("CDS (nt)", f"{stt['cds_nt']:,}".replace(",", "."))
            c[3].metric("Massa (kDa)", f"{stt.get('mw_kda', 0):.1f}")
            c[4].metric("pI", f"{stt.get('pi', 0):.2f}")
            svg(svgviz.gene_structure_svg(m, doms))
            a, b, c3, d, e = st.tabs(["Éxons e íntrons", "Sequências", "Estatísticas e verificações", "Domínios", "Simular retenção de íntron"])
            with a:
                intr = {i.index: i for i in m.introns()}
                tb = []
                for ex in m.exon_table():
                    tb.append(["Éxon", ex["n"], ex["len"], f"{ex['local'][0]}–{ex['local'][1]}", f"{ex['scaffold'][0]}–{ex['scaffold'][1]}", f"{ex['aa_from']}–{ex['aa_to']}", ""])
                    if ex["n"] in intr:
                        i = intr[ex["n"]]
                        s0, s1 = m.rel_to_local(i.a, i.b)
                        tb.append(["Íntron", i.index, i.length, f"{s0}–{s1}", f"{s0 + m.offset}–{s1 + m.offset}", "", f"{i.donor}…{i.acceptor} ({i.class_}), fase {i.phase}"])
                st.dataframe(pd.DataFrame(tb, columns=["Tipo", "Nº", "nt", "Local", "Scaffold", "aa", "Sítios / fase"]), hide_index=True, width="stretch")
            with b:
                kind = st.radio("Sequência", ["cDNA/CDS (sem íntrons)", "Proteína", "Genômica (com íntrons)"], horizontal=True)
                seq = {"cDNA/CDS (sem íntrons)": m.coding_seq(), "Proteína": m.protein(), "Genômica (com íntrons)": m.genomic}[kind]
                fa = wrap_fasta(rec.locus, f"{kind} [{rec.species}]", seq)
                st.text_area("FASTA", fa, height=220)
                st.download_button("💾 Baixar FASTA", fa, file_name=f"{rec.locus}.fasta")
            with c3:
                ck = m.checks()
                st.write({k: (v if v is not None else "—") for k, v in ck.items()})
                comp = stt.get("composition", {})
                st.dataframe(pd.DataFrame({"Estatística": ["GC genômico %", "GC CDS %", "GC3 %", "Instabilidade", "GRAVY", "Íntron médio (nt)"],
                                           "Valor": [round(stt["gc_genomic"], 1), round(stt["gc_cds"], 1), round(stt["gc3"], 1), round(stt.get("instability", 0), 1),
                                                     round(stt.get("gravy", 0), 3), round(stt["mean_intron"])]}), hide_index=True)
                if comp:
                    st.bar_chart(pd.Series(comp, name="aminoácidos").sort_values(ascending=False))
            with d:
                st.dataframe(pd.DataFrame([[display_name(x["name"]), x["name"], source_label(x), x["start"], x["end"], m.exon_of_aa(max(1, x["start"])) if x["end"] > x["start"] else "",
                                            x["evalue"], " | ".join(x["notes"])] for x in doms],
                                          columns=["Domínio", "Identificador original", "Fonte", "aa início", "aa fim", "Éxon inicial", "E-value", "Observações do arquivo"]),
                             hide_index=True, width="stretch")
            with e:
                n_in = len(m.introns())
                ret = st.multiselect("Íntrons retidos no mRNA", list(range(1, n_in + 1)))
                if ret:
                    eff = analysis.retention_effect(m, doms, set(ret))
                    st.write(f"Proteína: **{eff['aa_before']} → {eff['aa_after']} aa**; primeira diferença na posição {eff['first_difference']}; quadro múltiplo de 3: {eff['frame_ok']}; parada: {eff['has_stop']}.")
                    st.write("Domínios afetados: " + ("; ".join(eff["domains_affected"]) or "nenhum"))
                    st.caption("Simulação in silico; não prova que o evento ocorra na célula.")

# ------------------------------------------------------------------ análise
with t_an:
    if len(recs) == 0:
        st.info("Importe um GenBank para analisar.")
    else:
        a, b, c, d, e = st.tabs(["Matriz de domínios", "Arquiteturas", "Frequência", "Comparar", "Diagramas"])
        with a:
            cols, rows = analysis.matrix(recs, src)
            df = pd.DataFrame([[r.locus, r.gene_class, ",".join(r.bgc_types) or "—", r.aa, r.exons, r.arch_str(src)] + [("●" if n == 1 else f"● ×{n}") if n else "" for n in cnt]
                               for r, cnt in rows], columns=["Gene", "Classe da proteína", "Tipo de BGC", "aa", "Éxons", "Arquitetura"] + cols)
            sty = df.style
            for col in cols:
                sty = sty.apply(lambda s, c=col: [f"background-color:{svgviz.domain_hex(c)}88" if v else "" for v in s], subset=[col])
            st.dataframe(sty, hide_index=True, width="stretch")
            fr = analysis.domain_frequency(recs, src)
            exc = analysis.exclusive_domains(recs, src)
            st.write("**Presentes em todas:** " + (", ".join(f["domain"] for f in fr if f["category"] == "universal") or "—"))
            st.write("**Exclusivos:** " + ("; ".join(f"{k} → {', '.join(v)}" for k, v in exc.items()) or "—"))
        with b:
            g = analysis.group_architectures(recs, src)
            st.dataframe(pd.DataFrame([[x["arch_str"], x["n"], ", ".join(x["loci"]), "; ".join(x["notes"])] for x in g],
                                      columns=["Arquitetura (ordem preservada)", "Nº de proteínas", "Genes", "Observações (critérios do app)"]), hide_index=True, width="stretch")
        with c:
            fr = analysis.domain_frequency(recs, src)
            st.dataframe(pd.DataFrame([[f["domain"], f["proteins"], f"{100 * f['freq']:.0f}%", f["copies"], f["category"]] for f in fr],
                                      columns=["Domínio", "Proteínas", "Frequência", "Cópias", "Categoria"]), hide_index=True, width="stretch")
            svg(svgviz.bar_chart_svg([(f["domain"], f["proteins"]) for f in fr], "Proteínas com cada domínio", 800, len(recs), None))
            svg(svgviz.bar_chart_svg(analysis.class_distribution(recs), "Classe da proteína (inferida dos domínios)", 800, len(recs)))
            svg(svgviz.bar_chart_svg(analysis.class_distribution(recs, "bgc"), "Tipo de BGC (antiSMASH)", 800, len(recs), "#d9534f"))
        with d:
            sel = st.multiselect("Proteínas para comparar (2 ou mais)", [r.locus for r in recs], default=[r.locus for r in recs[:2]])
            chosen = [r for r in recs if r.locus in sel]
            if len(chosen) >= 2:
                cmp = analysis.compare(chosen, src)
                st.dataframe(pd.DataFrame(cmp["rows"]).set_index("Gene").astype(str).T, width="stretch")
                for p in cmp["pairs"]:
                    state = "idênticas" if p["identical"] else ("mesmos domínios em ordem diferente" if p["same_set_different_order"] else "diferentes")
                    st.write(f"**{p['a']} × {p['b']}**: {state}; distância de edição {p['edit_distance']}; Δ aa {p['aa_diff']:+d}; compartilhados: {', '.join(p['shared']) or '—'}; "
                             f"só em {p['a']}: {', '.join(p['only_a']) or '—'}; só em {p['b']}: {', '.join(p['only_b']) or '—'}")
                st.caption("A ausência de um domínio na lista do antiSMASH não implica truncamento nem perda de função.")
                svg(svgviz.architectures_svg(chosen, src))
            else:
                st.info("Selecione ao menos duas proteínas.")
        with e:
            shown = recs[:40]
            diag = svgviz.architectures_svg(shown, src, 1100, f"Arquiteturas de domínios — {len(shown)} proteína(s)")
            svg(diag)
            st.download_button("💾 Baixar SVG", diag, file_name="diagramas_dominios.svg", mime="image/svg+xml")

# ------------------------------------------------------------------ exportar
with t_exp:
    scope = st.radio("Registros", ["Filtrados na barra lateral", "Todos os genes-âncora"], horizontal=True)
    out_recs = recs if scope.startswith("Filtrados") else all_recs
    labels = {k: export.COLUMN_LABELS[k] for k in export.COLUMN_KEYS}
    chosen = st.multiselect("Colunas", export.COLUMN_KEYS, default=export.DEFAULT_KEYS, format_func=lambda k: labels[k])
    if out_recs and chosen:
        c1, c2, c3 = st.columns(3)
        c1.download_button("📄 CSV", S.csv(out_recs, chosen, src), file_name="genes_biossinteticos.csv", mime="text/csv")
        c2.download_button("📊 XLSX (Excel)", S.xlsx(out_recs, chosen, src, {"species": ", ".join(sorted({r.species for r in out_recs}))}),
                           file_name="genes_biossinteticos.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if c3.button("📑 Gerar relatório"):
            pdf = S.pdf(out_recs, sp_id, src, "Relatório de análise de genes biossintéticos")
            if pdf:
                st.download_button("⬇ Baixar PDF", pdf, file_name="relatorio_pks.pdf", mime="application/pdf")
            html_b = S.html_report(out_recs, sp_id, src)
            st.download_button("⬇ Baixar relatório HTML (imprima como PDF no navegador)", html_b, file_name="relatorio_pks.html", mime="text/html")
    else:
        st.info("Não há registros ou colunas selecionados.")

# ------------------------------------------------------------------ validação
with t_val:
    if st.button("▶ Rodar verificação científica do conjunto importado"):
        a = analysis.audit(S.db, sp_id)
        st.write(f"{a['total_genes']} gene(s) importado(s); {a['core']} genes-âncora.")
        st.warning("A verificação cobre **apenas o que foi importado**. Para a lista completa de PKS do genoma, importe o GenBank completo anotado pelo antiSMASH.")
        st.write("**Candidatos possivelmente ignorados (sugestões):**", a["candidates_ignored"] or "nenhum")
        st.write("**Posições duplicadas:**", a["duplicate_positions"] or "nenhuma", " · **Proteínas idênticas:**", a["duplicate_proteins"] or "nenhuma")
        st.write("**Verificações da CDS (alertas):**", a["cds_alerts"] or "nenhum", " · **Não verificáveis:**", a["cds_unchecked"] or "nenhum")
        st.caption("Dados originais: identificadores/coordenadas de domínios, tipo de BGC, gene_kind, status do módulo, éxons. Inferências do app: classe da proteína, agrupamentos, observações e verificações.")

# ------------------------------------------------------------------ sobre
with t_about:
    st.markdown(f"""
**Privacidade.** Cada sessão do navegador tem um banco **em memória** e um diretório temporário privado; o arquivo enviado é apagado do disco logo após a leitura, nada é gravado de forma permanente
e as sessões não compartilham dados. O botão «Apagar meus dados agora» limpa tudo. Fechar a aba encerra a sessão.
Mesmo assim, o arquivo trafega até o servidor que hospeda este app: **não envie genomas inéditos/confidenciais a servidores de terceiros sem autorização**; para dados sensíveis use a versão desktop ou um servidor próprio.

**Limites.** Tamanho máximo por arquivo aqui: {MAX_MB} MB. Servidores gratuitos têm pouca memória (Streamlit Community Cloud: em torno de 0,7–2,7 GB) e hibernam após inatividade.
Genomas completos muito grandes podem exceder a memória: envie as regiões (`*.regionNNN.gbk`) ou use a versão desktop / servidor próprio.

**Ciência.** Nomes de domínios = nomes do antiSMASH sem o prefixo «PKS_»; fontes (antiSMASH/Pfam/TIGRFAM) não são misturadas sem pedido; «status do módulo» ≠ truncamento. Domínios são predições.
""")
