"""Genoteca: coleção de espécies, genes e BGCs com registro de evidências (estilo «dex»)."""
from __future__ import annotations
import json
from typing import Any

from .antismash import ParsedBGC, ParsedGene
from .db import UserDB, now

STAGES = [
    (0, "Predito", "Gene previsto por software (inferência computacional)", "#8a95a5"),
    (1, "Transcrito", "RNA detectado (RT-qPCR, RNA-seq…)", "#4a90d9"),
    (2, "Proteína", "Proteína detectada (Western, MS)", "#4cc2b0"),
    (3, "Atividade", "Atividade enzimática demonstrada", "#e0a458"),
    (4, "Produto", "Produto químico detectado (LC-MS)", "#e07a5f"),
    (5, "Identidade", "Identidade do produto confirmada (padrão/RMN)", "#6fcf6f"),
]


def add_species(db: UserDB, name: str, strain: str = "", accession: str = "", genome_file: str = "",
                taxonomy: str = "", notes: str = "") -> int:
    cur = db.con.execute("INSERT INTO species(name,strain,genome_accession,genome_file,taxonomy,notes,created) VALUES(?,?,?,?,?,?,?)",
                         (name.strip(), strain, accession, genome_file, taxonomy, notes, now()))
    db.con.commit()
    return int(cur.lastrowid)


def update_species(db: UserDB, sid: int, **fields: Any) -> None:
    allowed = {"name", "strain", "genome_accession", "genome_file", "taxonomy", "notes"}
    for k, v in fields.items():
        if k in allowed:
            db.con.execute(f"UPDATE species SET {k}=? WHERE id=?", (v, sid))
    db.con.commit()


def delete_species(db: UserDB, sid: int) -> None:
    for t in ("evidence",):
        db.con.execute(f"DELETE FROM {t} WHERE gene_id IN (SELECT id FROM genes WHERE species_id=?)", (sid,))
    db.con.execute("DELETE FROM genes WHERE species_id=?", (sid,))
    db.con.execute("DELETE FROM bgcs WHERE species_id=?", (sid,))
    db.con.execute("DELETE FROM species WHERE id=?", (sid,))
    db.con.commit()


def species_list(db: UserDB):
    return list(db.con.execute("SELECT * FROM species ORDER BY name"))


def add_gene(db: UserDB, species_id: int, g: ParsedGene, bgc_id: int | None = None, commit: bool = True) -> int:
    row = db.con.execute("SELECT id FROM genes WHERE species_id=? AND locus_tag=?", (species_id, g.locus_tag)).fetchone()
    vals = (g.product, g.gene_class, g.kind, g.contig, g.start, g.end, g.strand, g.protein, json.dumps(g.domains),
            json.dumps(g.parts), g.genomic_nt, g.offset, g.scaffold, g.codon_start, json.dumps(g.meta))
    if row:
        gid = int(row["id"])
        db.con.execute("UPDATE genes SET bgc_id=COALESCE(?,bgc_id), product=?, gene_class=?, kind=?, contig=?, start=?, end=?, strand=?, "
                       "protein=?, domains=?, parts=?, genomic_nt=?, offset=?, scaffold=?, codon_start=?, meta=? WHERE id=?", (bgc_id,) + vals + (gid,))
    else:
        cur = db.con.execute(
            "INSERT INTO genes(species_id,bgc_id,locus_tag,created,product,gene_class,kind,contig,start,end,strand,protein,domains,"
            "parts,genomic_nt,offset,scaffold,codon_start,meta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (species_id, bgc_id, g.locus_tag, now()) + vals)
        gid = int(cur.lastrowid)
        record_evidence(db, gid, 0, "Importado/previsto", "importação", commit=False)
    if commit:
        db.con.commit()
    return gid


def add_manual_gene(db: UserDB, species_id: int, locus_tag: str, product: str = "", gene_class: str = "Outro", notes: str = "") -> int:
    gid = add_gene(db, species_id, ParsedGene(locus_tag, product or "a determinar", "other", gene_class, "", 0, 0, 1))
    if notes:
        db.con.execute("UPDATE genes SET notes=? WHERE id=?", (notes, gid))
        db.con.commit()
    return gid


def add_bgc(db: UserDB, species_id: int, b: ParsedBGC, source: str, source_file: str, with_genes: bool = True) -> int:
    row = db.con.execute("SELECT id FROM bgcs WHERE species_id=? AND name=?", (species_id, b.name)).fetchone()
    if row:
        bid = int(row["id"])
    else:
        cur = db.con.execute("INSERT INTO bgcs(species_id,name,contig,start,end,products,source,source_file,created,contig_edge,meta) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                             (species_id, b.name, b.contig, b.start, b.end, ",".join(b.products), source, source_file, now(), int(b.contig_edge),
                              json.dumps(b.meta)))
        bid = int(cur.lastrowid)
    db.con.commit()
    if with_genes:
        for g in b.genes:
            add_gene(db, species_id, g, bid, commit=False)
        db.con.commit()
    return bid


