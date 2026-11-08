"""Busca local: título, termo em inglês, siglas, sinônimos, tags, cabeçalhos e texto.

Implementação em Python puro (sem FTS5), sem acentos e sem diferenciar maiúsculas.
Os campos têm pesos diferentes; consultas com várias palavras exigem todas (E),
com recuo para correspondência parcial. O tesauro (content/thesaurus.yaml) expande
a consulta para termos equivalentes (ex.: "pol II" -> "RNA polimerase II").
Para bases com milhares de artigos, a classe pode ser trocada por um índice SQLite FTS5
mantendo a mesma interface (SearchIndex.search).
"""
from __future__ import annotations
import re
from dataclasses import dataclass

from .content import Article, Library, norm

TOKEN_RE = re.compile(r"[0-9a-z′'’\-\u2032]+")
WEIGHTS = {"title": 12.0, "title_en": 10.0, "synonyms": 10.0, "tags": 4.0, "headings": 4.0,
           "summary": 3.0, "body": 1.0}


@dataclass
class Hit:
    article_id: str
    score: float
    snippet: str
    matched: str


def tokens(text: str) -> list[str]:
    return [t.strip("-'’") for t in TOKEN_RE.findall(norm(text)) if t.strip("-'’")]


class SearchIndex:
    def __init__(self, library: Library):
        self.lib = library
        self.docs: dict[str, dict[str, str]] = {}
        self.vocab: dict[str, set[str]] = {}
        self.rebuild()

    def rebuild(self) -> None:
        self.docs = {}
        for a in self.lib.articles.values():
            fields = {
                "title": norm(a.title), "title_en": norm(a.title_en),
                "synonyms": norm(" | ".join(a.synonyms)), "tags": norm(" ".join(a.tags)),
                "headings": norm(" | ".join(a.headings)), "summary": norm(a.summary),
                "body": norm(a.body),
            }
            self.docs[a.id] = fields
        self._groups = [[norm(t) for t in g] for g in self.lib.thesaurus]

    # ------------------------------------------------------------------ query
    def _expansions(self, q: str) -> list[str]:
        nq = " ".join(tokens(q))
        out = [nq]
        for g in self._groups:
            for term in g:
                tt = " ".join(tokens(term))
                if tt and (nq == tt or (len(tt) > 3 and tt in nq)):
                    out += [" ".join(tokens(x)) for x in g if x != term]
                    break
        return list(dict.fromkeys(x for x in out if x))

    @staticmethod
    def _field_score(text: str, toks: list[str], phrase: str, weight: float) -> tuple[float, int]:
        if not text:
            return 0.0, 0
        words = set(TOKEN_RE.findall(text))
        s, hit = 0.0, 0
        for t in toks:
            if t in words:
                s += weight
                hit += 1
            elif len(t) >= 3 and any(w.startswith(t) for w in words):
                s += weight * 0.6
                hit += 1
            elif len(t) >= 4 and t in text:
                s += weight * 0.3
                hit += 1
        if phrase and phrase in text:
            s += weight * 1.5
        return s, hit

    def _score_doc(self, aid: str, qn: str) -> tuple[float, str]:
        toks = tokens(qn)
        if not toks:
            return 0.0, ""
        total, covered, best_field, best = 0.0, set(), "", 0.0
        for fname, weight in WEIGHTS.items():
            s, _ = self._field_score(self.docs[aid][fname], toks, qn if len(toks) > 1 else "", weight)
            if s > best:
                best, best_field = s, fname
            total += s
            for t in toks:
                txt = self.docs[aid][fname]
                if txt and (t in txt):
                    covered.add(t)
        if len(covered) < len(toks):          # exige todas as palavras (E)
            return 0.0, ""
        return total, best_field

    def search(self, query: str, limit: int = 30) -> list[Hit]:
        if not query.strip():
            return []
        best: dict[str, tuple[float, str]] = {}
        for qn in self._expansions(query):
            for aid in self.docs:
                s, f = self._score_doc(aid, qn)
                if s > 0 and s > best.get(aid, (0, ""))[0]:
                    best[aid] = (s, f)
        hits = [Hit(aid, s, self._snippet(aid, query), f) for aid, (s, f) in best.items()]
        hits.sort(key=lambda h: (-h.score, self.lib.articles[h.article_id].title))
        return hits[:limit]

    def _snippet(self, aid: str, query: str) -> str:
        art: Article = self.lib.articles[aid]
        toks = tokens(query)
        text = re.sub(r"[#*>`\[\]|]|:::\w*", " ", art.body)
        text = re.sub(r"\s+", " ", text)
        low = norm(text)
        for t in toks:
            pos = low.find(t)
            if pos >= 0:
                a, b = max(0, pos - 50), min(len(text), pos + 90)
                return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")
        return art.summary[:140]
