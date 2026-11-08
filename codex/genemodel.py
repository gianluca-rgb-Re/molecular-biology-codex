"""Modelo gênico: estrutura éxon/íntron, cDNA (CDS) sem íntrons, proteína, estatísticas e simulações.

Convenções:
- `genomic` é a sequência do gene na orientação 5′→3′ do gene (já reverso-complementada se strand = −1), COM íntrons.
- `exons_rel` são intervalos [a, b) em coordenadas 0-based dessa sequência, ordenados e em ordem de transcrição.
- Coordenadas «locais» são as do registro GenBank importado (1-based, fita direta). Para regiões extraídas de um
  scaffold maior (antiSMASH), `offset` converte para coordenadas do scaffold original: scaffold = local + offset.
"""
from __future__ import annotations
from dataclasses import dataclass, field

STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
COMP = str.maketrans("ACGTacgtNn", "TGCAtgcaNn")
STOPS = {"TAA", "TAG", "TGA"}


def revcomp(s: str) -> str:
    return s.translate(COMP)[::-1]


def translate(cds: str, table: int = 1) -> str:
    from Bio.Seq import Seq
    cds = cds[: len(cds) - len(cds) % 3]
    return str(Seq(cds).translate(table=table))


@dataclass
class Intron:
    index: int
    a: int            # início em coords relativas (0-based)
    b: int            # fim exclusivo
    donor: str        # 2 primeiros nt (5′ splice site)
    acceptor: str     # 2 últimos nt (3′ splice site)
    phase: int        # 0, 1 ou 2
    cds_pos: int      # posição na CDS (nt) onde o íntron interrompe

    @property
    def length(self) -> int:
        return self.b - self.a

    @property
    def class_(self) -> str:
        pair = f"{self.donor}-{self.acceptor}".upper()
        return {"GT-AG": "canônico GT–AG", "GC-AG": "GC–AG (minoritário)", "AT-AC": "AT–AC (U12)"}.get(pair, f"atípico {pair}")

    @property
    def canonical(self) -> bool:
        return f"{self.donor}-{self.acceptor}".upper() == "GT-AG"


