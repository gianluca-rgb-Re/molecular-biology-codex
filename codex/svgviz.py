"""Figuras em SVG (sem Qt): arquiteturas de domínios, gráfico de barras e estrutura do gene. Usadas na versão web e no relatório HTML."""
from __future__ import annotations
import html
import zlib

from .analysis import Rec, source_label
from .antismash import display_name

_KEY = (("KS", "#d9534f"), ("AT", "#e0a458"), ("ACYL_TRANSF", "#e0a458"), ("DH", "#2ea66b"), ("ER", "#3fb0c9"), ("ADH_", "#3fb0c9"), ("KR", "#9b59b6"),
        ("PP", "#4a90d9"), ("ACP", "#4a90d9"), ("MT", "#e67e9c"), ("METHYLTRANSF", "#e67e9c"), ("TE", "#6fcf6f"), ("COND", "#7a8fd9"),
        ("AMP", "#e07a5f"), ("PCP", "#4cc2b0"), ("SAT", "#c9a227"), ("PT", "#8e9aaf"))


def domain_hex(name: str) -> str:
    u = display_name(name).upper()
    for k, c in _KEY:
        if u.startswith(k):
            return c
    h = zlib.crc32(name.encode()) & 0xFFFFFF
    return f"#{(90 + h % 120):02x}{(90 + (h >> 8) % 120):02x}{(90 + (h >> 16) % 120):02x}"


def _text_color(hex_: str) -> str:
    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return "#ffffff" if (0.299 * r + 0.587 * g + 0.114 * b) < 150 else "#1c2430"


