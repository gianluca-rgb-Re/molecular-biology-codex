"""Leitura de resultados do antiSMASH (GenBank de região/genoma), GenBank do Funannotate/NCBI e FASTA.

NÃO há API do Geneious Prime: a integração é por arquivos (GenBank/FASTA), que o Geneious importa e exporta.
Validado com um GenBank real do antiSMASH 8 (região T1PKS, anotação Funannotate) e com arquivos sintéticos nos testes.
"""
from __future__ import annotations
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .genemodel import revcomp

GENE_KINDS = {"biosynthetic": "Biossintético (núcleo)", "biosynthetic-additional": "Biossintético (adicional)",
              "transport": "Transporte", "regulatory": "Regulador", "resistance": "Resistência", "other": "Outro"}
CLASS_COLORS = {
    "PKS": "#d9534f", "NRPS": "#9b59b6", "PKS-NRPS": "#e07a5f", "NRPS-like": "#b47fd0", "Terpeno": "#2ea66b", "RiPP": "#3fb0c9",
    "Biossintético": "#e0a458", "Auxiliar": "#e67e9c", "Transporte": "#4a90d9", "Regulador": "#6fcf6f",
    "Resistência": "#c9a227", "Outro": "#8a95a5",
}
DOMAIN_COLORS = {"KS": "#d9534f", "AT": "#e0a458", "ACP": "#4a90d9", "DH": "#2ea66b", "ER": "#3fb0c9", "KR": "#9b59b6",
                 "MT": "#e67e9c", "SAT": "#c9a227", "PT": "#8e9aaf", "TE": "#6fcf6f", "C": "#7a8fd9", "A": "#e07a5f",
                 "T": "#4cc2b0", "R": "#c792ea", "p450": "#b0703c"}
CORE_CLASSES = ("PKS", "NRPS", "PKS-NRPS", "NRPS-like", "Terpeno")

# IDs Pfam usados na triagem de genomas não processados pelo antiSMASH (anotação do Funannotate/InterPro)
PFAM_ROLES = {
    "PF00109": "KS", "PF02801": "KS", "PF00698": "AT", "PF14765": "DH", "PF08659": "KR", "PF00550": "ACP", "PF08242": "MT",
    "PF13602": "ER", "PF00107": "ER", "PF00501": "A", "PF00668": "C", "PF03936": "TS", "PF01397": "TS", "PF19086": "TS",
}
PRODUCT_WORDS = (("polyketide synthase", "PKS"), ("polyketide synthetase", "PKS"), ("nonribosomal peptide synthetase", "NRPS"),
                 ("non-ribosomal peptide synthetase", "NRPS"), ("nrps", "NRPS"), ("beta-ketoacyl synthase", "PKS"),
                 ("terpene synthase", "Terpeno"), ("terpene cyclase", "Terpeno"))


@dataclass
class ParsedGene:
    locus_tag: str
    product: str
    kind: str
    gene_class: str
    contig: str
    start: int                     # 0-based, coordenadas locais do registro
    end: int
    strand: int
    protein: str = ""
    domains: list[dict] = field(default_factory=list)   # name, short, start, end (aa), tool, kind, evalue, score, notes
    parts: list[list[int]] = field(default_factory=list)  # éxons [início, fim] 1-based locais, em ordem de transcrição
    genomic_nt: str = ""           # gene orientado 5′→3′, com íntrons
    offset: int = 0                # local + offset = coordenada no scaffold original
    scaffold: str = ""
    codon_start: int = 1
    meta: dict = field(default_factory=dict)


@dataclass
class RecordInfo:
    organism: str = ""
    strain: str = ""
    taxonomy: str = ""
    accession: str = ""
    antismash_version: str = ""
    orig_start: int = 0
    orig_end: int = 0
    length: int = 0
    annotator: str = ""


@dataclass
class ParsedBGC:
    name: str
    contig: str
    start: int
    end: int
    products: list[str]
    contig_edge: bool
    genes: list[ParsedGene]
    meta: dict = field(default_factory=dict)
    info: RecordInfo = field(default_factory=RecordInfo)


def display_name(name: str) -> str:
    """Nome de exibição: remove só o prefixo «PKS_» (PKS_KS → KS). O identificador ORIGINAL permanece nos dados e arquivos."""
    return name[4:] if name.startswith("PKS_") and len(name) > 4 else name


