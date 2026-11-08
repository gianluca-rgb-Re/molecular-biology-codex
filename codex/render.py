"""Renderização de artigos (Markdown + extensões) para o subconjunto de HTML do Qt.

Extensões de sintaxe:
  [[id]] / [[id|texto]]      link interno
  [@chave] / [@a; @b]        citação do catálogo de referências (numerada por artigo)
  :::tipo Título opcional    bloco epistêmico (ver BOX_TYPES) ... encerrado por :::
  ![legenda](figures/x.svg)  figura (SVG/PNG) com legenda
  Cabeçalhos "## Camada N — ..." podem ser filtrados por camada.
"""
from __future__ import annotations
import html
import re
from pathlib import Path

import markdown

from .content import Article, Library, LEVELS, VERIFICATION, format_reference

BOX_TYPES = {
    "fato": ("Fato estabelecido", "#3fa37a"),
    "modelo": ("Modelo mecanístico aceito", "#4a90d9"),
    "predominante": ("Interpretação predominante", "#7a8fd9"),
    "hipotese": ("Hipótese", "#d9a441"),
    "indireta": ("Evidência indireta", "#c98a5a"),
    "inferencia": ("Inferência computacional", "#a07ad9"),
    "experimento": ("Resultado experimental", "#3fb0c9"),
    "debate": ("Questão em debate", "#d9704a"),
    "erro": ("Erro conceitual frequente", "#d9534f"),
    "nao": ("O que NÃO significa", "#d9534f"),
    "fungos": ("Em fungos — cuidado ao extrapolar", "#8cb04a"),
    "aviso": ("Aviso", "#d9a441"),
    "simulado": ("Dados simulados (didáticos)", "#d9a441"),
}
BOX_RE = re.compile(r"^:::(\w+)[ \t]*(.*?)\n(.*?)\n:::[ \t]*$", re.S | re.M)
CITE_RE = re.compile(r"\[@([^\]]+)\]")
WIKILINK_RE = re.compile(r"\[\[([a-z0-9\-]+)(?:\|([^\]]*))?\]\]")
LAYER_RE = re.compile(r"^## Camada (\d)\b", re.M)
IMG_RE = re.compile(r'<img alt="(.*?)" src="(.*?)"(?: title="(.*?)")? ?/?>')

CATEGORY_STYLE = {
    "Fundamentos moleculares": ("#4a90d9", "🧬"),
    "Genoma e arquitetura gênica": ("#7a8fd9", "🧩"),
    "Transcrição eucariótica": ("#4cc2b0", "⚙"),
    "Do RNA à proteína": ("#6fcf6f", "🔡"),
    "Regulação da expressão gênica": ("#e0a458", "🎛"),
    "Técnicas experimentais": ("#e07a5f", "🧪"),
    "Fungos, metabolismo secundário e PKSs": ("#d9534f", "🍄"),
    "Projeto aplicado": ("#c792ea", "🎯"),
    "Raciocínio científico": ("#3fb0c9", "🧠"),
    "Genômica e bioinformática": ("#8e7cc3", "🖥"),
    "Replicação e reparo": ("#d98cb3", "🧫"),
    "Enzimas e química analítica": ("#c9a227", "⚗"),
}


def cat_color(cat: str) -> str:
    return CATEGORY_STYLE.get(cat, ("#8a95a5", "📄"))[0]


def cat_icon(cat: str) -> str:
    return CATEGORY_STYLE.get(cat, ("#8a95a5", "📄"))[1]


LEVEL_STARS = {"iniciante": "★☆☆", "intermediario": "★★☆", "avancado": "★★★"}


def cat_color(cat: str) -> str:
    return CATEGORY_STYLE.get(cat, ("#8a95a5", "📄"))[0]


def cat_icon(cat: str) -> str:
    return CATEGORY_STYLE.get(cat, ("#8a95a5", "📄"))[1]


LEVEL_STARS = {"iniciante": "★☆☆", "intermediario": "★★☆", "avancado": "★★★"}

PALETTES = {
    "dark": dict(bg="#14171d", panel="#1b2028", panel2="#222833", text="#e6e9ef", muted="#9aa4b2",
                 accent="#4cc2b0", accent2="#e0a458", border="#2d3543", link="#6cb6ff", bad="#e06c6c"),
    "light": dict(bg="#f6f7f9", panel="#ffffff", panel2="#eef1f5", text="#1c2430", muted="#5b6675",
                  accent="#0f8f7e", accent2="#b9770e", border="#d5dbe3", link="#1a62b5", bad="#b3261e"),
}