def architectures_svg(recs: list[Rec], source: str = "antismash", width: int = 1100, title: str = "") -> str:
    left, right, row_h = 190, 20, 46
    bar_w = width - left - right
    max_aa = max([r.aa for r in recs] + [1])
    y = 10 + (26 if title else 0)
    out: list[str] = []
    if title:
        out.append(f'<text x="8" y="22" font-size="15" font-weight="bold" fill="#1c2430">{html.escape(title)}</text>')
    legend: dict[str, str] = {}
    for r in recs:
        out.append(f'<text x="8" y="{y + 14}" font-size="13" font-weight="bold" fill="#1c2430">{html.escape(r.locus)}</text>')
        out.append(f'<text x="8" y="{y + 28}" font-size="10" fill="#5b6675">{html.escape(r.gene_class)} · {r.aa} aa · {r.exons} éxons</text>')
        out.append(f'<text x="8" y="{y + 40}" font-size="10" fill="#5b6675">BGC: {html.escape(",".join(r.bgc_types) or "—")}</text>')
        out.append(f'<rect x="{left}" y="{y + 8}" width="{max(4, bar_w * r.aa / max_aa):.1f}" height="22" rx="3" fill="#eef1f5" stroke="#1c2430"/>')
        for d in r.doms(source):
            if d.get("end", 0) <= d.get("start", 0):
                continue
            dn, c = display_name(d["name"]), domain_hex(d["name"])
            x1, w = left + bar_w * d["start"] / max_aa, max(3.0, bar_w * (d["end"] - d["start"]) / max_aa)
            legend.setdefault(dn, c)
            label = dn if w > 7 * len(dn) * 0.9 else (dn[:max(1, int(w // 7))] + "…" if w > 14 else "")
            out.append(f'<g><title>{html.escape(d["name"])} ({d["start"]}–{d["end"]} aa) · {html.escape(source_label(d))}</title>'
                       f'<rect x="{x1:.1f}" y="{y + 5}" width="{w:.1f}" height="28" fill="{c}" stroke="#1c2430"/>'
                       f'<text x="{x1 + w / 2:.1f}" y="{y + 23}" font-size="10" font-weight="bold" text-anchor="middle" fill="{_text_color(c)}">{html.escape(label)}</text></g>')
        y += row_h
    step = 500 if max_aa > 1500 else 250 if max_aa > 600 else 100
    for a in range(0, max_aa + 1, step):
        x = left + bar_w * a / max_aa
        out.append(f'<line x1="{x:.1f}" y1="{y}" x2="{x:.1f}" y2="{y + 4}" stroke="#5b6675"/><text x="{x:.1f}" y="{y + 15}" font-size="9" text-anchor="middle" fill="#5b6675">{a}</text>')
    y += 28
    x = 8
    for n, c in legend.items():
        w = 22 + 7 * len(n)
        if x + w > width - 8:
            x, y = 8, y + 16
        out.append(f'<rect x="{x}" y="{y}" width="12" height="10" fill="{c}" stroke="#1c2430"/><text x="{x + 16}" y="{y + 9}" font-size="10" fill="#1c2430">{html.escape(n)}</text>')
        x += w + 6
    y += 20
    srcs = ", ".join(sorted({source_label(d) for r in recs for d in r.doms(source)})) or "—"
    out.append(f'<text x="8" y="{y + 8}" font-size="9" fill="#5b6675">Fonte dos domínios: {html.escape(srcs)}. Nomes do antiSMASH sem o prefixo «PKS_».</text>')
    h = y + 20
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {h}" width="100%" style="background:#fff;max-width:{width}px">{"".join(out)}</svg>'


def bar_chart_svg(items: list[tuple[str, float]], title: str, width: int = 800, total: float | None = None, color: str | None = "#4a90d9") -> str:
    left, top = 210, max([v for _l, v in items] + [1])
    h = 40 + 24 * max(1, len(items))
    out = [f'<text x="8" y="20" font-size="14" font-weight="bold" fill="#1c2430">{html.escape(title)}</text>']
    for i, (lab, v) in enumerate(items):
        y, w = 34 + i * 24, (width - left - 120) * v / top
        c = color or domain_hex(lab)
        pct = f" ({100 * v / total:.0f}%)" if total else ""
        out.append(f'<text x="{left - 8}" y="{y + 14}" font-size="11" text-anchor="end" fill="#1c2430">{html.escape(lab)}</text>'
                   f'<rect x="{left}" y="{y + 2}" width="{max(2, w):.1f}" height="16" fill="{c}"/>'
                   f'<text x="{left + w + 6:.1f}" y="{y + 14}" font-size="11" fill="#5b6675">{v:g}{pct}</text>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {h}" width="100%" style="background:#fff;max-width:{width}px">{"".join(out)}</svg>'


def gene_structure_svg(model, domains: list[dict] | None = None, width: int = 1100) -> str:
    """Éxons (caixas), íntrons (ângulos numerados), ATG/parada e domínios mapeados sobre o gene."""
    n = max(1, len(model.genomic))
    k = (width - 20) / n
    out = [f'<text x="10" y="14" font-size="11" fill="#5b6675">Gene orientado 5′→3′ (fita {"+" if model.strand != -1 else "−"}); {len(model.genomic):,} pb</text>'.replace(",", ".")]
    y0 = 60
    out.append(f'<line x1="10" y1="{y0 + 14}" x2="{width - 10}" y2="{y0 + 14}" stroke="#8a95a5"/>')
    for i in model.introns():
        x1, x2 = 10 + i.a * k, 10 + i.b * k
        out.append(f'<g><title>Íntron {i.index}: {i.length} nt · {i.donor}…{i.acceptor} · {html.escape(i.class_)} · fase {i.phase}</title>'
                   f'<polyline points="{x1:.1f},{y0 + 14} {(x1 + x2) / 2:.1f},{y0 - 8} {x2:.1f},{y0 + 14}" fill="none" stroke="#5b6675" stroke-width="1.5"/></g>'
                   f'<text x="{(x1 + x2) / 2:.1f}" y="{y0 - 12}" font-size="9" text-anchor="middle" fill="#5b6675">{i.index}</text>')
    for e, (a, b) in enumerate(model.exons_rel, 1):
        out.append(f'<g><title>Éxon {e}: {b - a} nt</title><rect x="{10 + a * k:.1f}" y="{y0}" width="{max(2, (b - a) * k):.1f}" height="28" fill="#4cc2b0" stroke="#1c2430"/></g>')
        if (b - a) * k > 14:
            out.append(f'<text x="{10 + a * k + 4:.1f}" y="{y0 + 18}" font-size="10" fill="#fff">{e}</text>')
    cs, ce = model.exons_rel[0][0], model.exons_rel[-1][1]
    out.append(f'<polygon points="{10 + cs * k:.1f},{y0 + 34} {5 + cs * k:.1f},{y0 + 44} {15 + cs * k:.1f},{y0 + 44}" fill="#2ea66b"/>'
               f'<rect x="{6 + ce * k:.1f}" y="{y0 + 34}" width="8" height="8" fill="#e06c6c"/>'
               f'<text x="10" y="{y0 + 58}" font-size="9" fill="#5b6675">▲ ATG · ■ parada · caixas = éxons · ângulos = íntrons (numerados)</text>')
    yd = y0 + 70
    for d in domains or []:
        if d.get("kind") != "pks" or d["end"] <= d["start"]:
            continue
        a, b = model.aa_span_rel(d["start"], d["end"])
        c = domain_hex(d["name"])
        out.append(f'<g><title>{html.escape(d["name"])} · aa {d["start"]}–{d["end"]}</title><rect x="{10 + a * k:.1f}" y="{yd}" width="{max(3, (b - a) * k):.1f}" height="18" fill="{c}" stroke="#1c2430" opacity=".9"/></g>'
                   f'<text x="{10 + a * k + 2:.1f}" y="{yd + 13}" font-size="9" font-weight="bold" fill="{_text_color(c)}">{html.escape(display_name(d["name"])) if (b - a) * k > 18 else ""}</text>')
    h = yd + 30
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {h}" width="100%" style="background:#fff;max-width:{width}px">{"".join(out)}</svg>'
