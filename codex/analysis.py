"""Análise comparativa de genes biossintéticos (PKS/NRPS/terpeno): matriz, arquiteturas, frequências, comparação, auditoria.

Princípios científicos:
- Nomes de domínios = identificadores ORIGINAIS do arquivo (ex.: PKS_KS, MT, Acyl_transf_1). Siglas curtas são só complementares.
- Cada domínio carrega a FONTE (antiSMASH nrps_pks_domains, Pfam, TIGRFAM...). Fontes não são misturadas sem pedido.
- Mantêm-se separados: gene/proteína, tipo de BGC, arquitetura, status do módulo antiSMASH e verificações da CDS.
- «Status do módulo» é a classificação ORIGINAL do antiSMASH e NÃO indica truncamento. Verificações da CDS têm critérios próprios.
"""
from __future__ import annotations
import json
from collections import Counter, OrderedDict
from dataclasses import dataclass, field

from . import genoteca
from .antismash import display_name

CORE_CLASSES = ("PKS", "PKS-NRPS", "NRPS", "NRPS-like", "Terpeno")
SOURCES = OrderedDict([("antismash", "antiSMASH (nrps_pks_domains)"), ("pfam", "Pfam"), ("tigr", "TIGRFAM"), ("all", "Todas as fontes")])
KIND_OF_SOURCE = {"antismash": "pks", "pfam": "pfam", "tigr": "tigr"}


def source_label(d: dict) -> str:
    k, tool = d.get("kind", "pks"), d.get("tool", "")
    if k == "pks":
        return f"antiSMASH ({tool or 'nrps_pks_domains'})"
    if k == "pfam":
        return f"Pfam ({tool})" if tool else "Pfam"
    if k == "tigr":
        return "TIGRFAM"
    return f"outra ({tool})" if tool else "outra"


@dataclass
class Rec:
    id: int = 0
    locus: str = ""
    species: str = ""
    gene_class: str = "Outro"            # inferida a partir dos domínios da PRÓPRIA proteína
    gene_kind: str = ""                  # gene_kind do antiSMASH (biosynthetic, transport...)
    bgc: str = ""
    bgc_types: list[str] = field(default_factory=list)   # tipo(s) do BGC (não é a classe da proteína)
    scaffold: str = ""
    start: int = 0                       # coordenadas do scaffold (1-based)
    end: int = 0
    strand: str = "+"
    aa: int = 0
    exons: int = 0
    introns: int = 0
    product: str = ""
    domains: list[dict] = field(default_factory=list)
    module: dict = field(default_factory=dict)           # classificação original do antiSMASH
    evidence: int = 0
    source: str = ""                     # origem da anotação (antiSMASH / triagem Pfam / manual)
    cds_alerts: list[str] = field(default_factory=list)  # verificações próprias da CDS
    cds_checked: bool = False
    edited: bool = False

    # -- domínios por fonte
    def doms(self, source: str = "antismash") -> list[dict]:
        k = KIND_OF_SOURCE.get(source)
        out, seen = [], set()
        for d in sorted(self.domains, key=lambda d: (d.get("start", 0), d.get("end", 0))):
            if k and d.get("kind") != k:
                continue
            key = (d["name"], d.get("start"), d.get("end"), d.get("kind"))
            if key in seen:
                continue
            seen.add(key)
            out.append(d)
        return out

    def arch(self, source: str = "antismash") -> tuple[str, ...]:
        return tuple(display_name(d["name"]) for d in self.doms(source))

    def arch_str(self, source: str = "antismash") -> str:
        return "–".join(self.arch(source)) or "—"

    @property
    def module_status(self) -> str:
        if self.module.get("complete"):
            return "completo"
        if self.module.get("incomplete"):
            return "incompleto"
        return "—"


def _cds_alerts(row) -> tuple[list[str], bool]:
    m = genoteca.model_for_gene(row)
    if m is None:
        return [], False
    c, al = m.checks(), []
    if not c["frame_multiple_3"]:
        al.append("CDS não múltipla de 3")
    if not c["start_ATG"]:
        al.append("não começa com ATG")
    if not c["stop_codon"]:
        al.append("sem códon de parada")
    if c["internal_stops"]:
        al.append(f"{c['internal_stops']} parada(s) interna(s)")
    if c["n_introns"] and c["canonical_introns"] != c["n_introns"]:
        al.append(f"{c['n_introns'] - c['canonical_introns']} íntron(s) não GT–AG")
    if c["matches_stored"] is False:
        al.append("proteína do modelo ≠ proteína do arquivo")
    return al, True


