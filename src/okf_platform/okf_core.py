"""Versioned Open Knowledge Format builder and evidence-first query path."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .knowledge_io import atomic_json, load_extraction, stable_id
from .snapshot import canonical_hash


OKF_VERSION = "open-knowledge-format/1.0"
BUILDER_VERSION = "deterministic-okf-builder/1.0"
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{1,}")
ENTITY_RE = re.compile(
    r"\b(?:[A-Z]{2,}(?:[A-Z0-9&/-]*[A-Z0-9])?|[A-Z][a-z]+(?:\s+[A-Z][A-Za-z&/-]+){0,4})\b"
)
SENTENCE_RE = re.compile(r"[^\n.!?]+(?:[.!?]+|$)")
PREDICATE_RE = re.compile(
    r"\b(is|are|was|were|has|have|had|provides?|offers?|operates?|supports?|"
    r"includes?|serves?|handles?|manages?|enables?|requires?)\b",
    re.IGNORECASE,
)
STOPWORDS = frozenset(
    "a an and are as at be by for from has have in into is it its of on or our that the "
    "their this to was were will with you your can may also more information page website".split()
)


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def _entity_type(name: str) -> str:
    if name.isupper():
        return "organization_or_acronym"
    if re.search(r"\b(?:Airport|Airlines?|Limited|Ltd|Corporation|University|Authority)\b", name):
        return "organization"
    return "named_term"


def _temporal_scope(statement: str) -> dict[str, object] | None:
    years = sorted(set(re.findall(r"\b(?:19|20)\d{2}\b", statement)))
    return {"years": years, "interpretation": "mentioned_in_evidence"} if years else None


def _predicate(statement: str) -> tuple[str, str | None, str | None]:
    match = PREDICATE_RE.search(statement)
    if not match:
        return "states", None, None
    subject = statement[: match.start()].strip(" ,:;-—") or None
    object_value = statement[match.end() :].strip(" ,:;-—.") or None
    return match.group(1).lower(), subject, object_value


def _sentences(text: str) -> list[tuple[int, int, str]]:
    values: list[tuple[int, int, str]] = []
    for match in SENTENCE_RE.finditer(text):
        raw = match.group(0)
        leading = len(raw) - len(raw.lstrip())
        statement = raw.strip()
        if 3 <= len(_tokens(statement)) and 12 <= len(statement) <= 800:
            start = match.start() + leading
            values.append((start, start + len(statement), statement))
    return values


def _evidence(
    document_id: str,
    record: dict[str, object],
    unit: dict[str, object],
    start: int,
    end: int,
    quote: str,
) -> dict[str, object]:
    return {
        "document_id": document_id,
        "object_sha256": record["object_sha256"],
        "unit_id": unit["unit_id"],
        "locator": unit["locator"],
        "char_start": start,
        "char_end": end,
        "quote": quote,
        "source_url": (record.get("source_urls") or [None])[0],
    }


def _build_bundle(
    corpus_id: str,
    snapshot: dict[str, object],
    extraction: dict[str, object],
    records: list[dict[str, object]],
) -> dict[str, object]:
    documents: list[dict[str, object]] = []
    claims: list[dict[str, object]] = []
    entity_mentions: dict[str, list[dict[str, object]]] = defaultdict(list)
    entity_names: dict[str, str] = {}
    concept_counts: Counter[str] = Counter()
    relationship_claims: dict[tuple[str, str], set[str]] = defaultdict(set)
    claim_keys: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )

    unit_lookup: dict[str, str] = {}
    for record in records:
        document_id = stable_id("doc", record["object_sha256"])
        documents.append(
            {
                "id": document_id,
                "object_sha256": record["object_sha256"],
                "kind": record["kind"],
                "detected_mime": record["detected_mime"],
                "source_urls": record.get("source_urls", []),
                "extraction_status": record["status"],
            }
        )
        for unit in record.get("units", []):
            unit_lookup[str(unit["unit_id"])] = str(unit["text"])
            for start, end, statement in _sentences(str(unit["text"])):
                evidence = _evidence(document_id, record, unit, start, end, statement)
                mentioned_ids: list[str] = []
                for match in ENTITY_RE.finditer(statement):
                    name = match.group(0).strip()
                    if name.lower() in STOPWORDS:
                        continue
                    canonical = re.sub(r"\s+", " ", name).casefold()
                    entity_id = stable_id("ent", canonical)
                    entity_names.setdefault(entity_id, name)
                    entity_mentions[entity_id].append(
                        {
                            "claim_quote": statement,
                            "document_id": document_id,
                            "unit_id": unit["unit_id"],
                            "char_start": start + match.start(),
                            "char_end": start + match.end(),
                        }
                    )
                    mentioned_ids.append(entity_id)

                meaningful = [token for token in _tokens(statement) if token not in STOPWORDS]
                concept_counts.update(set(meaningful))
                predicate, subject_text, object_text = _predicate(statement)
                claim_id = stable_id(
                    "claim", record["object_sha256"], unit["unit_id"], start, statement
                )
                unique_entities = sorted(set(mentioned_ids))
                claim = {
                    "id": claim_id,
                    "statement": statement,
                    "predicate": predicate,
                    "arguments": {
                        "subject_text": subject_text,
                        "object_text": object_text,
                        "entity_ids": unique_entities,
                    },
                    "temporal_scope": _temporal_scope(statement),
                    "evidence": [evidence],
                    "status": "machine_extracted",
                    "validation": "exact_evidence_verified",
                    "extraction_method": BUILDER_VERSION,
                    "confidence": None,
                }
                claims.append(claim)
                for index, left in enumerate(unique_entities):
                    for right in unique_entities[index + 1 :]:
                        relationship_claims[(left, right)].add(claim_id)
                if subject_text and object_text and predicate != "states":
                    key = (" ".join(_tokens(subject_text)), predicate)
                    claim_keys[key][" ".join(_tokens(object_text))].append(claim_id)

    entities = [
        {
            "id": entity_id,
            "canonical_name": entity_names[entity_id],
            "canonical_key": re.sub(r"\s+", " ", entity_names[entity_id]).casefold(),
            "type": _entity_type(entity_names[entity_id]),
            "mentions": sorted(
                mentions, key=lambda item: (str(item["document_id"]), str(item["unit_id"]))
            ),
            "status": "machine_extracted",
        }
        for entity_id, mentions in entity_mentions.items()
    ]
    concepts = [
        {
            "id": stable_id("concept", label),
            "label": label,
            "mention_count": count,
            "status": "machine_extracted",
        }
        for label, count in concept_counts.most_common(250)
        if count >= 2
    ]
    relationships = [
        {
            "id": stable_id("rel", left, "co_occurs_with", right),
            "source_entity_id": left,
            "type": "co_occurs_with",
            "target_entity_id": right,
            "supporting_claim_ids": sorted(claim_ids),
        }
        for (left, right), claim_ids in relationship_claims.items()
    ]
    conflicts = []
    for (subject, predicate), objects in claim_keys.items():
        nonempty = {value: ids for value, ids in objects.items() if value}
        if len(nonempty) > 1:
            conflicts.append(
                {
                    "id": stable_id("conflict", subject, predicate, *sorted(nonempty)),
                    "subject_key": subject,
                    "predicate": predicate,
                    "alternatives": [
                        {"object_key": value, "claim_ids": sorted(ids)}
                        for value, ids in sorted(nonempty.items())
                    ],
                    "status": "potential_conflict_requires_review",
                }
            )

    bundle: dict[str, object] = {
        "okf_version": OKF_VERSION,
        "builder_version": BUILDER_VERSION,
        "corpus": {
            "id": corpus_id,
            "snapshot_sha256": snapshot["manifest_sha256"],
            "extraction_manifest_sha256": extraction["manifest_sha256"],
            "target_url": snapshot["target_url"],
            "approved_at": snapshot["approved_at"],
            "approved_by": snapshot["approved_by"],
        },
        "documents": sorted(documents, key=lambda item: str(item["id"])),
        "entities": sorted(entities, key=lambda item: str(item["id"])),
        "concepts": sorted(concepts, key=lambda item: str(item["id"])),
        "claims": sorted(claims, key=lambda item: str(item["id"])),
        "relationships": sorted(relationships, key=lambda item: str(item["id"])),
        "conflicts": sorted(conflicts, key=lambda item: str(item["id"])),
        "extensions": {},
    }
    validate_bundle(bundle, unit_lookup)
    return bundle


def validate_bundle(bundle: dict[str, object], unit_lookup: dict[str, str]) -> None:
    """Reject malformed IDs, duplicate records, or evidence that cannot be reproduced."""

    if bundle.get("okf_version") != OKF_VERSION:
        raise ValueError("unsupported OKF version")
    for collection_name in ("documents", "entities", "concepts", "claims", "relationships"):
        collection = bundle.get(collection_name)
        if not isinstance(collection, list):
            raise ValueError(f"OKF {collection_name} must be a list")
        identifiers = [str(item.get("id", "")) for item in collection]
        if any(not identifier for identifier in identifiers) or len(set(identifiers)) != len(
            identifiers
        ):
            raise ValueError(f"OKF {collection_name} contains missing or duplicate IDs")
    for claim in bundle["claims"]:
        for evidence in claim.get("evidence", []):
            unit_id = str(evidence["unit_id"])
            text = unit_lookup.get(unit_id)
            if text is None:
                raise ValueError(f"claim references missing extraction unit {unit_id}")
            start, end = int(evidence["char_start"]), int(evidence["char_end"])
            if text[start:end] != evidence["quote"]:
                raise ValueError(f"claim {claim['id']} has non-reproducible evidence")


def build_okf(data_dir: Path, corpus_id: str) -> dict[str, object]:
    snapshot, extraction, records = load_extraction(data_dir, corpus_id)
    output_dir = data_dir / "knowledge" / corpus_id / OKF_VERSION.replace("/", "-")
    manifest_path = output_dir / "manifest.json"
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("extraction_manifest_sha256") == extraction["manifest_sha256"]:
            return existing

    bundle = _build_bundle(corpus_id, snapshot, extraction, records)
    bundle_text = json.dumps(bundle, sort_keys=True, separators=(",", ":"))
    bundle_sha256 = hashlib.sha256(bundle_text.encode("utf-8")).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / "bundle.json"
    temporary = bundle_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    temporary.replace(bundle_path)
    core: dict[str, object] = {
        "schema_version": "okf-build-manifest/1.0",
        "okf_version": OKF_VERSION,
        "builder_version": BUILDER_VERSION,
        "corpus_id": corpus_id,
        "corpus_manifest_sha256": snapshot["manifest_sha256"],
        "extraction_manifest_sha256": extraction["manifest_sha256"],
        "bundle_sha256": bundle_sha256,
        "bundle_uri": f"knowledge://{corpus_id}/{OKF_VERSION}/bundle.json",
        "counts": {
            key: len(bundle[key])
            for key in ("documents", "entities", "concepts", "claims", "relationships", "conflicts")
        },
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest = {**core, "manifest_sha256": canonical_hash(core)}
    atomic_json(manifest_path, manifest)
    return manifest


def load_okf_bundle(data_dir: Path, corpus_id: str) -> dict[str, object]:
    manifest = build_okf(data_dir, corpus_id)
    path = data_dir / "knowledge" / corpus_id / OKF_VERSION.replace("/", "-") / "bundle.json"
    raw = path.read_text(encoding="utf-8")
    compact = json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(compact.encode("utf-8")).hexdigest() != manifest["bundle_sha256"]:
        raise ValueError("OKF bundle failed integrity verification")
    return json.loads(raw)


def audit_okf(data_dir: Path, corpus_id: str) -> dict[str, object]:
    """Read-only critic that independently reproduces every claim evidence span."""

    _, _, records = load_extraction(data_dir, corpus_id)
    unit_lookup = {
        str(unit["unit_id"]): str(unit["text"])
        for record in records
        for unit in record.get("units", [])
    }
    bundle = load_okf_bundle(data_dir, corpus_id)
    validate_bundle(bundle, unit_lookup)
    evidence_count = sum(len(claim.get("evidence", [])) for claim in bundle["claims"])
    return {
        "agent": "okf_evidence_critic",
        "verdict": "pass",
        "checked_claims": len(bundle["claims"]),
        "checked_evidence_spans": evidence_count,
        "potential_conflicts": len(bundle["conflicts"]),
    }


def query_okf(data_dir: Path, corpus_id: str, question: str, *, limit: int = 5) -> dict[str, object]:
    query_terms = set(_tokens(question)) - STOPWORDS
    if not query_terms:
        return {"method": "okf", "status": "abstained", "answer": None, "citations": [], "reason": "question has no searchable terms"}
    bundle = load_okf_bundle(data_dir, corpus_id)
    entity_names = {
        str(item["id"]): set(_tokens(str(item["canonical_name"]))) for item in bundle["entities"]
    }
    scored: list[tuple[float, dict[str, object]]] = []
    for claim in bundle["claims"]:
        statement_terms = set(_tokens(str(claim["statement"])))
        overlap = query_terms & statement_terms
        if not overlap:
            continue
        coverage = len(overlap) / len(query_terms)
        entity_boost = sum(
            0.12 for entity_id in claim["arguments"]["entity_ids"] if query_terms & entity_names.get(entity_id, set())
        )
        phrase_boost = 0.15 if " ".join(_tokens(question)) in " ".join(_tokens(str(claim["statement"]))) else 0.0
        scored.append((coverage + entity_boost + phrase_boost, claim))
    scored.sort(key=lambda item: (-item[0], str(item[1]["id"])))
    selected = scored[:limit]
    if not selected or selected[0][0] < 0.18:
        return {"method": "okf", "status": "abstained", "answer": None, "citations": [], "reason": "no sufficiently grounded OKF claim"}
    citations = [
        {
            "claim_id": claim["id"],
            "score": round(score, 6),
            **claim["evidence"][0],
        }
        for score, claim in selected
    ]
    answer_statements = [str(claim["statement"]) for _, claim in selected[:3]]
    return {
        "method": "okf",
        "status": "answered",
        "answer": " ".join(dict.fromkeys(answer_statements)),
        "citations": citations,
        "reason": None,
        "trace": {"candidate_claims": len(scored), "returned_claims": len(selected)},
    }
