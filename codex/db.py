"""Armazenamento local do usuário (SQLite): progresso, favoritos, notas, dúvidas, revisões."""
from __future__ import annotations
import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

from .paths import data_dir
from .srs import CardState

MIGRATIONS = [
    # v1
    """
    CREATE TABLE progress(article_id TEXT PRIMARY KEY, first_opened TEXT, last_opened TEXT,
                          open_count INTEGER DEFAULT 0, manual_cap INTEGER);
    CREATE TABLE favorites(article_id TEXT PRIMARY KEY, created TEXT);
    CREATE TABLE notes(id INTEGER PRIMARY KEY AUTOINCREMENT, article_id TEXT, text TEXT,
                       created TEXT, updated TEXT);
    CREATE TABLE doubts(id INTEGER PRIMARY KEY AUTOINCREMENT, article_id TEXT, text TEXT,
                        source TEXT, created TEXT, resolved INTEGER DEFAULT 0);
    CREATE TABLE card_state(card_id TEXT PRIMARY KEY, article_id TEXT, ease REAL, interval INTEGER,
                            reps INTEGER, lapses INTEGER, due TEXT);
    CREATE TABLE reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, kind TEXT, article_id TEXT,
                         ts TEXT, correct INTEGER, rating INTEGER, confidence INTEGER, answer TEXT);
    CREATE TABLE settings(k TEXT PRIMARY KEY, v TEXT);
    CREATE INDEX idx_reviews_item ON reviews(item_id);
    CREATE INDEX idx_reviews_article ON reviews(article_id);
    """,
    # v2: Genoteca (coleção de espécies, genes e BGCs) e evidências por gene
    """
    CREATE TABLE species(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, strain TEXT, genome_accession TEXT,
                         genome_file TEXT, taxonomy TEXT, notes TEXT, created TEXT);
    CREATE TABLE bgcs(id INTEGER PRIMARY KEY AUTOINCREMENT, species_id INTEGER, name TEXT, contig TEXT, start INTEGER,
                      end INTEGER, products TEXT, source TEXT, source_file TEXT, notes TEXT, created TEXT,
                      contig_edge INTEGER DEFAULT 0);
    CREATE TABLE genes(id INTEGER PRIMARY KEY AUTOINCREMENT, species_id INTEGER, bgc_id INTEGER, locus_tag TEXT,
                       product TEXT, gene_class TEXT, kind TEXT, contig TEXT, start INTEGER, end INTEGER, strand INTEGER,
                       protein TEXT, domains TEXT, notes TEXT, created TEXT, UNIQUE(species_id, locus_tag));
    CREATE TABLE evidence(id INTEGER PRIMARY KEY AUTOINCREMENT, gene_id INTEGER, stage INTEGER, note TEXT,
                          source TEXT, ts TEXT, UNIQUE(gene_id, stage));
    CREATE INDEX idx_genes_species ON genes(species_id);
    CREATE INDEX idx_genes_bgc ON genes(bgc_id);
    """,
    # v3: modelo gênico (éxons, sequência genômica orientada), metadados do antiSMASH e modelo editado pelo usuário
    """
    ALTER TABLE genes ADD COLUMN parts TEXT;
    ALTER TABLE genes ADD COLUMN genomic_nt TEXT;
    ALTER TABLE genes ADD COLUMN offset INTEGER DEFAULT 0;
    ALTER TABLE genes ADD COLUMN scaffold TEXT;
    ALTER TABLE genes ADD COLUMN codon_start INTEGER DEFAULT 1;
    ALTER TABLE genes ADD COLUMN user_parts TEXT;
    ALTER TABLE genes ADD COLUMN meta TEXT;
    ALTER TABLE bgcs ADD COLUMN meta TEXT;
    ALTER TABLE species ADD COLUMN info TEXT;
    """,
]


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class UserDB:
    def __init__(self, path: str | Path | None = None, check_same_thread: bool = True):
        self.path = Path(path) if path else data_dir() / "codex.db"
        self.con = sqlite3.connect(str(self.path), check_same_thread=check_same_thread)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        ver = self.con.execute("PRAGMA user_version").fetchone()[0]
        for i in range(ver, len(MIGRATIONS)):
            self.con.executescript(MIGRATIONS[i])
            self.con.execute(f"PRAGMA user_version={i + 1}")
        self.con.commit()

    def close(self) -> None:
        self.con.commit()
        self.con.close()

    # --------------------------------------------------------------- settings
    def get_setting(self, key: str, default: str = "") -> str:
        r = self.con.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
        return r["v"] if r else default

    def set_setting(self, key: str, value: str) -> None:
        self.con.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                         (key, value))
        self.con.commit()

    # --------------------------------------------------------------- progress
    def touch_article(self, aid: str) -> None:
        t = now()
        self.con.execute(
            "INSERT INTO progress(article_id, first_opened, last_opened, open_count) VALUES(?,?,?,1) "
            "ON CONFLICT(article_id) DO UPDATE SET last_opened=?, open_count=open_count+1", (aid, t, t, t))
        self.set_setting("last_article", aid)

    def progress_all(self) -> dict[str, sqlite3.Row]:
        return {r["article_id"]: r for r in self.con.execute("SELECT * FROM progress")}

    def set_manual_cap(self, aid: str, cap: int | None) -> None:
        self.con.execute("INSERT INTO progress(article_id, first_opened, last_opened, open_count, manual_cap) "
                         "VALUES(?,?,?,0,?) ON CONFLICT(article_id) DO UPDATE SET manual_cap=?",
                         (aid, now(), now(), cap, cap))
        self.con.commit()

    def recent_articles(self, n: int = 5) -> list[str]:
        return [r["article_id"] for r in self.con.execute(
            "SELECT article_id FROM progress WHERE open_count>0 ORDER BY last_opened DESC LIMIT ?", (n,))]

    # -------------------------------------------------------------- favorites
    def is_favorite(self, aid: str) -> bool:
        return self.con.execute("SELECT 1 FROM favorites WHERE article_id=?", (aid,)).fetchone() is not None

    def toggle_favorite(self, aid: str) -> bool:
        if self.is_favorite(aid):
            self.con.execute("DELETE FROM favorites WHERE article_id=?", (aid,))
            state = False
        else:
            self.con.execute("INSERT INTO favorites VALUES(?,?)", (aid, now()))
            state = True
        self.con.commit()
        return state

    def favorites(self) -> set[str]:
        return {r["article_id"] for r in self.con.execute("SELECT article_id FROM favorites")}

    # ------------------------------------------------------------------ notes
    def add_note(self, aid: str, text: str) -> int:
        cur = self.con.execute("INSERT INTO notes(article_id,text,created,updated) VALUES(?,?,?,?)",
                               (aid, text, now(), now()))
        self.con.commit()
        return int(cur.lastrowid)

    def update_note(self, nid: int, text: str) -> None:
        self.con.execute("UPDATE notes SET text=?, updated=? WHERE id=?", (text, now(), nid))
        self.con.commit()

    def delete_note(self, nid: int) -> None:
        self.con.execute("DELETE FROM notes WHERE id=?", (nid,))
        self.con.commit()

    def notes(self, aid: str | None = None) -> list[sqlite3.Row]:
        if aid:
            return list(self.con.execute("SELECT * FROM notes WHERE article_id=? ORDER BY created", (aid,)))
        return list(self.con.execute("SELECT * FROM notes ORDER BY article_id, created"))

    # ----------------------------------------------------------------- doubts
    def add_doubt(self, aid: str, text: str, source: str = "") -> int:
        cur = self.con.execute("INSERT INTO doubts(article_id,text,source,created) VALUES(?,?,?,?)",
                               (aid, text, source, now()))
        self.con.commit()
        return int(cur.lastrowid)

    def doubts(self, pending_only: bool = True) -> list[sqlite3.Row]:
        q = "SELECT * FROM doubts" + (" WHERE resolved=0" if pending_only else "") + " ORDER BY created DESC"
        return list(self.con.execute(q))

    def resolve_doubt(self, did: int, resolved: bool = True) -> None:
        self.con.execute("UPDATE doubts SET resolved=? WHERE id=?", (1 if resolved else 0, did))
        self.con.commit()

    # ------------------------------------------------------------------ cards
    def card_state(self, card_id: str) -> CardState | None:
        r = self.con.execute("SELECT * FROM card_state WHERE card_id=?", (card_id,)).fetchone()
        return CardState(r["ease"], r["interval"], r["reps"], r["lapses"], r["due"]) if r else None

    def save_card_state(self, card_id: str, aid: str, st: CardState) -> None:
        self.con.execute(
            "INSERT INTO card_state VALUES(?,?,?,?,?,?,?) ON CONFLICT(card_id) DO UPDATE SET "
            "ease=excluded.ease, interval=excluded.interval, reps=excluded.reps, "
            "lapses=excluded.lapses, due=excluded.due", (card_id, aid, st.ease, st.interval, st.reps, st.lapses, st.due))
        self.con.commit()

    def all_card_states(self) -> dict[str, CardState]:
        return {r["card_id"]: CardState(r["ease"], r["interval"], r["reps"], r["lapses"], r["due"])
                for r in self.con.execute("SELECT * FROM card_state")}

    def due_card_ids(self, today: dt.date | None = None) -> list[str]:
        t = (today or dt.date.today()).isoformat()
        return [r["card_id"] for r in self.con.execute(
            "SELECT card_id FROM card_state WHERE due<=? ORDER BY due", (t,))]

    # ---------------------------------------------------------------- reviews
    def record_review(self, item_id: str, kind: str, aid: str, correct: bool | None,
                      rating: int | None = None, confidence: int | None = None, answer: str = "") -> None:
        self.con.execute(
            "INSERT INTO reviews(item_id,kind,article_id,ts,correct,rating,confidence,answer) VALUES(?,?,?,?,?,?,?,?)",
            (item_id, kind, aid, now(), None if correct is None else int(correct), rating, confidence, answer))
        self.con.commit()

    def last_result(self, item_id: str) -> sqlite3.Row | None:
        return self.con.execute("SELECT * FROM reviews WHERE item_id=? ORDER BY id DESC LIMIT 1",
                                (item_id,)).fetchone()

    def last_results_for_article(self, aid: str) -> dict[str, sqlite3.Row]:
        out: dict[str, sqlite3.Row] = {}
        for r in self.con.execute("SELECT * FROM reviews WHERE article_id=? ORDER BY id", (aid,)):
            out[r["item_id"]] = r
        return out

    def reviews_by_day(self, days: int = 14) -> list[tuple[str, int, int]]:
        since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
        rows = self.con.execute(
            "SELECT substr(ts,1,10) d, COUNT(*) n, SUM(CASE WHEN correct=1 OR (correct IS NULL AND rating>=2) "
            "THEN 1 ELSE 0 END) ok FROM reviews WHERE substr(ts,1,10)>=? GROUP BY d ORDER BY d", (since,))
        return [(r["d"], r["n"], r["ok"] or 0) for r in rows]

    def accuracy_by_article(self) -> list[tuple[str, int, int]]:
        rows = self.con.execute(
            "SELECT article_id, COUNT(*) n, SUM(CASE WHEN correct=1 OR (correct IS NULL AND rating>=2) "
            "THEN 1 ELSE 0 END) ok FROM reviews GROUP BY article_id ORDER BY article_id")
        return [(r["article_id"], r["n"], r["ok"] or 0) for r in rows]

    def difficult_item_ids(self) -> list[str]:
        """Itens cujo último resultado foi erro/dificuldade, ou cartões com lapsos."""
        ids = [r["item_id"] for r in self.con.execute(
            "SELECT r.item_id FROM reviews r JOIN (SELECT item_id, MAX(id) mid FROM reviews GROUP BY item_id) m "
            "ON r.id=m.mid WHERE r.correct=0 OR r.rating<=1")]
        ids += [r["card_id"] for r in self.con.execute("SELECT card_id FROM card_state WHERE lapses>0")]
        return list(dict.fromkeys(ids))

    # ----------------------------------------------------------- export/backup
    def backup_to(self, dest: str | Path) -> None:
        self.con.commit()
        out = sqlite3.connect(str(dest))
        with out:
            self.con.backup(out)
        out.close()

    def export_json(self, dest: str | Path) -> None:
        def rows(t: str) -> list[dict[str, Any]]:
            return [dict(r) for r in self.con.execute(f"SELECT * FROM {t}")]
        data = {"exported": now(), "notes": rows("notes"), "doubts": rows("doubts"),
                "favorites": rows("favorites"), "card_state": rows("card_state"),
                "reviews": rows("reviews"), "progress": rows("progress")}
        Path(dest).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def export_notes_markdown(self, dest: str | Path, titles: dict[str, str]) -> None:
        lines = ["# Minhas notas e dúvidas — Molecular Biology Codex\n"]
        cur = None
        for n in self.notes():
            if n["article_id"] != cur:
                cur = n["article_id"]
                lines.append(f"\n## {titles.get(cur, cur)}\n")
            lines.append(f"- ({n['created'][:10]}) {n['text']}")
        pend = self.doubts(False)
        if pend:
            lines.append("\n# Dúvidas\n")
            for d in pend:
                mark = "x" if d["resolved"] else " "
                lines.append(f"- [{mark}] **{titles.get(d['article_id'], d['article_id'])}**: {d['text']}")
        Path(dest).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def export_cards_csv(self, dest: str | Path, library) -> None:
        import csv
        with open(dest, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["id", "artigo", "pergunta", "resposta", "explicacao"])
            for a in library.sorted_articles():
                for i, c in enumerate(a.flashcards):
                    w.writerow([f"{a.id}:c{i}", a.id, c.get("q", ""), c.get("a", ""), c.get("explain", "")])

    @staticmethod
    def restore_from(src: str | Path, dest: str | Path) -> None:
        """Valida o arquivo de backup antes de substituir o banco."""
        test = sqlite3.connect(str(src))
        try:
            names = {r[0] for r in test.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            test.close()
        if not {"progress", "reviews", "card_state"} <= names:
            raise ValueError("O arquivo selecionado não parece ser um backup do Codex.")
        import shutil
        shutil.copyfile(src, dest)