@dataclass
class GeneModel:
    genomic: str
    exons_rel: list[tuple[int, int]]
    strand: int = 1
    gstart: int = 0                 # 0-based local, início do gene (menor coordenada)
    gend: int = 0                   # exclusivo
    offset: int = 0
    scaffold: str = ""
    codon_start: int = 1
    table: int = 1
    stored_protein: str = ""
    label: str = ""

    def __post_init__(self) -> None:
        self.exons_rel = sorted((int(a), int(b)) for a, b in self.exons_rel)
        if not self.gend:
            self.gend = self.gstart + len(self.genomic)

    # ----------------------------------------------------------- estrutura
    def introns(self) -> list[Intron]:
        out, cum = [], 0
        for i in range(len(self.exons_rel) - 1):
            a, b = self.exons_rel[i][1], self.exons_rel[i + 1][0]
            cum += self.exons_rel[i][1] - self.exons_rel[i][0]
            seq = self.genomic[a:b].upper()
            out.append(Intron(i + 1, a, b, seq[:2], seq[-2:], (cum - (self.codon_start - 1)) % 3, cum))
        return out

    def cds(self) -> str:
        return "".join(self.genomic[a:b] for a, b in self.exons_rel).upper()

    def coding_seq(self) -> str:
        return self.cds()[self.codon_start - 1:]

    def protein(self) -> str:
        p = translate(self.coding_seq(), self.table)
        return p[: p.index("*")] if "*" in p else p

    def full_translation(self) -> str:
        return translate(self.coding_seq(), self.table)

    def checks(self) -> dict:
        c = self.coding_seq()
        full = self.full_translation()
        body = full[:-1] if full.endswith("*") else full
        internal = body.count("*")
        return {
            "frame_multiple_3": len(c) % 3 == 0,
            "start_ATG": c[:3] == "ATG",
            "stop_codon": c[-3:] in STOPS,
            "internal_stops": internal,
            "matches_stored": (self.stored_protein.rstrip("*") == self.protein()) if self.stored_protein else None,
            "canonical_introns": sum(1 for i in self.introns() if i.canonical),
            "n_introns": len(self.exons_rel) - 1,
        }

    # -------------------------------------------------------- coordenadas
    def rel_to_local(self, a: int, b: int) -> tuple[int, int]:
        """[a,b) relativo → (início, fim) locais 1-based inclusivos, na fita direta."""
        if self.strand == -1:
            return self.gend - b + 1, self.gend - a
        return self.gstart + a + 1, self.gstart + b

    def local_to_rel(self, s: int, e: int) -> tuple[int, int]:
        if self.strand == -1:
            return self.gend - e, self.gend - (s - 1)
        return s - 1 - self.gstart, e - self.gstart

    def to_scaffold(self, s: int, e: int) -> tuple[int, int]:
        return s + self.offset, e + self.offset

    def exon_table(self) -> list[dict]:
        rows, cum = [], 0
        for i, (a, b) in enumerate(self.exons_rel, 1):
            s, e = self.rel_to_local(a, b)
            ss, se = self.to_scaffold(s, e)
            rows.append({"n": i, "len": b - a, "local": (s, e), "scaffold": (ss, se), "cds_from": cum + 1, "cds_to": cum + b - a,
                         "aa_from": cum // 3 + 1, "aa_to": (cum + b - a) // 3})
            cum += b - a
        return rows

    def cds_to_rel(self, cds_pos: int) -> int:
        """Posição 0-based na CDS espliçada → posição 0-based na sequência genômica orientada."""
        cum = 0
        for a, b in self.exons_rel:
            if cds_pos < cum + (b - a):
                return a + (cds_pos - cum)
            cum += b - a
        return self.exons_rel[-1][1] - 1

    def aa_span_rel(self, aa_start: int, aa_end: int) -> tuple[int, int]:
        """Intervalo genômico [a,b) que cobre os aminoácidos aa_start..aa_end (1-based)."""
        s0 = (aa_start - 1) * 3 + (self.codon_start - 1)
        e0 = aa_end * 3 + (self.codon_start - 1) - 1
        return self.cds_to_rel(s0), self.cds_to_rel(e0) + 1

    def exon_of_aa(self, aa: int) -> int:
        """Éxon (1-based) que contém o primeiro nt do códon do aminoácido `aa` (1-based)."""
        pos = (aa - 1) * 3 + (self.codon_start - 1)
        cum = 0
        for i, (a, b) in enumerate(self.exons_rel, 1):
            cum += b - a
            if pos < cum:
                return i
        return len(self.exons_rel)

    # ----------------------------------------------------- estatísticas
    def stats(self) -> dict:
        cds, prot = self.coding_seq(), self.protein()
        ex_len = [b - a for a, b in self.exons_rel]
        in_len = [i.length for i in self.introns()]
        gc = lambda s: 100 * sum(ch in "GC" for ch in s.upper()) / max(1, len(s))  # noqa: E731
        codons = [cds[i:i + 3] for i in range(0, len(cds) - 2, 3)]
        gc3 = 100 * sum(c[2] in "GC" for c in codons if c not in STOPS) / max(1, sum(1 for c in codons if c not in STOPS))
        s = {
            "aa": len(prot), "cds_nt": len(cds), "genomic_nt": len(self.genomic), "exons": len(ex_len), "introns": len(in_len),
            "intron_total_nt": sum(in_len), "mean_exon": sum(ex_len) / max(1, len(ex_len)),
            "mean_intron": (sum(in_len) / len(in_len)) if in_len else 0, "min_intron": min(in_len, default=0), "max_intron": max(in_len, default=0),
            "introns_per_kb_cds": 1000 * len(in_len) / max(1, len(cds)), "gc_genomic": gc(self.genomic), "gc_cds": gc(cds), "gc3": gc3,
            "strand": "+" if self.strand != -1 else "−",
        }
        clean = "".join(ch for ch in prot if ch in STANDARD_AA)
        s["nonstandard_aa"] = len(prot) - len(clean)
        if clean:
            from Bio.SeqUtils.ProtParam import ProteinAnalysis
            pa = ProteinAnalysis(clean)
            s.update(mw_kda=pa.molecular_weight() / 1000, pi=pa.isoelectric_point(), instability=pa.instability_index(),
                     gravy=pa.gravy(), aromaticity=pa.aromaticity(), composition=pa.count_amino_acids())
        return s

    # ---------------------------------------------------------- simulações
    def with_retained(self, retained: set[int]) -> "GeneModel":
        """Retém íntrons (numerados a partir de 1): éxons vizinhos são fundidos com o íntron."""
        ex = list(self.exons_rel)
        merged = [ex[0]]
        for i in range(1, len(ex)):
            if (i) in retained:
                merged[-1] = (merged[-1][0], ex[i][1])
            else:
                merged.append(ex[i])
        return GeneModel(self.genomic, merged, self.strand, self.gstart, self.gend, self.offset, self.scaffold,
                         self.codon_start, self.table, self.stored_protein, self.label)

    def with_exons_local(self, local: list[tuple[int, int]]) -> "GeneModel":
        rel = [self.local_to_rel(s, e) for s, e in local]
        for a, b in rel:
            if a < 0 or b > len(self.genomic) or b <= a:
                raise ValueError(f"Éxon fora do gene ou inválido: {a}-{b}")
        return GeneModel(self.genomic, rel, self.strand, self.gstart, self.gend, self.offset, self.scaffold,
                         self.codon_start, self.table, self.stored_protein, self.label)

    def exons_local(self) -> list[tuple[int, int]]:
        return [self.rel_to_local(a, b) for a, b in self.exons_rel]


def first_divergence(a: str, b: str) -> int | None:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i + 1
    return None if len(a) == len(b) else min(len(a), len(b)) + 1


def formatted_genomic(model: GeneModel, width: int = 60) -> list[tuple[str, bool]]:
    """Sequência genômica em linhas; devolve (texto, é_éxon) por segmento contínuo — para colorir."""
    mask = [False] * len(model.genomic)
    for a, b in model.exons_rel:
        for i in range(a, b):
            mask[i] = True
    segs, cur, flag = [], "", None
    for ch, m in zip(model.genomic, mask):
        if flag is None or m == flag:
            cur += ch
        else:
            segs.append((cur, flag))
            cur = ch
        flag = m
    if cur:
        segs.append((cur, bool(flag)))
    return segs


def wrap_fasta(tag: str, desc: str, seq: str, width: int = 60) -> str:
    return f">{tag} {desc}\n" + "\n".join(seq[i:i + width] for i in range(0, len(seq), width)) + "\n"
