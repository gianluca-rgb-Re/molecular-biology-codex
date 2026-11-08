"""XP, nível do pesquisador, sequência de dias e conquistas — calculados a partir dos dados reais (sem contadores falsos)."""
from __future__ import annotations
import datetime as dt
import math
from dataclasses import dataclass

from . import genoteca
from .content import Library
from .db import UserDB
from .study import all_levels

RANKS = ["Aprendiz de bancada", "Estagiário", "Técnico", "Mestrando", "Doutorando", "Pesquisador júnior",
         "Pesquisador", "Pós-doutor", "Líder de grupo", "Mestre do Codex"]


@dataclass
class Profile:
    xp: int
    level: int
    rank: str
    xp_in_level: int
    xp_for_next: int
    streak: int
    best_streak: int


def xp_breakdown(lib: Library, db: UserDB) -> dict[str, int]:
    levels = all_levels(lib, db)
    r = db.con
    cards_ok = r.execute("SELECT COUNT(*) FROM reviews WHERE kind='card' AND rating>=2").fetchone()[0]
    cards_bad = r.execute("SELECT COUNT(*) FROM reviews WHERE kind='card' AND rating<2").fetchone()[0]
    mcq_ok = r.execute("SELECT COUNT(*) FROM reviews WHERE kind='mcq' AND correct=1").fetchone()[0]
    mcq_bad = r.execute("SELECT COUNT(*) FROM reviews WHERE kind='mcq' AND correct=0").fetchone()[0]
    open_n = r.execute("SELECT COUNT(*) FROM reviews WHERE kind='open'").fetchone()[0]
    return {
        "Artigos descobertos": 3 * sum(1 for v in levels.values() if v >= 1),
        "Níveis de domínio": 20 * sum(levels.values()),
        "Cartões": 8 * cards_ok + 3 * cards_bad,
        "Questões objetivas": 10 * mcq_ok + 3 * mcq_bad,
        "Questões discursivas": 15 * open_n,
        "Genoteca (evidências)": 25 * genoteca.summary(db)["stages"] + 5 * genoteca.summary(db)["genes"],
    }


def streaks(db: UserDB, today: dt.date | None = None) -> tuple[int, int]:
    today = today or dt.date.today()
    days = sorted({dt.date.fromisoformat(r[0]) for r in db.con.execute("SELECT DISTINCT substr(ts,1,10) FROM reviews")})
    if not days:
        return 0, 0
    best = run = 1
    for a, b in zip(days, days[1:]):
        run = run + 1 if (b - a).days == 1 else 1
        best = max(best, run)
    cur = 0
    d = today if today in days else today - dt.timedelta(days=1)
    s = set(days)
    while d in s:
        cur += 1
        d -= dt.timedelta(days=1)
    return cur, best


def profile(lib: Library, db: UserDB) -> Profile:
    xp = sum(xp_breakdown(lib, db).values())
    level = int(math.sqrt(xp / 40)) + 1
    base, nxt = 40 * (level - 1) ** 2, 40 * level ** 2
    cur, best = streaks(db)
    return Profile(xp, level, RANKS[min(len(RANKS) - 1, (level - 1) // 2)], xp - base, nxt - base, cur, best)


def achievements(lib: Library, db: UserDB) -> list[tuple[str, str, bool]]:
    levels = all_levels(lib, db)
    cur, best = streaks(db)
    g = genoteca.summary(db)
    n_rev = db.con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    by_cat: dict[str, list[int]] = {}
    for a in lib.articles.values():
        by_cat.setdefault(a.category, []).append(levels[a.id])
    full_chain = any(genoteca.top_stage(db, r["id"]) >= 4 for r in genoteca.genes_of_species(db))
    return [
        ("🔬 Primeira revisão", "Registre sua primeira resposta no Modo de estudo", n_rev >= 1),
        ("📚 Explorador", "Descubra 10 artigos", sum(1 for v in levels.values() if v >= 1) >= 10),
        ("🔥 Três dias seguidos", "Estude em 3 dias consecutivos", best >= 3),
        ("💯 Cinquenta respostas", "Registre 50 respostas", n_rev >= 50),
        ("🧠 Compreensão", "Alcance «Compreendido» em um artigo", any(v >= 3 for v in levels.values())),
        ("🏆 Dominado", "Alcance «Dominado» em um artigo", any(v >= 4 for v in levels.values())),
        ("🗺 Mestre de uma trilha", "Compreenda todos os artigos de uma categoria",
         any(len(v) >= 3 and min(v) >= 3 for v in by_cat.values())),
        ("🧬 Primeiro gene", "Adicione um gene à Genoteca", g["genes"] >= 1),
        ("🍄 Caçador de BGCs", "Importe um BGC para a Genoteca", g["bgcs"] >= 1),
        ("⚗ Cadeia até o produto", "Registre evidência de produto (estágio 4) em um gene", full_chain),
    ]