def genes_of_species(db: UserDB, sid: int | None = None, only_core: bool = False):
    q = "SELECT * FROM genes" + (" WHERE species_id=?" if sid else "")
    rows = list(db.con.execute(q + " ORDER BY species_id, contig, start", (sid,) if sid else ()))
    return [r for r in rows if not only_core or r["kind"] in ("biosynthetic",) or r["gene_class"] in ("PKS", "NRPS", "PKS-NRPS", "Terpeno")]


def bgcs_of_species(db: UserDB, sid: int):
    return list(db.con.execute("SELECT * FROM bgcs WHERE species_id=? ORDER BY contig, start", (sid,)))


def genes_of_bgc(db: UserDB, bid: int):
    return list(db.con.execute("SELECT * FROM genes WHERE bgc_id=? ORDER BY start", (bid,)))


def record_evidence(db: UserDB, gene_id: int, stage: int, note: str = "", source: str = "", commit: bool = True) -> None:
    db.con.execute("INSERT INTO evidence(gene_id,stage,note,source,ts) VALUES(?,?,?,?,?) ON CONFLICT(gene_id,stage) "
                   "DO UPDATE SET note=excluded.note, source=excluded.source, ts=excluded.ts", (gene_id, stage, note, source, now()))
    if commit:
        db.con.commit()


def remove_evidence(db: UserDB, gene_id: int, stage: int) -> None:
    if stage == 0:
        return
    db.con.execute("DELETE FROM evidence WHERE gene_id=? AND stage=?", (gene_id, stage))
    db.con.commit()


def evidence_of(db: UserDB, gene_id: int) -> dict[int, Any]:
    return {r["stage"]: r for r in db.con.execute("SELECT * FROM evidence WHERE gene_id=?", (gene_id,))}


def top_stage(db: UserDB, gene_id: int) -> int:
    ev = evidence_of(db, gene_id)
    return max(ev) if ev else 0


def update_gene_notes(db: UserDB, gid: int, notes: str) -> None:
    db.con.execute("UPDATE genes SET notes=? WHERE id=?", (notes, gid))
    db.con.commit()


def summary(db: UserDB) -> dict[str, int]:
    r = db.con
    return {"species": r.execute("SELECT COUNT(*) FROM species").fetchone()[0],
            "genes": r.execute("SELECT COUNT(*) FROM genes").fetchone()[0],
            "bgcs": r.execute("SELECT COUNT(*) FROM bgcs").fetchone()[0],
            "stages": r.execute("SELECT COUNT(*) FROM evidence WHERE stage>0").fetchone()[0]}


def delete_gene(db: UserDB, gid: int) -> None:
    db.con.execute("DELETE FROM evidence WHERE gene_id=?", (gid,))
    db.con.execute("DELETE FROM genes WHERE id=?", (gid,))
    db.con.commit()


def get_gene(db: UserDB, gid: int):
    return db.con.execute("SELECT * FROM genes WHERE id=?", (gid,)).fetchone()


def get_species(db: UserDB, sid: int):
    return db.con.execute("SELECT * FROM species WHERE id=?", (sid,)).fetchone()


def get_bgc(db: UserDB, bid: int):
    return db.con.execute("SELECT * FROM bgcs WHERE id=?", (bid,)).fetchone()


