"""Lógica da versão web (sem Streamlit): sessão isolada em memória, importação de GenBank, tabelas e exportações."""
from __future__ import annotations
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codex import analysis, antismash, export, genoteca, htmlreport  # noqa: E402
from codex.db import UserDB  # noqa: E402

MAX_MB = int(os.environ.get("CODEX_MAX_MB", "200"))


class WebSession:
    """Uma sessão = um banco SQLite em memória + um diretório temporário privado (apagado ao limpar). Nada é gravado de forma permanente."""

    def __init__(self) -> None:
        self.db = UserDB(":memory:", check_same_thread=False)
        self.tmp = tempfile.mkdtemp(prefix="codex_")          # permissão 0700; usado só durante a leitura do arquivo
        self.imports: list[dict] = []
        self.version = 0
        self._cache: dict = {}

    def import_bytes(self, name: str, data: bytes) -> dict:
        if len(data) > MAX_MB * 1024 * 1024:
            raise ValueError(f"Arquivo maior que o limite configurado ({MAX_MB} MB). Divida por regiões (*.regionNNN.gbk) ou use a versão desktop/servidor próprio.")
        path = Path(self.tmp) / f"up_{len(self.imports)}.gbk"
        try:
            path.write_bytes(data)
            regions = antismash.parse_genbank(path)
            if regions:
                sid = genoteca.ensure_species_from_info(self.db, regions[0].info, name) or genoteca.add_species(self.db, Path(name).stem)
                for b in regions:
                    genoteca.add_bgc(self.db, sid, b, "antiSMASH", name)
                res = {"file": name, "mode": "antiSMASH", "regions": len(regions), "genes": sum(len(b.genes) for b in regions), "species_id": sid}
            else:
                genes, info, n_cds = antismash.screen_genome(path)
                if not genes:
                    raise ValueError(f"Nenhuma região do antiSMASH nem candidato PKS/NRPS (Pfam/texto) em {n_cds} CDS. Rode o antiSMASH e envie o GenBank do resultado.")
                sid = genoteca.ensure_species_from_info(self.db, info, name) or genoteca.add_species(self.db, Path(name).stem)
                for g in genes:
                    genoteca.add_gene(self.db, sid, g, None, commit=False)
                self.db.con.commit()
                res = {"file": name, "mode": "triagem Pfam/texto (heurística)", "regions": 0, "genes": len(genes), "species_id": sid}
        finally:
            path.unlink(missing_ok=True)                       # o arquivo enviado nunca permanece em disco
        self.imports.append(res)
        self.version += 1
        self._cache.clear()
        return res

    def clear(self) -> None:
        """Apaga TODOS os dados da sessão (banco em memória e diretório temporário)."""
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.__init__()

    def species(self):
        return genoteca.species_list(self.db)

    def records(self, species_id: int | None = None):
        k = ("rec", species_id, self.version)
        if k not in self._cache:
            self._cache[k] = analysis.load_records(self.db, species_id)
        return self._cache[k]

    def gene_row(self, gid: int):
        return genoteca.get_gene(self.db, gid)

    # ---- exportações em bytes
    def csv(self, recs, keys, source) -> bytes:
        return export.csv_bytes(recs, keys, source)

    def xlsx(self, recs, keys, source, meta=None) -> bytes:
        buf = io.BytesIO()
        export.write_xlsx(buf, recs, keys, source, meta or {})
        return buf.getvalue()

    def html_report(self, recs, species_id, source, title="") -> bytes:
        return htmlreport.report_html(self.db, recs, species_id, source, title).encode("utf-8")

    def pdf(self, recs, species_id, source, title="") -> bytes | None:
        """PDF via Qt (somente se PySide6 estiver instalado, ex.: servidor próprio). None se indisponível."""
        try:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide6.QtGui import QGuiApplication
            from codex import report
        except Exception:  # noqa: BLE001
            return None
        QGuiApplication.instance() or QGuiApplication([])
        out = Path(self.tmp) / "r.pdf"
        try:
            report.write_pdf(out, self.db, recs, species_id, source, title)
            return out.read_bytes()
        finally:
            out.unlink(missing_ok=True)
