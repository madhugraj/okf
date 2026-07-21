"""Independent hybrid RAG index with parent-child retrieval and citation checks."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Protocol, Sequence

from .knowledge_io import atomic_json, canonical_json_lines, load_extraction, stable_id
from .rag_models import DenseEncoder, Reranker
from .snapshot import canonical_hash
from .vector_store import DenseMatch, DenseVectorStore


RAG_VERSION = "advanced-rag/1.1"
INDEX_VERSION = "hybrid-parent-child-index/2.0"
EMBEDDING_VERSION = "deterministic-feature-hash/1.0"
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{1,}")
STOPWORDS = frozenset(
    "a an and are as at be by for from has have in into is it its of on or that the this to was were will with what which who how when where why".split()
)
VECTOR_SIZE = 256


class AnswerGenerator(Protocol):
    name: str

    def generate(self, question: str, evidence: list[dict[str, object]]) -> str: ...


class FeatureHashEncoder:
    """Provider-free baseline behind the same contract as a learned encoder."""

    name = EMBEDDING_VERSION
    dimensions = VECTOR_SIZE
    minimum_similarity = 0.08

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [_dense_vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return _dense_vector(text)


class HeuristicReranker:
    """Deterministic fallback; production mode uses Qwen3-Reranker."""

    name = "lexical-coverage-reranker/1.0"

    def score(self, question: str, documents: Sequence[str]) -> list[float]:
        query_terms = set(_search_terms(question))
        query_phrase = " ".join(_tokens(question))
        scores = []
        for document in documents:
            terms = set(_search_terms(document))
            coverage = len(query_terms & terms) / max(1, len(query_terms))
            exact = 1.0 if query_phrase and query_phrase in " ".join(_tokens(document)) else 0.0
            scores.append(coverage + 0.1 * exact)
        return scores


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
DEFAULT_RERANKER = HeuristicReranker()
DEFAULT_GENERATOR = ExtractiveAnswerGenerator()


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def _search_terms(text: str) -> list[str]:
    return [token for token in _tokens(text) if token not in STOPWORDS]


def _dense_vector(text: str) -> list[float]:
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
    vector = [0.0] * VECTOR_SIZE
    if magnitude:
        for key, value in values.items():
            vector[key] = value / magnitude
    return vector


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("dense vectors have inconsistent dimensions")
    return sum(a * b for a, b in zip(left, right, strict=True))


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


def _index_dir(data_dir: Path, corpus_id: str, encoder: DenseEncoder) -> Path:
    model_key = stable_id("embedding", encoder.name, encoder.dimensions)
    return data_dir / "knowledge" / corpus_id / RAG_VERSION.replace("/", "-") / model_key


def build_rag_index(
    data_dir: Path,
    corpus_id: str,
    *,
    encoder: DenseEncoder = DEFAULT_ENCODER,
    vector_store: DenseVectorStore | None = None,
) -> dict[str, object]:
    snapshot, extraction, records = load_extraction(data_dir, corpus_id)
    output_dir = _index_dir(data_dir, corpus_id, encoder)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            existing.get("extraction_manifest_sha256") == extraction["manifest_sha256"]
            and existing.get("embedding_version") == encoder.name
            and existing.get("embedding_dimensions") == encoder.dimensions
            and existing.get("vector_backend")
            == (vector_store.name if vector_store else "local-json/1.0")
            and (
                vector_store is None
                or vector_store.count(corpus_id, INDEX_VERSION, encoder.name)
                == existing.get("chunk_count")
            )
        ):
            return existing

    chunks = _build_chunks(records)
    if not chunks:
        raise ValueError("RAG cannot index an extraction with no text units")
    vectors = encoder.embed_documents([str(chunk["text"]) for chunk in chunks])
    if len(vectors) != len(chunks):
        raise ValueError("embedding model did not return one vector per RAG chunk")
    for vector in vectors:
        if len(vector) != encoder.dimensions or any(not math.isfinite(value) for value in vector):
            raise ValueError("embedding model returned an invalid vector")
    if vector_store:
        vector_store.replace(corpus_id, INDEX_VERSION, encoder.name, chunks, vectors)
    else:
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk["embedding"] = vector
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
        "embedding_dimensions": encoder.dimensions,
        "vector_backend": vector_store.name if vector_store else "local-json/1.0",
        "corpus_id": corpus_id,
        "corpus_manifest_sha256": snapshot["manifest_sha256"],
        "extraction_manifest_sha256": extraction["manifest_sha256"],
        "chunks_sha256": chunks_sha256,
        "chunks_uri": (
            f"knowledge://{corpus_id}/{RAG_VERSION}/"
            f"{output_dir.name}/chunks.jsonl"
        ),
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
    vector_store: DenseVectorStore | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    manifest = build_rag_index(
        data_dir, corpus_id, encoder=encoder, vector_store=vector_store
    )
    path = _index_dir(data_dir, corpus_id, encoder) / "chunks.jsonl"
    text = path.read_text(encoding="utf-8")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != manifest["chunks_sha256"]:
        raise ValueError("RAG chunks failed integrity verification")
    return manifest, [json.loads(line) for line in text.splitlines() if line.strip()]


def audit_rag_index(
    data_dir: Path,
    corpus_id: str,
    *,
    encoder: DenseEncoder = DEFAULT_ENCODER,
    vector_store: DenseVectorStore | None = None,
) -> dict[str, object]:
    """Read-only critic that proves every child chunk against its extraction parent."""

    _, _, records = load_extraction(data_dir, corpus_id)
    unit_lookup = {
        str(unit["unit_id"]): str(unit["text"])
        for record in records
        for unit in record.get("units", [])
    }
    manifest, chunks = _load_index(
        data_dir, corpus_id, encoder=encoder, vector_store=vector_store
    )
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
        if vector_store is None:
            vector = chunk.get("embedding")
            if not isinstance(vector, list) or len(vector) != encoder.dimensions:
                raise ValueError(f"RAG chunk {chunk['id']} has no valid local embedding")
    if vector_store and vector_store.count(corpus_id, INDEX_VERSION, encoder.name) != len(chunks):
        raise ValueError("pgvector row count does not match the frozen chunk index")
    return {
        "agent": "rag_index_critic",
        "verdict": "pass",
        "checked_chunks": len(chunks),
        "checked_parents": len({str(chunk["parent_id"]) for chunk in chunks}),
        "embedding_version": encoder.name,
        "embedding_dimensions": encoder.dimensions,
        "vector_backend": manifest["vector_backend"],
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
    reranker: Reranker,
    vector_store: DenseVectorStore | None,
    sparse_candidates: int,
    dense_candidates: int,
    rerank_candidates: int,
) -> list[dict[str, object]]:
    candidates = [chunk for chunk in chunks if _metadata_match(chunk, filters)]
    if not candidates:
        return []
    fused: defaultdict[str, float] = defaultdict(float)
    signals: defaultdict[str, dict[str, float]] = defaultdict(dict)
    by_id = {str(chunk["id"]): chunk for chunk in candidates}
    for subquery in _decompose(question):
        terms = _search_terms(subquery)
        query_vector = encoder.embed_query(subquery)
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
        )[:sparse_candidates]
        if vector_store:
            matches = vector_store.search(
                str(manifest["corpus_id"]),
                str(manifest["index_version"]),
                str(manifest["embedding_version"]),
                query_vector,
                filters=filters,
                limit=dense_candidates,
            )
        else:
            matches = [
                DenseMatch(str(chunk["id"]), _cosine(query_vector, chunk["embedding"]))
                for chunk in candidates
            ]
            matches.sort(key=lambda item: (-item.score, item.chunk_id))
            matches = matches[:dense_candidates]
        for rank, (score, chunk_id) in enumerate(sparse, start=1):
            if score > 0:
                fused[chunk_id] += 1 / (60 + rank)
                signals[chunk_id]["sparse"] = max(score, signals[chunk_id].get("sparse", 0.0))
        for rank, match in enumerate(matches, start=1):
            score, chunk_id = match.score, match.chunk_id
            if chunk_id not in by_id:
                continue
            if score > 0:
                fused[chunk_id] += 1 / (60 + rank)
                signals[chunk_id]["dense"] = max(score, signals[chunk_id].get("dense", 0.0))

    query_terms = set(_search_terms(question))
    fused_candidates = []
    for chunk_id, fusion_score in fused.items():
        chunk = by_id[chunk_id]
        chunk_terms = set(chunk["term_frequency"])
        lexical_overlap = len(query_terms & chunk_terms)
        fused_candidates.append(
            {
                **chunk,
                "fusion_score": round(fusion_score, 8),
                "lexical_overlap": lexical_overlap,
                "signals": signals[chunk_id],
            }
        )
    fused_candidates.sort(
        key=lambda item: (-float(item["fusion_score"]), str(item["id"]))
    )
    rerank_pool = fused_candidates[:rerank_candidates]
    rerank_scores = reranker.score(question, [str(item["text"]) for item in rerank_pool])
    if len(rerank_scores) != len(rerank_pool):
        raise ValueError("reranker did not return one score per candidate")
    ranked = []
    for item, rerank_score in zip(rerank_pool, rerank_scores, strict=True):
        ranked.append(
            {
                **item,
                "reranker_score": round(float(rerank_score), 8),
                "retrieval_score": round(
                    float(rerank_score) + float(item["fusion_score"]), 8
                ),
            }
        )
    ranked.sort(
        key=lambda item: (
            -float(item["reranker_score"]),
            -float(item["fusion_score"]),
            str(item["id"]),
        )
    )
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
    reranker: Reranker = DEFAULT_RERANKER,
    vector_store: DenseVectorStore | None = None,
    generator: AnswerGenerator = DEFAULT_GENERATOR,
    sparse_candidates: int = 40,
    dense_candidates: int = 40,
    rerank_candidates: int = 20,
) -> dict[str, object]:
    if not _search_terms(question):
        return {"method": "rag", "status": "abstained", "answer": None, "citations": [], "reason": "question has no searchable terms"}
    manifest, chunks = _load_index(
        data_dir, corpus_id, encoder=encoder, vector_store=vector_store
    )
    if manifest["embedding_version"] != encoder.name:
        raise ValueError("configured dense encoder does not match the persisted RAG index")
    selected = _retrieve(
        manifest,
        chunks,
        question,
        filters,
        limit,
        encoder,
        reranker,
        vector_store,
        sparse_candidates,
        dense_candidates,
        rerank_candidates,
    )
    grounded = any(
        float(item.get("signals", {}).get("sparse", 0.0)) > 0
        or float(item.get("signals", {}).get("dense", 0.0)) >= encoder.minimum_similarity
        for item in selected
    )
    if not selected or not grounded:
        return {
            "method": "rag",
            "status": "abstained",
            "answer": None,
            "citations": [],
            "reason": "hybrid retrieval did not produce sufficiently grounded evidence",
        }
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
            "embedding_dimensions": encoder.dimensions,
            "vector_backend": manifest["vector_backend"],
            "sparse_retrieval": "BM25",
            "fusion": "reciprocal-rank-fusion",
            "reranker_version": reranker.name,
            "generator_version": generator.name,
        },
    }
