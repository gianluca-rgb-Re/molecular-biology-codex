"""Carregamento da base de conhecimento (artigos Markdown + catálogo de referências)."""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import bundled_content_dir, user_content_dir

RELATION_TYPES = {
    "forma_de": "é uma forma de",
    "participa_de": "participa de",
    "regula": "regula",
    "antes_de": "ocorre antes de",
    "necessario_para": "é necessário para",
    "pode_causar": "pode causar",
    "medido_por": "é medido por",
    "diferente_de": "é diferente de",
}
LEVELS = {"iniciante": "Iniciante", "intermediario": "Intermediário", "avancado": "Avançado"}
VERIFICATION = {
    "nao_revisado": "Texto ainda não revisado por especialista",
    "revisao_parcial": "Revisão parcial por especialista",
    "revisado": "Revisado por especialista",
}
REF_STATUS = {
    "verificada": "Verificada (metadados conferidos em fonte bibliográfica)",
    "verificada_parcial": "Parcialmente verificada (conferida em fonte secundária)",
    "pendente": "Pendente de verificação",
}
REF_TYPES = {
    "livro-texto", "revisao-narrativa", "revisao-sistematica", "artigo-original",
    "protocolo", "banco-de-dados", "documentacao-tecnica", "preprint",
}
REQUIRED_FIELDS = ("id", "title", "category", "level", "summary")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)
LINK_RE = re.compile(r"\[\[([a-z0-9\-]+)(?:\|[^\]]*)?\]\]")


def norm(text: str) -> str:
    """Minúsculas e sem acentos, para busca e comparação."""
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


@dataclass
class Article:
    id: str
    title: str
    title_en: str = ""
    synonyms: list[str] = field(default_factory=list)
    category: str = "Sem categoria"
    subcategory: str = ""
    level: str = "iniciante"
    prereqs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    body: str = ""
    relations: list[dict[str, str]] = field(default_factory=list)
    next: list[dict[str, str]] = field(default_factory=list)
    flashcards: list[dict[str, Any]] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    last_review: str = ""
    added: str = ""
    verification: str = "nao_revisado"
    path: str = ""
    origin: str = "bundled"
    problems: list[str] = field(default_factory=list)

    @property
    def headings(self) -> list[str]:
        return [m.group(1).strip() for m in re.finditer(r"^#{2,4}\s+(.+)$", self.body, re.M)]

    def card_ids(self) -> list[str]:
        return [f"{self.id}:c{i}" for i in range(len(self.flashcards))]

    def question_ids(self) -> list[str]:
        return [f"{self.id}:q{i}" for i in range(len(self.questions))]


def _as_list(v: Any) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def parse_article(path: Path, origin: str = "bundled") -> Article:
    """Lê um arquivo .md. Nunca levanta exceção: problemas ficam em Article.problems."""
    problems: list[str] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return Article(id=path.stem, title=path.stem, path=str(path), origin=origin,
                       problems=[f"Não foi possível ler o arquivo: {e}"])
    m = FRONT_RE.match(raw.replace("\r\n", "\n"))
    meta: dict[str, Any] = {}
    body = raw
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
            if not isinstance(meta, dict):
                problems.append("Cabeçalho YAML não é um dicionário.")
                meta = {}
        except yaml.YAMLError as e:
            problems.append(f"Cabeçalho YAML inválido: {e}")
        body = m.group(2)
    else:
        problems.append("Arquivo sem cabeçalho YAML (--- ... ---).")
    for f in REQUIRED_FIELDS:
        if not meta.get(f):
            problems.append(f"Campo obrigatório ausente: {f}")
    return Article(
        id=str(meta.get("id") or path.stem),
        title=str(meta.get("title") or path.stem),
        title_en=str(meta.get("title_en") or ""),
        synonyms=[str(x) for x in _as_list(meta.get("synonyms"))],
        category=str(meta.get("category") or "Sem categoria"),
        subcategory=str(meta.get("subcategory") or ""),
        level=str(meta.get("level") or "iniciante"),
        prereqs=[str(x) for x in _as_list(meta.get("prereqs"))],
        tags=[str(x) for x in _as_list(meta.get("tags"))],
        summary=str(meta.get("summary") or "").strip(),
        body=body,
        relations=[r for r in _as_list(meta.get("relations")) if isinstance(r, dict)],
        next=[r for r in _as_list(meta.get("next")) if isinstance(r, dict)],
        flashcards=[c for c in _as_list(meta.get("flashcards")) if isinstance(c, dict)],
        questions=[q for q in _as_list(meta.get("questions")) if isinstance(q, dict)],
        last_review=str(meta.get("last_review") or ""),
        added=str(meta.get("added") or ""),
        verification=str(meta.get("verification") or "nao_revisado"),
        path=str(path), origin=origin, problems=problems,
    )