def html_css(theme: str, font_pt: int = 11) -> str:
    p = PALETTES.get(theme, PALETTES["dark"])
    return f"""
    body {{ color:{p['text']}; font-size:{font_pt}pt; }}
    h1 {{ color:{p['accent']}; font-size:{font_pt + 9}pt; margin-bottom:2px; }}
    h2 {{ color:{p['accent']}; font-size:{font_pt + 4}pt; margin-top:18px; }}
    h3 {{ color:{p['accent2']}; font-size:{font_pt + 2}pt; margin-top:12px; }}
    h4 {{ color:{p['text']}; font-size:{font_pt + 1}pt; }}
    a {{ color:{p['link']}; text-decoration:none; }}
    code {{ background-color:{p['panel2']}; font-family:Consolas,monospace; }}
    th {{ background-color:{p['panel2']}; }}
    .muted {{ color:{p['muted']}; }}
    .broken {{ color:{p['bad']}; }}
    """


def _cite_replacer(order: list[str], lib: Library):
    def repl(m: re.Match) -> str:
        keys = [k.strip().lstrip("@") for k in re.split(r"[;,]", m.group(1)) if k.strip()]
        out = []
        for k in keys:
            if k not in order:
                order.append(k)
            n = order.index(k) + 1
            cls = "" if k in lib.refs else ' style="color:#d9534f"'
            out.append(f'<a href="codex://ref/{k}"{cls}>{n}</a>')
        return "<sup>[" + ", ".join(out) + "]</sup>"
    return repl


def _link_replacer(lib: Library):
    def repl(m: re.Match) -> str:
        aid, text = m.group(1), m.group(2)
        art = lib.get(aid)
        if art is None:
            return f'<span class="broken">{html.escape(text or aid)} (link quebrado: {aid})</span>'
        return f'<a href="codex://article/{aid}">{html.escape(text or art.title)}</a>'
    return repl


def split_layers(body: str) -> list[tuple[int | None, str]]:
    """Divide o corpo em seções '## ...'; devolve (camada|None, texto)."""
    parts = re.split(r"(?m)^(?=## )", body)
    out = []
    for p in parts:
        if not p.strip():
            continue
        m = LAYER_RE.match(p)
        out.append((int(m.group(1)) if m else None, p))
    return out


def _md(text: str) -> str:
    return markdown.markdown(text, extensions=["tables", "sane_lists", "fenced_code"], output_format="html")


def _box_html(kind: str, title: str, inner_md: str, theme: str) -> str:
    label, color = BOX_TYPES.get(kind, (kind.capitalize(), "#888888"))
    p = PALETTES[theme]
    head = f"<b style='color:{color}'>{html.escape(label)}</b>" + (f" — <b>{html.escape(title)}</b>" if title else "")
    return (f"<table width='100%' cellspacing='0' cellpadding='0' style='margin:8px 0'><tr>"
            f"<td width='5' bgcolor='{color}'></td>"
            f"<td bgcolor='{p['panel2']}' style='padding:6px 10px'>{head}<br>{inner_md}</td></tr></table>")


def render_body(body: str, lib: Library, order: list[str], theme: str, fig_dirs: list[Path]) -> str:
    boxes: list[str] = []

    def stash(m: re.Match) -> str:
        boxes.append(_box_html(m.group(1), m.group(2).strip(), _md(_inline(m.group(3))), theme))
        return f"\n\n@@BOX{len(boxes) - 1}@@\n\n"

    def _inline(t: str) -> str:
        t = CITE_RE.sub(_cite_replacer(order, lib), t)
        return WIKILINK_RE.sub(_link_replacer(lib), t)

    text = BOX_RE.sub(stash, body)
    out = _md(_inline(text))
    for i, b in enumerate(boxes):
        out = out.replace(f"<p>@@BOX{i}@@</p>", b).replace(f"@@BOX{i}@@", b)

    def fig(m: re.Match) -> str:
        alt, src, title = m.group(1), m.group(2), m.group(3) or m.group(1)
        path = next((d / Path(src).name for d in fig_dirs if (d / Path(src).name).exists()), None)
        if path is None:
            return f'<span class="broken">[figura ausente: {html.escape(src)}]</span>'
        return (f'<table width="100%"><tr><td align="center"><a href="codex://fig/{path.name}">'
                f'<img src="{path.resolve().as_uri()}" width="760"></a><br>'
                f'<i class="muted">{html.escape(title)} <span class="muted">(clique para ampliar)</span></i>'
                f'</td></tr></table>')
    out = IMG_RE.sub(fig, out)
    return out.replace("<table>", '<table border="1" cellspacing="0" cellpadding="5" width="100%">')