def short_domain(name: str) -> str:
    """Siglas curtas para domínios do antiSMASH (PKS_KS → KS, PKS_PP → ACP, Condensation_LCL → C...)."""
    n = name.replace("PKS_", "").replace("NRPS-", "")
    table = (("KS", "KS"), ("AT", "AT"), ("ACP", "ACP"), ("PP-binding", "ACP"), ("PP", "ACP"), ("DH", "DH"), ("ER", "ER"),
             ("KR", "KR"), ("cMT", "MT"), ("nMT", "MT"), ("oMT", "MT"), ("Methyltransf", "MT"), ("MT", "MT"), ("SAT", "SAT"),
             ("PT", "PT"), ("TE", "TE"), ("Thioesterase", "TE"), ("Condensation", "C"), ("AMP-binding", "A"), ("AMP_binding", "A"),
             ("A-OX", "A"), ("PCP", "T"), ("Thioester-redct", "R"), ("Terpene", "TS"), ("p450", "p450"))
    for key, out in table:
        if n.upper().startswith(key.upper()):
            return out
    return n[:10]


def classify_gene(kind: str, domain_names: list[str], product: str, region_products: list[str]) -> str:
    names = [d.upper() for d in domain_names]
    has_ks = any(x.startswith("PKS_KS") or x == "KS" for x in names)
    has_at = any(x.startswith("PKS_AT") or x == "AT" for x in names)
    has_pks = has_ks and has_at or (has_ks and any("PKS" in x for x in names))
    has_nrps = any(x.startswith("CONDENSATION") or x.startswith("AMP-BINDING") or x.startswith("AMP_BINDING") for x in names)
    if has_pks and has_nrps:
        return "PKS-NRPS"
    if has_pks:
        return "PKS"
    if has_nrps:
        return "NRPS"
    if any("TERPENE" in x for x in names) or "terpene" in product.lower():
        return "Terpeno"
    return {"biosynthetic": "Biossintético", "biosynthetic-additional": "Auxiliar", "transport": "Transporte",
            "regulatory": "Regulador", "resistance": "Resistência"}.get(kind, "Outro")


def _q(feature, key: str, default: str = "") -> str:
    v = feature.qualifiers.get(key)
    return str(v[0]) if v else default


def _ql(feature, key: str) -> list[str]:
    return [str(x) for x in feature.qualifiers.get(key, [])]


def _protein(rec, feat) -> str:
    tr = _q(feat, "translation")
    if tr:
        return tr.replace(" ", "").replace("\n", "")
    try:
        return str(feat.extract(rec.seq).translate(table=1, to_stop=True))
    except Exception:  # noqa: BLE001
        return ""


def _record_info(rec) -> RecordInfo:
    comment = str(rec.annotations.get("comment", ""))
    desc = rec.description or ""
    m = re.search(r"strain\s+([\w\-\.]+?)\.?$", desc.strip()) or re.search(r"strain\s+([\w\-\.]+)", desc)
    src = next((f for f in rec.features if f.type == "source"), None)
    strain = (m.group(1).rstrip(".") if m else "") or (_q(src, "strain") if src else "")
    org = rec.annotations.get("organism", "") or (_q(src, "organism") if src else "")
    sc = (rec.annotations.get("structured_comment") or {}).get("antiSMASH-Data", {}) or {}
    get = lambda k, rx: str(sc.get(k) or "") or (re.search(rx, comment).group(1) if re.search(rx, comment) else "")  # noqa: E731
    os_ = get("Orig. start", r"Orig\. start\s*::\s*(\d+)")
    oe = get("Orig. end", r"Orig\. end\s*::\s*(\d+)")
    ver = get("Version", r"Version\s*::\s*(\S+)")
    ann = re.search(r"Annotated using ([^'\n]+)", comment)
    return RecordInfo(org if org != "." else "", strain, "; ".join(rec.annotations.get("taxonomy", [])), rec.id,
                      ver, int(os_) if os_.isdigit() else 0, int(oe) if oe.isdigit() else 0, len(rec.seq),
                      ann.group(1).strip() if ann else "")