def load_records(db, species_id: int | None = None, classes: tuple[str, ...] | None = CORE_CLASSES, with_cds: bool = True) -> list[Rec]:
    q = ("SELECT g.*, s.name AS sp_name, b.name AS b_name, b.products AS b_products, b.source AS b_source "
         "FROM genes g JOIN species s ON s.id=g.species_id LEFT JOIN bgcs b ON b.id=g.bgc_id" + (" WHERE g.species_id=?" if species_id else "")
         + " ORDER BY g.species_id, g.scaffold, g.offset + g.start")
    out = []
    for r in db.con.execute(q, (species_id,) if species_id else ()):
        if classes is not None and r["gene_class"] not in classes:
            continue
        meta = genoteca.gene_meta(r)
        try:
            parts = json.loads(r["parts"] or "[]")
        except Exception:  # noqa: BLE001
            parts = []
        off = r["offset"] or 0
        alerts, checked = _cds_alerts(r) if with_cds else ([], False)
        src = (r["b_source"] or "") or (("triagem " + meta["screen"] + " (heurística)") if meta.get("screen") else "manual")
        out.append(Rec(r["id"], r["locus_tag"], r["sp_name"], r["gene_class"], r["kind"] or "", (r["b_name"] or ""),
                       [p for p in (r["b_products"] or "").split(",") if p], r["scaffold"] or r["contig"] or "", (r["start"] or 0) + off + 1,
                       (r["end"] or 0) + off, "+" if (r["strand"] or 1) != -1 else "−", len(r["protein"] or ""), len(parts), max(0, len(parts) - 1),
                       r["product"] or "", genoteca.domains_of(r), meta.get("module", {}), genoteca.top_stage(db, r["id"]), src, alerts, checked,
                       bool(r["user_parts"])))
    return out


def filter_records(recs: list[Rec], gene_class: str | None = None, bgc_type: str | None = None, text: str = "") -> list[Rec]:
    t = text.strip().lower()
    return [r for r in recs if (not gene_class or r.gene_class == gene_class) and (not bgc_type or bgc_type in r.bgc_types)
            and (not t or t in r.locus.lower() or t in r.scaffold.lower() or t in r.arch_str("all").lower())]


# ------------------------------------------------------------------ matriz
def domain_frequency(recs: list[Rec], source: str = "antismash") -> list[dict]:
    """Por domínio: nº de proteínas que o possuem, frequência relativa, nº total de cópias e categoria (universal/compartilhado/exclusivo)."""
    n = len(recs)
    prot, copies = Counter(), Counter()
    for r in recs:
        names = r.arch(source)
        copies.update(names)
        prot.update(set(names))
    rows = []
    for name, k in sorted(prot.items(), key=lambda kv: (-kv[1], kv[0])):
        cat = "universal" if k == n and n > 1 else "exclusivo" if k == 1 else "compartilhado"
        if n == 1:
            cat = "única proteína"
        rows.append({"domain": name, "proteins": k, "freq": k / n if n else 0.0, "copies": copies[name], "category": cat})
    return rows


def matrix(recs: list[Rec], source: str = "antismash") -> tuple[list[str], list[tuple[Rec, list[int]]]]:
    """Colunas = domínios (por frequência); linhas = (proteína, cópias por domínio), ordenadas por arquitetura."""
    cols = [f["domain"] for f in domain_frequency(recs, source)]
    rows = []
    for r in sorted(recs, key=lambda r: (r.arch(source), r.locus)):
        c = Counter(r.arch(source))
        rows.append((r, [c.get(d, 0) for d in cols]))
    return cols, rows


def exclusive_domains(recs: list[Rec], source: str = "antismash") -> dict[str, list[str]]:
    """Domínio exclusivo → lista de loci (domínios presentes em uma única proteína do conjunto)."""
    out: dict[str, list[str]] = {}
    for f in domain_frequency(recs, source):
        if f["proteins"] == 1 and len(recs) > 1:
            out[f["domain"]] = [r.locus for r in recs if f["domain"] in r.arch(source)]
    return out


# ------------------------------------------------------------ arquiteturas
def group_architectures(recs: list[Rec], source: str = "antismash") -> list[dict]:
    """Agrupa proteínas com arquitetura idêntica (mesmos domínios, mesma ordem). Observações = critérios explícitos do app."""
    groups: dict[tuple, list[Rec]] = {}
    for r in recs:
        groups.setdefault(r.arch(source), []).append(r)
    out = []
    for arch, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        notes = []
        if len(groups) > 1 and len(members) == 1:
            notes.append("arquitetura única no conjunto")
        classes = {m.gene_class for m in members}
        if "PKS-NRPS" in classes:
            notes.append("PKS e NRPS na mesma proteína")
        if source == "antismash" and any(a == "KS" for a in arch) and not any(a in ("PP", "ACP") for a in arch):
            notes.append("PP não detectado pelo antiSMASH (ver status do módulo; não implica truncamento)")
        if arch and len(set(arch)) < len(arch):
            notes.append("domínio(s) repetido(s)")
        out.append({"arch": arch, "arch_str": "–".join(arch) or "—", "n": len(members), "loci": [m.locus for m in members], "notes": notes,
                    "members": members})
    return out