def seed_project_case(db: UserDB) -> int:
    """Cria a entrada do projeto (identificadores informados pelo usuário; nenhum dado experimental)."""
    row = db.con.execute("SELECT id FROM species WHERE name=?", ("Rickiella edulis",)).fetchone()
    sid = int(row["id"]) if row else add_species(db, "Rickiella edulis", notes="Espécie do projeto aplicado (dado do projeto).")
    gid = add_manual_gene(db, sid, "RICKED_008071", "PKS candidata (dado do projeto)", "PKS",
                          "Identificador informado pelo usuário. Nenhuma sequência, expressão ou produto foi registrado ainda.")
    return gid


# ----------------------------------------------------------- modelo gênico
def model_for_gene(row, use_user: bool = True):
    """Constrói o GeneModel de um gene gravado (None se não houver sequência genômica/éxons)."""
    from .genemodel import GeneModel
    if not row["genomic_nt"] or not row["parts"]:
        return None
    parts = json.loads(row["user_parts"]) if (use_user and row["user_parts"]) else json.loads(row["parts"])
    m = GeneModel(row["genomic_nt"], [], row["strand"] or 1, row["start"], row["end"], row["offset"] or 0, row["scaffold"] or row["contig"] or "",
                  row["codon_start"] or 1, 1, row["protein"] or "", row["locus_tag"])
    return m.with_exons_local([(a, b) for a, b in parts])


def save_user_model(db: UserDB, gid: int, local_exons: list[tuple[int, int]] | None) -> None:
    db.con.execute("UPDATE genes SET user_parts=? WHERE id=?", (json.dumps([list(e) for e in local_exons]) if local_exons else None, gid))
    db.con.commit()


def gene_meta(row) -> dict:
    try:
        return json.loads(row["meta"] or "{}")
    except Exception:  # noqa: BLE001
        return {}


def bgc_meta(row) -> dict:
    try:
        return json.loads(row["meta"] or "{}")
    except Exception:  # noqa: BLE001
        return {}


def ensure_species_from_info(db: UserDB, info, source_file: str = "") -> int | None:
    """Cria/encontra a espécie a partir dos metadados do GenBank (organismo, linhagem, taxonomia)."""
    if not info.organism:
        return None
    row = db.con.execute("SELECT * FROM species WHERE name=? AND COALESCE(strain,'')=?", (info.organism, info.strain or "")).fetchone() \
        or db.con.execute("SELECT * FROM species WHERE name=?", (info.organism,)).fetchone()
    if row:
        fill = {k: v for k, v in (("strain", info.strain), ("genome_accession", info.accession), ("taxonomy", info.taxonomy),
                                  ("genome_file", source_file)) if v and not row[k]}
        if fill:
            update_species(db, int(row["id"]), **fill)
        return int(row["id"])
    return add_species(db, info.organism, info.strain, info.accession, source_file, info.taxonomy, "Criada automaticamente a partir do GenBank importado.")


def all_core_genes(db: UserDB, sid: int | None = None):
    """Genes-âncora (PKS, NRPS, híbridas, NRPS-like, terpeno), em ordem do genoma."""
    q = "SELECT g.*, b.name AS bgc_name, b.products AS bgc_products, b.contig_edge AS bgc_edge FROM genes g LEFT JOIN bgcs b ON b.id=g.bgc_id " \
        "WHERE g.gene_class IN ('PKS','NRPS','PKS-NRPS','NRPS-like','Terpeno')" + (" AND g.species_id=?" if sid else "") + \
        " ORDER BY g.species_id, g.scaffold, g.offset + g.start"
    return list(db.con.execute(q, (sid,) if sid else ()))


_DOM_DEFAULTS = {"kind": "pks", "tool": "", "evalue": "", "score": "", "description": "", "notes": [], "id": "", "start": 0, "end": 0, "short": "", "name": ""}


def domains_of(row) -> list[dict]:
    """Domínios do gene com campos padrão (compatível com bancos criados por versões anteriores, sem `kind`, `tool` etc.)."""
    try:
        raw = json.loads(row["domains"] or "[]")
    except Exception:  # noqa: BLE001
        return []
    out = []
    for d in raw:
        if not isinstance(d, dict):
            continue
        dd = {**_DOM_DEFAULTS, **d}
        dd["short"] = dd["short"] or str(dd["name"])[:10]
        out.append(dd)
    return out