def render_article(art: Article, lib: Library, theme: str = "dark", layer: int | None = None,
                   fig_dirs: list[Path] | None = None, level: int | None = None,
                   mastery_label: str = "") -> tuple[str, list[str]]:
    """Devolve (html, chaves_de_referência_na_ordem_de_citação)."""
    fig_dirs = fig_dirs or []
    p = PALETTES[theme]
    order: list[str] = []
    cc = cat_color(art.category)
    pips = "".join("●" if k < (level or 0) else "○" for k in range(4))
    chips = [f"Dificuldade <b>{LEVEL_STARS.get(art.level, '')}</b> {LEVELS.get(art.level, art.level)}"]
    if level is not None:
        chips.append(f"Domínio <b style='color:{cc}'>{pips}</b> {mastery_label}")
    chips.append(f"🃏 {len(art.flashcards)} cartões · 📝 {len(art.questions)} questões")
    head = [f"<table width='100%' cellspacing='0' cellpadding='0'><tr><td width='9' bgcolor='{cc}'></td>"
            f"<td bgcolor='{p['panel2']}' style='padding:10px 16px'>"
            f"<span style='color:{cc}'><b>{cat_icon(art.category)} {html.escape(art.category)}"
            f"{' › ' + html.escape(art.subcategory) if art.subcategory else ''}</b></span><br>"
            f"<span style='font-size:21pt; color:{p['accent']}'><b>{html.escape(art.title)}</b></span><br>"
            + (f"<i class='muted'>{html.escape(art.title_en)}</i><br>" if art.title_en else "")
            + f"<span class='muted'>{' &nbsp;·&nbsp; '.join(chips)}</span></td></tr></table>"]
    syn = ", ".join(art.synonyms)
    if syn:
        head.append(f"<p class='muted'>Sinônimos e siglas: {html.escape(syn)}</p>")
    if art.verification != "revisado":
        head.append(_box_html("aviso", VERIFICATION.get(art.verification, art.verification),
                              "Confira as referências antes de usar este texto como fonte.", theme))
    if art.summary:
        head.append(f"<p><b>Resumo.</b> {html.escape(art.summary)}</p>")
    if art.prereqs:
        links = ", ".join(
            f"<a href='codex://article/{x}'>{html.escape(lib.articles[x].title)}</a>" if x in lib.articles
            else f"<span class='broken'>{html.escape(x)} (inexistente)</span>" for x in art.prereqs)
        head.append(f"<h3>Antes de continuar</h3><p>Pré-requisitos sugeridos: {links}</p>")

    body_html = []
    for lay, section in split_layers(art.body):
        if layer is not None and lay is not None and lay != layer:
            continue
        body_html.append(render_body(section, lib, order, theme, fig_dirs))

    tail = []
    if art.next:
        items = []
        for n in art.next:
            nid = n.get("id", "")
            if nid in lib.articles:
                items.append(f"<li><a href='codex://article/{nid}'>{html.escape(lib.articles[nid].title)}</a>"
                             f" — {html.escape(str(n.get('why', '')))}</li>")
        if items:
            tail.append("<h2>Continue explorando</h2><ul>" + "".join(items) + "</ul>")
    if art.flashcards or art.questions:
        tail.append(f"<p class='muted'>Este artigo tem {len(art.flashcards)} flashcard(s) e "
                    f"{len(art.questions)} questão(ões) no Modo de estudo.</p>")
    return "".join(head + body_html + tail), order


def reference_html(key: str, lib: Library, theme: str = "dark") -> str:
    from .content import REF_STATUS, REF_TYPES  # noqa: F401
    ref = lib.refs.get(key)
    if not ref:
        return f"<p class='broken'>Referência '{html.escape(key)}' não encontrada no catálogo.</p>"
    v = ref.get("verification", {}) or {}
    status = REF_STATUS.get(v.get("status", "pendente"), "Pendente de verificação")
    rows = [f"<p>{html.escape(format_reference(ref))}</p>",
            f"<p><b>Tipo:</b> {html.escape(str(ref.get('type', '—')))}</p>",
            f"<p><b>Verificação:</b> {html.escape(status)}</p>"]
    for lab, k in (("DOI", "doi"), ("PMID", "pmid"), ("PMCID", "pmcid"), ("URL", "url")):
        if ref.get(k):
            val = html.escape(str(ref[k]))
            if k == "doi":
                rows.append(f"<p><b>DOI:</b> <a href='https://doi.org/{val}'>{val}</a></p>")
            elif k == "url":
                rows.append(f"<p><b>URL:</b> <a href='{val}'>{val}</a></p>")
            else:
                rows.append(f"<p><b>{lab}:</b> {val}</p>")
    if v.get("how"):
        rows.append(f"<p class='muted'>Como foi conferida ({html.escape(str(v.get('date', '')))}): "
                    f"{html.escape(str(v['how']))}</p>")
    if ref.get("supports"):
        rows.append("<p><b>Sustenta:</b> " + html.escape("; ".join(map(str, ref["supports"]))) + "</p>")
    if ref.get("evidence_note"):
        rows.append(f"<p><b>Força da evidência:</b> {html.escape(str(ref['evidence_note']))}</p>")
    return "".join(rows)
