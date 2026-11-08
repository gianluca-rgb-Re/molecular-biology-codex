"""Validação ESTRUTURAL da base de conhecimento.

Atenção: validar a estrutura NÃO valida a ciência. Um artigo sem erros aqui pode conter
imprecisões; a revisão por especialista é um processo à parte (campo 'verification').
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path

from .content import (ID_RE, LEVELS, REF_STATUS, REF_TYPES, RELATION_TYPES, VERIFICATION, Library)
from .render import BOX_TYPES, CITE_RE, IMG_RE, WIKILINK_RE

MIN_META = ("authors", "title", "container", "year")


@dataclass
class Issue:
    severity: str   # "erro" | "aviso"
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.where}: {self.message}"


def _cited_keys(body: str) -> set[str]:
    keys: set[str] = set()
    for m in CITE_RE.finditer(body):
        keys |= {k.strip().lstrip("@") for k in re.split(r"[;,]", m.group(1)) if k.strip()}
    return keys


def validate(lib: Library, fig_dirs: list[Path] | None = None) -> list[Issue]:
    issues: list[Issue] = []
    add = lambda sev, where, msg: issues.append(Issue(sev, where, msg))  # noqa: E731
    fig_dirs = fig_dirs or [d / "figures" for d in (lib.dirs or [])]
    for p in lib.problems:
        add("erro", "carregamento", p)

    seen_ids: dict[str, str] = {}
    for a in lib.articles.values():
        w = f"artigo '{a.id}'"
        for p in a.problems:
            add("erro", w, p)
        if not ID_RE.match(a.id):
            add("erro", w, "ID deve conter apenas a-z, 0-9 e hífen.")
        if a.id in seen_ids:
            add("erro", w, f"ID duplicado (também em {seen_ids[a.id]}).")
        seen_ids[a.id] = a.path
        if not a.title.strip():
            add("erro", w, "Título vazio.")
        if a.level not in LEVELS:
            add("erro", w, f"Nível inválido: {a.level}")
        if a.verification not in VERIFICATION:
            add("erro", w, f"Status de verificação inválido: {a.verification}")
        for pid in a.prereqs:
            if pid not in lib.articles:
                add("erro", w, f"Pré-requisito inexistente: {pid}")
            if pid == a.id:
                add("erro", w, "Artigo é pré-requisito de si mesmo.")
        for r in a.relations:
            if r.get("to") not in lib.articles:
                add("erro", w, f"Relação aponta para ID inexistente: {r.get('to')}")
            if r.get("type") not in RELATION_TYPES:
                add("erro", w, f"Tipo de relação inválido: {r.get('type')}")
        for n in a.next:
            if n.get("id") not in lib.articles:
                add("erro", w, f"'Continue explorando' aponta para ID inexistente: {n.get('id')}")
            if not n.get("why"):
                add("aviso", w, f"Recomendação sem justificativa: {n.get('id')}")
        for m in WIKILINK_RE.finditer(a.body):
            if m.group(1) not in lib.articles:
                add("erro", w, f"Link interno quebrado: [[{m.group(1)}]]")
        cited = _cited_keys(a.body)
        for k in cited:
            if k not in lib.refs:
                add("erro", w, f"Citação sem correspondência no catálogo: {k}")
        if not cited and a.body.strip():
            add("aviso", w, "Artigo sem nenhuma citação [@chave].")
        for m in IMG_RE.finditer(__import__("markdown").markdown(a.body)):
            name = Path(m.group(2)).name
            if not any((Path(d) / name).exists() for d in fig_dirs):
                add("erro", w, f"Figura referenciada não existe: {name}")
        for m in re.finditer(r"^:::(\w+)", a.body, re.M):
            if m.group(1) not in BOX_TYPES:
                add("erro", w, f"Tipo de bloco desconhecido: :::{m.group(1)}")
        if len(re.findall(r"^:::\w+", a.body, re.M)) != len(re.findall(r"^:::[ \t]*$", a.body, re.M)):
            add("erro", w, "Blocos ':::' não fechados corretamente.")
        for i, c in enumerate(a.flashcards):
            if not c.get("q") or not c.get("a"):
                add("erro", w, f"Flashcard {i} sem pergunta/resposta.")
            for k in c.get("refs", []) or []:
                if k not in lib.refs:
                    add("erro", w, f"Flashcard {i} cita referência inexistente: {k}")
        for i, q in enumerate(a.questions):
            t = q.get("type", "mcq")
            if not q.get("q"):
                add("erro", w, f"Questão {i} sem enunciado.")
            if t == "mcq":
                opts, ans = q.get("options") or [], q.get("answer")
                if len(opts) < 2 or not isinstance(ans, int) or not (0 <= ans < len(opts)):
                    add("erro", w, f"Questão {i}: opções/gabarito inválidos.")
                if len(q.get("explanations") or []) != len(opts):
                    add("erro", w, f"Questão {i}: é preciso explicar cada alternativa (correta e incorretas).")
            elif t in ("open", "experiment"):
                if not q.get("model_answer"):
                    add("erro", w, f"Questão {i}: sem resposta-modelo.")
            else:
                add("erro", w, f"Questão {i}: tipo inválido '{t}'.")
        # ciclo de pré-requisitos
        stack: set[str] = set()

        def dfs(x: str) -> bool:
            if x in stack:
                return True
            if x not in lib.articles:
                return False
            stack.add(x)
            res = any(dfs(p) for p in lib.articles[x].prereqs)
            stack.discard(x)
            return res
        if dfs(a.id):
            add("erro", w, "Ciclo detectado na cadeia de pré-requisitos.")

    for k, r in lib.refs.items():
        w = f"referência '{k}'"
        v = (r.get("verification") or {}).get("status", "pendente")
        if v not in REF_STATUS:
            add("erro", w, f"Status de verificação inválido: {v}")
        if r.get("type") not in REF_TYPES:
            add("erro", w, f"Tipo de publicação inválido: {r.get('type')}")
        if v in ("verificada", "verificada_parcial"):
            missing = [f for f in MIN_META if not r.get(f)]
            if not (r.get("doi") or r.get("isbn") or r.get("url") or r.get("pmid")):
                missing.append("doi/pmid/isbn/url")
            if r.get("type") not in ("livro-texto", "banco-de-dados", "documentacao-tecnica") and not (
                    r.get("pages") or r.get("article_id")):
                missing.append("pages")
            if missing:
                add("erro", w, f"Marcada como verificada, mas faltam metadados: {', '.join(missing)}")
            if not (r.get("verification") or {}).get("how"):
                add("erro", w, "Marcada como verificada sem registrar COMO foi verificada.")
        else:
            add("aviso", w, "Pendente de verificação.")
    # conceitos sem citação no catálogo mas catálogo não usado
    used = set().union(*[_cited_keys(a.body) for a in lib.articles.values()]) if lib.articles else set()
    for k in lib.refs:
        if k not in used:
            add("aviso", f"referência '{k}'", "Não é citada por nenhum artigo.")
    return issues
