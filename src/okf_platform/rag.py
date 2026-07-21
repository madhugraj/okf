"""Independent hybrid RAG index with parent-child retrieval and citation checks."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Protocol

from .knowledge_io import atomic_json, canonical_json_lines, load_extraction, stable_id
from .snapshot import canonical_hash


RAG_VERSION = "advanced-rag/1.0"
INDEX_VERSION = "hybrid-parent-child-index/1.0"
EMBEDDING_VERSION = "deterministic-feature-hash/1.0"
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{1,}")
STOPWORDS = frozenset(
    "a an and are as at be by for from has have in into is it its of on or that the this to was were will with what which who how when where why".split()
)
VECTOR_SIZE = 256


class DenseEncoder(Protocol):
    name: str

    def embed(self, text: str) -> dict[int, float]: ...


class AnswerGenerator(Protocol):
    name: str

    def generate(self, question: str, evidence: list[dict[str, object]]) -> str: ...


class FeatureHashEncoder:
    """Provider-free baseline behind the same contract as a learned encoder."""

    name = EMBEDDING_VERSION

    def embed(self, text: str) -> dict[int, float]:
        return _dense_vector(text)


class ExtractiveAnswerGenerator:
    """Grounded local fallback used until an approved answer model is configured."""

    name = "evidence-extractive-generator/1.0"

    def generate(self, question: str, evidence: list[dict[str, object]]) -> str:
        del question
        snippets = []
        for item in evidence[:3]:
            text = str(item["text"]).strip()
            snippets.append(re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0])
        return " ".join(dict.fromkeys(snippets))


DEFAULT_ENCODER = FeatureHashEncoder()
DEFAULT_GENERATOR = ExtractiveAnswerGenerator()


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def _search_terms(text: str) -> list[str]:
    return [token for token in _tokens(text) if token not in STOPWORDS]


def _dense_vector(text: str) -> dict[int, float]:
    """Produce a deterministic local dense vector without external model calls."""

    features = _search_terms(text)
    features.extend(
        token[index : index + 3]
        for token in list(features)
        for index in range(max(0, len(token) - 2))
    )
    values: defaultdict[int, float] = defaultdict(float)
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % VECTOR_SIZE
        sign = 1.0 if digest[4] & 1 else -1.0
        values[bucket] += sign
    magnitude = math.sqrt(sum(value * value for value in values.values()))
    if magnitude:
        return {key: value / magnitude for key, value in values.items()}
    return {}


def _cosine(left: dict[int, float], right: dict[int, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(key, 0.0) for key, value in left.items())


def _child_spans(text: str, *, size: int = 900, overlap: int = 120) -> list[tuple[int, int]]:
    if not text:
        return []
    spans = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = max(text.rfind("\n", start + 300, end), text.rfind(". ", start + 300, end))
            if boundary > start:
                end = boundary + 1
        spans.append((start, end))
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return spans


def _build_chunks(records: list[dict[str, object]]) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    for record in records:
        for unit in record.get("units", []):
            text = str(unit["text"])
            parent_id = stable_id("parent", record["object_sha256"], unit["unit_id"])
            for sequence, (start, end) in enumerate(_child_spans(text), start=1):
                child_text = text[start:end]
                terms = _search_terms(child_text)
                chunks.append(
                    {
                        "id": stable_id("chunk", parent_id, sequence, child_text),
                        "parent_id": parent_id,
                        "unit_id": unit["unit_id"],
                        "object_sha256": record["object_sha256"],
                        "kind": record["kind"],
                        "source_urls": record.get("source_urls", []),
                        "locator": unit["locator"],
                        "char_start": start,
                        "char_end": end,
                        "text": child_text,
                        "parent_text": text,
                        "term_frequency": dict(Counter(terms)),
                        "token_count": len(terms),
                    }
                )
    return sorted(chunks, key=lambda item: str(item["id"]))


def build_rag_index(
    data_dir: Path, corpus_id: str, *, encoder: DenseEncoder = DEFAULT_ENCODER
) -> dict[str, object]:
    snapshot, extraction, records = load_extraction(data_dir, corpus_id)
    output_dir = data_dir / "knowledge" / corpus_id / RAG_VERSION.replace("/", "-")
    manifest_path = output_dir / "manifest.json"
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            existing.get("extraction_manifest_sha256") == extraction["manifest_sha256"]
            and existing.get("embedding_version") == encoder.name
        ):
            return existing

    chunks = _build_chunks(records)
    if not chunks:
        raise ValueError("RAG cannot index an extraction with no text units")
    document_frequency: Counter[str] = Counter()
    for chunk in chunks:
        document_frequency.update(chunk["term_frequency"].keys())
    chunks_text = canonical_json_lines(chunks)
    chunks_sha256 = hashlib.sha256(chunks_text.encode("utf-8")).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = output_dir / "chunks.jsonl.tmp"
    temporary.write_text(chunks_text, encoding="utf-8")
    temporary.replace(output_dir / "chunks.jsonl")
    core: dict[str, object] = {
        "schema_version": "rag-index-manifest/1.0",
        "rag_version": RAG_VERSION,
        "index_version": INDEX_VERSION,
        "embedding_version": encoder.name,
        "corpus_id": corpus_id,
        "corpus_manifest_sha256": snapshot["manifest_sha256"],
        "extraction_manifest_sha256": extraction["manifest_sha256"],
        "chunks_sha256": chunks_sha256,
        "chunks_uri": f"knowledge://{corpus_id}/{RAG_VERSION}/chunks.jsonl",
        "chunk_count": len(chunks),
        "parent_count": len({str(chunk["parent_id"]) for chunk in chunks}),
        "average_length": sum(int(chunk["token_count"]) for chunk in chunks) / len(chunks),
        "document_frequency": dict(sorted(document_frequency.items())),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest = {**core, "manifest_sha256": canonical_hash(core)}
    atomic_json(manifest_path, manifest)
    return manifest


def _load_index(
    data_dir: Path,
    corpus_id: str,
    *,
    encoder: DenseEncoder = DEFAULT_ENCODER,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    manifest = build_rag_index(data_dir, corpus_id, encoder=encoder)
    path = data_dir / "knowledge" / corpus_id / RAG_VERSION.replace("/", "-") / "chunks.jsonl"
    text = path.read_text(encoding="utf-8")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != manifest["chunks_sha256"]:
        raise ValueError("RAG chunks failed integrity verification")
    return manifest, [json.loads(line) for line in text.splitlines() if line.strip()]


def audit_rag_index(data_dir: Path, corpus_id: str) -> dict[str, object]:
    """Read-only critic that proves every child chunk against its extraction parent."""

    _, _, records = load_extraction(data_dir, corpus_id)
    unit_lookup = {
        str(unit["unit_id"]): str(unit["text"])
        for record in records
        for unit in record.get("units", [])
    }
    _, chunks = _load_index(data_dir, corpus_id)
    identifiers = [str(chunk["id"]) for chunk in chunks]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("RAG index contains duplicate chunk IDs")
    for chunk in chunks:
        source = unit_lookup.get(str(chunk["unit_id"]))
        if source is None:
            raise ValueError(f"RAG chunk {chunk['id']} references a missing extraction unit")
        start, end = int(chunk["char_start"]), int(chunk["char_end"])
        if source[start:end] != chunk["text"]:
            raise ValueError(f"RAG chunk {chunk['id']} has non-reproducible source evidence")
    return {
        "agent": "rag_index_critic",
        "verdict": "pass",
        "checked_chunks": len(chunks),
        "checked_parents": len({str(chunk["parent_id"]) for chunk in chunks}),
    }


def _bm25(
    terms: list[str],
    chunk: dict[str, object],
    document_frequency: dict[str, int],
    count: int,
    average_length: float,
) -> float:
    frequencies = chunk["term_frequency"]
    length = max(1, int(chunk["token_count"]))
    score = 0.0
    for term in terms:
        frequency = int(frequencies.get(term, 0))
        if not frequency:
            continue
        df = int(document_frequency.get(term, 0))
        idf = math.log(1 + (count - df + 0.5) / (df + 0.5))
        denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * length / max(1.0, average_length))
        score += idf * frequency * 2.2 / denominator
    return score


def _decompose(question: str) -> list[str]:
    pieces = [piece.strip() for piece in re.split(r"[?;]|\band\b", question, flags=re.I)]
    useful = [piece for piece in pieces if len(_search_terms(piece)) >= 2]
    return useful[:4] or [question]


def _metadata_match(chunk: dict[str, object], filters: dict[str, object] | None) -> bool:
    if not filters:
        return True
    if filters.get("kind") and chunk["kind"] != filters["kind"]:
        return False
    source_contains = str(filters.get("source_url_contains", "")).casefold()
    return not source_contains or any(
        source_contains in str(url).casefold() for url in chunk.get("source_urls", [])
    )


def _retrieve(
    manifest: dict[str, object],
    chunks: list[dict[str, object]],
    question: str,
    filters: dict[str, object] | None,
    limit: int,
    encoder: DenseEncoder,
) -> list[dict[str, object]]:
    candidates = [chunk for chunk in chunks if _metadata_match(chunk, filters)]
    if not candidates:
        return []
    fused: defaultdict[str, float] = defaultdict(float)
    signals: defaultdict[str, dict[str, float]] = defaultdict(dict)
    by_id = {str(chunk["id"]): chunk for chunk in candidates}
    for subquery in _decompose(question):
        terms = _search_terms(subquery)
        query_vector = encoder.embed(subquery)
        sparse = sorted(
            (
                (
                    _bm25(
                        terms,
                        chunk,
                        manifest["document_frequency"],
                        len(chunks),
                        float(manifest["average_length"]),
                    ),
                    str(chunk["id"]),
                )
                for chunk in candidates
            ),
            reverse=True,
        )[:50]
        dense = sorted(
            ((_cosine(query_vector, encoder.embed(str(chunk["text"]))), str(chunk["id"])) for chunk in candidates),
            reverse=True,
        )[:50]
        for rank, (score, chunk_id) in enumerate(sparse, start=1):
            if score > 0:
                fused[chunk_id] += 1 / (60 + rank)
                signals[chunk_id]["sparse"] = max(score, signals[chunk_id].get("sparse", 0.0))
        for rank, (score, chunk_id) in enumerate(dense, start=1):
            if score > 0:
                fused[chunk_id] += 1 / (60 + rank)
                signals[chunk_id]["dense"] = max(score, signals[chunk_id].get("dense", 0.0))

    query_terms = set(_search_terms(question))
    ranked = []
    for chunk_id, fusion_score in fused.items():
        chunk = by_id[chunk_id]
        chunk_terms = set(chunk["term_frequency"])
        lexical_overlap = len(query_terms & chunk_terms)
        coverage = lexical_overlap / max(1, len(query_terms))
        exact_phrase = 1.0 if " ".join(_tokens(question)) in " ".join(_tokens(str(chunk["text"]))) else 0.0
        rerank_score = fusion_score + 0.08 * coverage + 0.02 * exact_phrase
        ranked.append(
            {
                **chunk,
                "retrieval_score": round(rerank_score, 8),
                "lexical_overlap": lexical_overlap,
                "signals": signals[chunk_id],
            }
        )
    ranked.sort(key=lambda item: (-float(item["retrieval_score"]), str(item["id"])))
    selected = []
    parents: set[str] = set()
    for item in ranked:
        if item["parent_id"] in parents:
            continue
        selected.append(item)
        parents.add(str(item["parent_id"]))
        if len(selected) >= limit:
            break
    return selected


def _verified_citation(item: dict[str, object]) -> dict[str, object]:
    start, end = int(item["char_start"]), int(item["char_end"])
    parent_text = str(item["parent_text"])
    quote = str(item["text"])
    if parent_text[start:end] != quote:
        raise ValueError(f"RAG chunk {item['id']} has non-reproducible evidence")
    return {
        "chunk_id": item["id"],
        "unit_id": item["unit_id"],
        "object_sha256": item["object_sha256"],
        "locator": item["locator"],
        "char_start": start,
        "char_end": end,
        "quote": quote,
        "source_url": (item.get("source_urls") or [None])[0],
        "score": item["retrieval_score"],
    }


def query_rag(
    data_dir: Path,
    corpus_id: str,
    question: str,
    *,
    filters: dict[str, object] | None = None,
    limit: int = 5,
    encoder: DenseEncoder = DEFAULT_ENCODER,
    generator: AnswerGenerator = DEFAULT_GENERATOR,
) -> dict[str, object]:
    if not _search_terms(question):
        return {"method": "rag", "status": "abstained", "answer": None, "citations": [], "reason": "question has no searchable terms"}
    manifest, chunks = _load_index(data_dir, corpus_id, encoder=encoder)
    if manifest["embedding_version"] != encoder.name:
        raise ValueError("configured dense encoder does not match the persisted RAG index")
    selected = _retrieve(manifest, chunks, question, filters, limit, encoder)
    if not selected or int(selected[0]["lexical_overlap"]) == 0:
        return {"method": "rag", "status": "abstained", "answer": None, "citations": [], "reason": "retrieval did not produce grounded lexical evidence"}
    citations = [_verified_citation(item) for item in selected]
    return {
        "method": "rag",
        "status": "answered",
        "answer": generator.generate(question, selected),
        "citations": citations,
        "reason": None,
        "trace": {
            "query_parts": _decompose(question),
            "candidate_chunks": len(chunks),
            "returned_parents": len(selected),
            "index_version": INDEX_VERSION,
            "embedding_version": encoder.name,
            "generator_version": generator.name,
        },
    }