def format_reference(ref: dict[str, Any]) -> str:
    """Citação em texto simples (próxima ao estilo Vancouver, sem pretensão normativa)."""
    authors = ref.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    a = ", ".join(authors[:6]) + (" et al." if len(authors) > 6 else "")
    title = str(ref.get("title", "")).rstrip(".")
    cont, year = ref.get("container", ""), ref.get("year", "")
    if ref.get("type") == "livro-texto":
        ed = f"{str(ref['edition']).rstrip('.')}. " if ref.get("edition") else ""
        tail = f"{ed}{cont}, {year}."
    else:
        vol = f";{ref['volume']}" if ref.get("volume") else ""
        iss = f"({ref['issue']})" if ref.get("issue") else ""
        pg = f":{ref['pages']}" if ref.get("pages") else ""
        tail = f"{cont}. {year}{vol}{iss}{pg}."
    return " ".join(p for p in [f"{a}." if a else "", f"{title}.", tail] if p)


class Library:
    """Artigos, referências, categorias e tesauro carregados do disco."""

    def __init__(self, dirs: list[Path] | None = None):
        self.dirs = dirs
        self.articles: dict[str, Article] = {}
        self.refs: dict[str, dict[str, Any]] = {}
        self.categories: list[str] = []
        self.thesaurus: list[list[str]] = []
        self.problems: list[str] = []
        self.backlinks: dict[str, set[str]] = {}
        self.cat_order: dict[str, int] = {}
        self.load()

    def load(self) -> None:
        self.articles, self.refs, self.categories = {}, {}, []
        self.thesaurus, self.problems = [], []
        dirs = self.dirs if self.dirs is not None else [bundled_content_dir(), user_content_dir()]
        for i, d in enumerate(dirs):
            self._load_dir(Path(d), "bundled" if i == 0 else "user")
        self._build_indexes()

    def _read_yaml(self, path: Path) -> Any:
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            self.problems.append(f"{path.name}: não foi possível ler ({e})")
            return None

    def _load_dir(self, d: Path, origin: str) -> None:
        if not d.exists():
            return
        data = self._read_yaml(d / "categories.yaml") if (d / "categories.yaml").exists() else None
        for c in data if isinstance(data, list) else []:
            if str(c) not in self.categories:
                self.categories.append(str(c))
        data = self._read_yaml(d / "thesaurus.yaml") if (d / "thesaurus.yaml").exists() else None
        for g in data if isinstance(data, list) else []:
            if isinstance(g, list):
                self.thesaurus.append([str(t) for t in g])
        ref_files = [d / "references.yaml"] + sorted((d / "references").glob("*.yaml"))
        for rf in ref_files:
            if rf.exists():
                data = self._read_yaml(rf)
                for k, v in (data.items() if isinstance(data, dict) else []):
                    if isinstance(v, dict):
                        self.refs[str(k)] = v
        for md in sorted((d / "articles").glob("*.md")):
            art = parse_article(md, origin)
            prev = self.articles.get(art.id)
            if prev is not None and prev.origin == origin:
                art.problems.append(f"ID duplicado: {art.id}")
                self.problems.append(f"ID duplicado '{art.id}' em {md.name}")
            self.articles[art.id] = art  # conteúdo do usuário substitui o empacotado

    def _build_indexes(self) -> None:
        self.backlinks = {i: set() for i in self.articles}
        for a in self.articles.values():
            targets = set(LINK_RE.findall(a.body)) | {r.get("to", "") for r in a.relations} | set(a.prereqs)
            for t in targets:
                if t in self.backlinks and t != a.id:
                    self.backlinks[t].add(a.id)
        self.cat_order = {c: i for i, c in enumerate(self.categories)}

    # ---------------------------------------------------------------- queries
    def get(self, aid: str) -> Article | None:
        return self.articles.get(aid)

    def sorted_articles(self) -> list[Article]:
        return sorted(self.articles.values(),
                      key=lambda a: (self.cat_order.get(a.category, 999), norm(a.subcategory), norm(a.title)))

    def by_category(self) -> dict[str, list[Article]]:
        out: dict[str, list[Article]] = {}
        for a in self.sorted_articles():
            out.setdefault(a.category, []).append(a)
        return dict(sorted(out.items(), key=lambda kv: self.cat_order.get(kv[0], 999)))

    def incoming_relations(self, aid: str) -> list[tuple[str, str]]:
        return [(a.id, r["type"]) for a in self.articles.values()
                for r in a.relations if r.get("to") == aid and r.get("type")]

    def topological_order(self) -> list[str]:
        """Ordem que respeita pré-requisitos (ciclos são ignorados; o validador os reporta)."""
        seen: set[str] = set()
        order: list[str] = []

        def visit(i: str, stack: set[str]) -> None:
            if i in seen or i in stack or i not in self.articles:
                return
            stack.add(i)
            for p in self.articles[i].prereqs:
                visit(p, stack)
            stack.discard(i)
            seen.add(i)
            order.append(i)

        for a in self.sorted_articles():
            visit(a.id, set())
        return order
