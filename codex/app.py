"""Inicialização do aplicativo."""
from __future__ import annotations
import logging
import sys
import traceback

from .paths import bundled_content_dir, data_dir, user_content_dir


def _setup_logging() -> None:
    logging.basicConfig(filename=str(data_dir() / "codex.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")


def create_window():
    """Cria Context + MainWindow (usado também pelos testes de interface)."""
    from .content import Library
    from .db import UserDB
    from .ui.common import Context
    from .ui.main_window import MainWindow
    lib = Library()
    db = UserDB()
    fig_dirs = [bundled_content_dir() / "figures", user_content_dir() / "figures"]
    ctx = Context(lib, db, fig_dirs)
    return MainWindow(ctx), ctx


def selftest() -> int:
    """Verifica, dentro do executável empacotado, a leitura de GenBank (Biopython) e o motor do modelo gênico."""
    from . import antismash
    from .paths import bundled_content_dir
    sample = bundled_content_dir() / "samples" / "RICKED_scaf_70_region001.gbk"
    regions = antismash.parse_genbank(sample)
    g = next(x for x in regions[0].genes if x.locus_tag == "RICKED_008071")
    from .genemodel import GeneModel
    m = GeneModel(g.genomic_nt, [], g.strand, g.start, g.end, g.offset, g.scaffold, g.codon_start, 1, g.protein).with_exons_local([tuple(p) for p in g.parts])
    st = m.stats()
    ok = len(regions) == 1 and len(g.protein) == 2525 and st["exons"] == 9 and m.checks()["matches_stored"] and "mw_kda" in st
    print(f"SELFTEST {'OK' if ok else 'FALHOU'}: {len(regions[0].genes)} genes, {st['aa']} aa, {st['exons']} éxons, {st.get('mw_kda', 0):.1f} kDa")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    from PySide6.QtWidgets import QApplication, QMessageBox
    _setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Molecular Biology Codex")

    def hook(exc_type, exc, tb) -> None:
        msg = "".join(traceback.format_exception(exc_type, exc, tb))
        logging.error(msg)
        QMessageBox.critical(None, "Erro inesperado",
                             "Ocorreu um erro, mas seus dados foram preservados.\n"
                             f"Detalhes registrados em {data_dir() / 'codex.log'}\n\n{exc}")
    sys.excepthook = hook
    try:
        win, _ctx = create_window()
    except Exception as e:  # noqa: BLE001
        logging.exception("Falha ao iniciar")
        QMessageBox.critical(None, "Não foi possível iniciar", f"{e}\n\nVeja {data_dir() / 'codex.log'}")
        return 1
    win.show()
    return app.exec()