def _domain_dict(df) -> dict | None:
    ps, pe = _q(df, "protein_start"), _q(df, "protein_end")
    if not (ps and pe):
        return None
    name = _q(df, "aSDomain") or _q(df, "label") or df.type
    tool = _q(df, "aSTool", "")
    kind = "pks" if tool == "nrps_pks_domains" else ("tigr" if tool == "tigrfam" else (
        "pfam" if df.type == "PFAM_domain" or tool in ("clusterhmmer", "pfam") else "other"))
    notes = _ql(df, "ASF") + _ql(df, "specificity") + ([f"subtipo: {_q(df, 'domain_subtypes')}"] if _q(df, "domain_subtypes") else [])
    desc = _q(df, "description")
    return {"name": name, "short": short_domain(name) if kind == "pks" else (desc.split(":")[0][:14] or name[:14]),
            "start": int(ps), "end": int(pe), "tool": tool, "kind": kind, "evalue": _q(df, "evalue"), "score": _q(df, "score"),
            "description": re.sub(r"\s+", " ", desc), "notes": [re.sub(r"\s+", " ", n) for n in notes],
            "id": _q(df, "identifier") or _q(df, "db_xref")}


def _legacy_domain(df, feat) -> dict:
    """Formato antigo/sintético: sem protein_start; calcula a partir das coordenadas em nt."""
    ds, de, fs, fe = int(df.location.start), int(df.location.end), int(feat.location.start), int(feat.location.end)
    a, b = ((fe - de) // 3, (fe - ds) // 3) if feat.location.strand == -1 else ((ds - fs) // 3, (de - fs) // 3)
    n = _q(df, "aSDomain")
    return {"name": n, "short": short_domain(n), "start": max(0, a), "end": max(a + 1, b), "tool": "nrps_pks_domains",
            "kind": "pks", "evalue": "", "score": "", "description": "", "notes": [], "id": ""}


def _gene_from_cds(rec, feat, dom_by_locus, mrna_by_locus, region_products, info, modules) -> ParsedGene:
    tag = _q(feat, "locus_tag") or _q(feat, "gene") or _q(feat, "protein_id") or f"CDS_{int(feat.location.start)}"
    kind = _q(feat, "gene_kind", "other")
    doms: list[dict] = []
    for df in dom_by_locus.get(tag, []):
        d = _domain_dict(df)
        if d is None and df.type == "aSDomain" and _q(df, "aSDomain"):
            d = _legacy_domain(df, feat)
        if d:
            doms.append(d)
    if not doms:
        for sd in feat.qualifiers.get("sec_met_domain", []):
            n = str(sd).split(" (")[0]
            doms.append({"name": n, "short": short_domain(n), "start": 0, "end": 0, "tool": "rule-based-clusters", "kind": "pks",
                         "evalue": "", "score": "", "description": "", "notes": [], "id": ""})
    doms.sort(key=lambda d: (d["start"], d["end"]))
    product = _q(feat, "product", "proteína hipotética")
    gs, ge = int(feat.location.start), int(feat.location.end)
    strand = feat.location.strand or 1
    genomic = str(rec.seq[gs:ge]).upper()
    if strand == -1:
        genomic = revcomp(genomic)
    parts = [[int(p.start) + 1, int(p.end)] for p in feat.location.parts]
    meta = {"gene_functions": [re.sub(r"\s+", " ", x) for x in _ql(feat, "gene_functions")],
            "sec_met_domain": [re.sub(r"\s+", " ", x) for x in _ql(feat, "sec_met_domain")],
            "note": _ql(feat, "note"), "protein_id": _q(feat, "protein_id"), "db_xref": _ql(feat, "db_xref")}
    mrna = mrna_by_locus.get(tag)
    if mrna is not None:
        mp = [[int(p.start) + 1, int(p.end)] for p in mrna.location.parts]
        if sorted(mp) != sorted(parts):
            meta["mrna_parts"] = mp
    if tag in modules:
        meta["module"] = modules[tag]
    names = [d["name"] for d in doms]
    offset = max(0, info.orig_start - 1) if info.orig_start else 0
    return ParsedGene(tag, product, kind, classify_gene(kind, names, product, region_products), rec.id, gs, ge, strand,
                      _protein(rec, feat), doms, parts, genomic, offset, rec.id, int(_q(feat, "codon_start", "1") or 1), meta)


def _index_features(rec):
    dom: dict[str, list] = {}
    mrna: dict[str, object] = {}
    modules: dict[str, dict] = {}
    for f in rec.features:
        if f.type in ("aSDomain", "PFAM_domain"):
            dom.setdefault(_q(f, "locus_tag"), []).append(f)
        elif f.type == "mRNA":
            mrna[_q(f, "locus_tag")] = f
        elif f.type == "aSModule":
            info = {"type": _q(f, "type"), "iterative": "iterative" in f.qualifiers, "complete": "complete" in f.qualifiers,
                    "incomplete": "incomplete" in f.qualifiers, "monomer_pairings": _ql(f, "monomer_pairings"),
                    "domains": [re.sub(r"^.*_(?=[^_]+\.\d+$)", "", d) for d in _ql(f, "domains")]}
            for t in _ql(f, "locus_tags"):
                modules[t] = info
    return dom, mrna, modules


def parse_genbank(path: str | Path, progress: Callable[[str], None] | None = None) -> list[ParsedBGC]:
    """GenBank do antiSMASH → lista de BGCs (regiões) com genes, domínios, éxons e sequências."""
    from Bio import SeqIO
    out: list[ParsedBGC] = []
    for rec in SeqIO.parse(str(path), "genbank"):
        if progress:
            progress(rec.id)
        regions = [f for f in rec.features if f.type == "region"]
        if not regions:
            continue
        info = _record_info(rec)
        dom, mrna, modules = _index_features(rec)
        cds = [f for f in rec.features if f.type == "CDS"]
        cand = [f for f in rec.features if f.type == "cand_cluster"]
        cores = [f for f in rec.features if f.type == "proto_core"]
        protos = [f for f in rec.features if f.type == "protocluster"]
        offset = max(0, info.orig_start - 1) if info.orig_start else 0
        for r in regions:
            rs, re_ = int(r.location.start), int(r.location.end)
            products = [str(p) for p in r.qualifiers.get("product", [])]
            num = _q(r, "region_number", str(len(out) + 1))
            inside = lambda f: int(f.location.start) >= rs and int(f.location.end) <= re_  # noqa: E731
            genes = sorted((_gene_from_cds(rec, c, dom, mrna, products, info, modules) for c in cds if inside(c)), key=lambda g: g.start)
            c0 = next((c for c in cand if inside(c)), None)
            meta = {"rules": re.sub(r"\s+", " ", _q(r, "rules")), "region_number": num, "scaffold": rec.id, "offset": offset,
                    "kind": _q(c0, "kind") if c0 else "", "smiles": _q(c0, "SMILES") if c0 else "",
                    "cores": [[int(p.location.start) + 1, int(p.location.end), p.location.strand or 1, _q(p, "product")] for p in cores if inside(p)],
                    "category": next((_q(p, "category") for p in protos if inside(p)), ""),
                    "antismash_version": info.antismash_version, "orig_start": info.orig_start, "orig_end": info.orig_end,
                    "annotator": info.annotator, "length": re_ - rs}
            name = f"{rec.id}.region{int(num):03d}" if num.isdigit() else f"{rec.id}.region{num}"
            out.append(ParsedBGC(name, rec.id, rs, re_, products, _q(r, "contig_edge").lower() == "true", genes, meta, info))
    return out


def record_info(path: str | Path) -> RecordInfo:
    from Bio import SeqIO
    for rec in SeqIO.parse(str(path), "genbank"):
        return _record_info(rec)
    return RecordInfo()


def _pfam_ids(feat) -> set[str]:
    ids = set()
    for x in feat.qualifiers.get("db_xref", []):
        ids.update(re.findall(r"(PF\d{5})", str(x)))
    for x in feat.qualifiers.get("note", []):
        ids.update(re.findall(r"(PF\d{5})", str(x)))
    return ids


def screen_genome(path: str | Path, progress: Callable[[str], None] | None = None) -> tuple[list[ParsedGene], RecordInfo, int]:
    """Triagem de genoma NÃO processado pelo antiSMASH, por anotação Pfam (db_xref) ou texto do produto.

    É uma HEURÍSTICA baseada na anotação existente no arquivo; o antiSMASH (domínios, regras e vizinhança) é a referência.
    """
    from Bio import SeqIO
    found: list[ParsedGene] = []
    first: RecordInfo | None = None
    n_cds = 0
    for rec in SeqIO.parse(str(path), "genbank"):
        if progress:
            progress(rec.id)
        info = _record_info(rec)
        first = first or info
        mrna = {_q(f, "locus_tag"): f for f in rec.features if f.type == "mRNA"}
        for f in rec.features:
            if f.type != "CDS":
                continue
            n_cds += 1
            roles = {PFAM_ROLES[i] for i in _pfam_ids(f) if i in PFAM_ROLES}
            word = next((c for w, c in PRODUCT_WORDS if w in _q(f, "product", "").lower()), "")
            has_pks, has_nrps = "KS" in roles and "AT" in roles, "A" in roles and "C" in roles
            cls = ("PKS-NRPS" if has_pks and has_nrps else "PKS" if has_pks else "NRPS" if has_nrps else
                   "NRPS-like" if "A" in roles else "Terpeno" if "TS" in roles else word)
            if not cls:
                continue
            g = _gene_from_cds(rec, f, {}, mrna, [], info, {})
            g.gene_class, g.kind = cls, "biosynthetic"
            g.domains = [{"name": r, "short": r, "start": 0, "end": 0, "tool": "Pfam (db_xref)", "kind": "pfam", "evalue": "", "score": "",
                          "description": "inferido do ID Pfam no arquivo; sem coordenadas", "notes": [], "id": ""} for r in sorted(roles)]
            g.meta["screen"] = "Pfam" if roles else "texto do produto"
            found.append(g)
    return found, first or RecordInfo(), n_cds


def find_gene(path: str | Path, locus_tag: str, flank: int = 8) -> tuple[ParsedBGC | None, str]:
    """Procura um gene por locus_tag em qualquer GenBank e devolve a vizinhança ±flank genes."""
    from Bio import SeqIO
    want = locus_tag.strip().lower()
    for rec in SeqIO.parse(str(path), "genbank"):
        cds = sorted((f for f in rec.features if f.type == "CDS"), key=lambda f: int(f.location.start))
        for i, c in enumerate(cds):
            tags = [str(x).lower() for k in ("locus_tag", "gene", "old_locus_tag", "protein_id") for x in c.qualifiers.get(k, [])]
            if want in tags:
                info = _record_info(rec)
                dom, mrna, modules = _index_features(rec)
                lo, hi = max(0, i - flank), min(len(cds), i + flank + 1)
                genes = [_gene_from_cds(rec, f, dom, mrna, [], info, modules) for f in cds[lo:hi]]
                bgc = ParsedBGC(f"Vizinhança de {locus_tag}", rec.id, genes[0].start, genes[-1].end, ["vizinhança"], False, genes,
                                {"scaffold": rec.id, "offset": genes[0].offset, "length": genes[-1].end - genes[0].start}, info)
                return bgc, genes[i - lo].locus_tag
    return None, ""


def read_fasta_proteins(path: str | Path) -> list[tuple[str, str]]:
    from Bio import SeqIO
    return [(r.id, str(r.seq)) for r in SeqIO.parse(str(path), "fasta")]


def to_fasta(tag: str, desc: str, seq: str) -> str:
    return f">{tag} {desc}\n" + "\n".join(seq[i:i + 60] for i in range(0, len(seq), 60)) + "\n"


def antismash_path() -> str | None:
    return shutil.which("antismash")


def build_command(input_file: str, outdir: str, taxon: str = "fungi", fasta: bool = False, cpus: int = 2) -> list[str]:
    """Comando do antiSMASH 6/7/8 para execução local. Para FASTA de fungos é preciso predição de genes (glimmerhmm)."""
    cmd = ["antismash", "--taxon", taxon, "--output-dir", outdir, "--cpus", str(cpus),
           "--cb-general", "--cb-knownclusters", "--cc-mibig", "--output-basename", Path(input_file).stem]
    if fasta:
        cmd += ["--genefinding-tool", "glimmerhmm"]
    cmd.append(input_file)
    return cmd


ANTISMASH_WEB = "https://fungismash.secondarymetabolites.org/"
ANTISMASH_WEB_BACTERIA = "https://antismash.secondarymetabolites.org/"
