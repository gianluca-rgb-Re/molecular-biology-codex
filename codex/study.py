"""Níveis de domínio, filas de estudo e missões.

Níveis (0 a 4):
  0 Não iniciado
  1 Descoberto  - o artigo foi aberto
  2 Em estudo   - há ao menos uma resposta registrada (cartão ou questão)
  3 Compreendido- >=70% de acerto na última tentativa das questões objetivas respondidas (ao menos uma) e
                  pelo menos 3 evidências no total (questões objetivas certas + cartões com última avaliação
                  "Bom" ou "Fácil"); artigos sem questões objetivas não passam do nível 2
  4 Dominado    - nível 3 + questão discursiva/experimental autoavaliada como "Bom" ou "Fácil" + metade dos
                  cartões do artigo com última avaliação "Bom" ou "Fácil"
O usuário pode reduzir o teto (manual_cap) - por exemplo, para "preciso rever" - mas não pode elevar
o nível além do que as respostas registradas sustentam.
"""
from __future__ import annotations
import datetime as dt

from .content import Article, Library
from .db import UserDB

LEVEL_NAMES = {0: "Não iniciado", 1: "Descoberto", 2: "Em estudo", 3: "Compreendido", 4: "Dominado"}


def compute_level(art: Article, db: UserDB, progress: dict | None = None) -> int:
    prog = progress if progress is not None else db.progress_all()
    row = prog.get(art.id)
    results = db.last_results_for_article(art.id)
    opened = row is not None and (row["open_count"] or 0) > 0
    if not opened and not results:
        return 0
    level = 2 if results else 1
    mcq_ids = [f"{art.id}:q{i}" for i, q in enumerate(art.questions) if q.get("type", "mcq") == "mcq"]
    open_ids = [f"{art.id}:q{i}" for i, q in enumerate(art.questions) if q.get("type", "mcq") != "mcq"]
    answered = [results[i] for i in mcq_ids if i in results]
    cards = art.card_ids()
    good_cards = sum(1 for c in cards if c in results and (results[c]["rating"] or 0) >= 2)
    right = sum(1 for r in answered if r["correct"] == 1)
    if answered and right / len(answered) >= 0.7 and right + good_cards >= 3:
        level = 3
        open_ok = (not open_ids) or any(i in results and (results[i]["rating"] or 0) >= 2 for i in open_ids)
        cards_ok = (not cards) or good_cards >= len(cards) / 2
        if open_ok and cards_ok and (open_ids or cards):
            level = 4
    cap = row["manual_cap"] if row is not None else None
    if cap is not None:
        level = min(level, int(cap))
    return level


def all_levels(lib: Library, db: UserDB) -> dict[str, int]:
    prog = db.progress_all()
    return {a.id: compute_level(a, db, prog) for a in lib.articles.values()}


def is_recommended_first(art: Article, levels: dict[str, int]) -> bool:
    """True se há pré-requisitos ainda abaixo de 'Em estudo' (orientação, não bloqueio)."""
    return any(levels.get(p, 0) < 2 for p in art.prereqs)


def missions(lib: Library, db: UserDB, levels: dict[str, int], n: int = 4) -> list[dict]:
    """Sugestões ancoradas na árvore de pré-requisitos e no estado de revisão."""
    out: list[dict] = []
    due = len(db.due_card_ids())
    if due:
        out.append({"kind": "review", "text": f"Revisar {due} cartão(ões) vencido(s)", "target": None})
    for aid in lib.topological_order():
        a = lib.articles[aid]
        lv = levels.get(aid, 0)
        if lv < 3 and not is_recommended_first(a, levels):
            verb = "Começar" if lv == 0 else "Continuar"
            out.append({"kind": "study", "text": f"{verb} o artigo: {a.title}", "target": aid})
        if len(out) >= n:
            break
    return out[:n]


def build_item_index(lib: Library) -> dict[str, tuple[str, str, dict]]:
    """item_id -> (article_id, 'card'|'mcq'|'open', dados)."""
    idx: dict[str, tuple[str, str, dict]] = {}
    for a in lib.articles.values():
        for i, c in enumerate(a.flashcards):
            idx[f"{a.id}:c{i}"] = (a.id, "card", c)
        for i, q in enumerate(a.questions):
            idx[f"{a.id}:q{i}"] = (a.id, "mcq" if q.get("type", "mcq") == "mcq" else "open", q)
    return idx


def build_card_queue(lib: Library, db: UserDB, article_id: str | None = None, limit: int = 20,
                     today: dt.date | None = None) -> list[str]:
    states = db.all_card_states()
    t = (today or dt.date.today()).isoformat()
    due = [cid for cid, st in sorted(states.items(), key=lambda kv: kv[1].due) if st.due <= t]
    new = [cid for a in lib.sorted_articles() for cid in a.card_ids() if cid not in states]
    if article_id:
        pref = f"{article_id}:"
        due = [c for c in due if c.startswith(pref)]
        new = [c for c in new if c.startswith(pref)]
    valid = {cid for a in lib.articles.values() for cid in a.card_ids()}
    return [c for c in due + new if c in valid][:limit]