def _levenshtein(a: tuple, b: tuple) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def compare(recs: list[Rec], source: str = "antismash") -> dict:
    """Comparação de 2+ proteínas: tabela de atributos e diferenças de arquitetura entre cada par."""
    rows = [{"Gene": r.locus, "Classe (domínios)": r.gene_class, "Tipo de BGC": ",".join(r.bgc_types) or "—", "Aminoácidos": r.aa, "Éxons": r.exons,
             "Domínios": len(r.arch(source)), "Arquitetura": r.arch_str(source), "Status do módulo antiSMASH": r.module_status} for r in recs]
    pairs = []
    for i in range(len(recs)):
        for j in range(i + 1, len(recs)):
            a, b = recs[i].arch(source), recs[j].arch(source)
            sa, sb = set(a), set(b)
            pairs.append({"a": recs[i].locus, "b": recs[j].locus, "shared": sorted(sa & sb), "only_a": sorted(sa - sb), "only_b": sorted(sb - sa),
                          "same_set_different_order": sa == sb and a != b and Counter(a) == Counter(b), "identical": a == b,
                          "edit_distance": _levenshtein(a, b), "aa_diff": recs[i].aa - recs[j].aa})
    common = sorted(set.intersection(*[set(r.arch(source)) for r in recs])) if recs else []
    return {"rows": rows, "pairs": pairs, "common": common}


def class_distribution(recs: list[Rec], by: str = "gene_class") -> list[tuple[str, int]]:
    c: Counter = Counter()
    for r in recs:
        if by == "bgc":
            for t in (r.bgc_types or ["(sem BGC)"]):
                c[t] += 1
        else:
            c[r.gene_class] += 1
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))


# ---------------------------------------------------------------- auditoria
_KEYS = ("ketoacyl", "ks", "acyl_transf", "polyketide", "condensation", "amp-binding", "amp_binding", "terpene", "pks_", "nrps")


def audit(db, species_id: int | None = None) -> dict:
    """Procura genes que a classificação atual pode estar ignorando e inconsistências. São SUGESTÕES para revisão, não conclusões."""
    all_recs = load_records(db, species_id, None, with_cds=True)
    core = [r for r in all_recs if r.gene_class in CORE_CLASSES]
    cand, dup_pos, dup_prot = [], [], []
    for r in all_recs:
        if r.gene_class in CORE_CLASSES:
            continue
        hits = [d for d in r.domains if any(k in (d["name"] + " " + d.get("description", "")).lower() for k in _KEYS)]
        txt = any(k in r.product.lower() for k in ("polyketide", "synthetase", "synthase", "ketoacyl"))
        if hits or txt or r.gene_kind in ("biosynthetic",):
            why = [f"{display_name(d['name'])} [{source_label(d)}]" for d in hits][:4] or (["produto: " + r.product] if txt else ["gene_kind = biosynthetic"])
            cand.append({"locus": r.locus, "class": r.gene_class, "reason": "; ".join(why), "bgc": r.bgc})
    seen_pos, seen_prot = {}, {}
    rows = db.con.execute("SELECT id, locus_tag, species_id, scaffold, offset, start, end, protein FROM genes" + (" WHERE species_id=?" if species_id else ""),
                          (species_id,) if species_id else ()).fetchall()
    for g in rows:
        k = (g["species_id"], g["scaffold"], (g["offset"] or 0) + g["start"], (g["offset"] or 0) + g["end"])
        if g["end"] > g["start"]:
            if k in seen_pos:
                dup_pos.append((seen_pos[k], g["locus_tag"]))
            seen_pos[k] = g["locus_tag"]
        if g["protein"] and len(g["protein"]) > 50:
            if g["protein"] in seen_prot:
                dup_prot.append((seen_prot[g["protein"]], g["locus_tag"]))
            seen_prot[g["protein"]] = g["locus_tag"]
    alerts = [(r.locus, r.cds_alerts) for r in core if r.cds_alerts]
    unchecked = [r.locus for r in core if not r.cds_checked]
    return {"total_genes": len(all_recs), "core": len(core), "candidates_ignored": cand, "duplicate_positions": dup_pos, "duplicate_proteins": dup_prot,
            "cds_alerts": alerts, "cds_unchecked": unchecked}


def retention_effect(model, domains: list[dict], retained: set[int]) -> dict:
    """Efeito in silico da retenção de íntrons (numerados a partir de 1) na proteína e nos domínios antiSMASH."""
    from .genemodel import first_divergence
    new = model.with_retained(retained)
    bp, np_ = model.protein(), new.protein()
    d = first_divergence(bp, np_)
    hit = []
    for dm in domains:
        if dm.get("kind") != "pks" or dm["end"] <= dm["start"] or d is None:
            continue
        state = "perdido" if len(np_) < dm["start"] else "truncado" if len(np_) < dm["end"] else ("alterado" if d <= dm["end"] else "")
        if state:
            hit.append(f"{display_name(dm['name'])} ({dm['start']}–{dm['end']}): {state}")
    ch = new.checks()
    return {"aa_before": len(bp), "aa_after": len(np_), "first_difference": d, "domains_affected": hit, "frame_ok": ch["frame_multiple_3"],
            "has_stop": ch["stop_codon"], "identical": d is None}
