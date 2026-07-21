# Open Knowledge Format: Definition Workstream

## Status

`IMPLEMENTED BASELINE` — OKF 1.0 is implemented as deterministic JSON with a published JSON Schema and runtime evidence validation. Domain and model-assisted extensions remain versioned future work.

## Working definition

For this project, Open Knowledge Format is a portable, machine-readable representation of knowledge extracted from an approved corpus. It must preserve claims, concepts, entities, relationships and provenance while allowing validation, versioning and comparison with RAG.

This is a project working definition, not a claim that an external standard has already been selected.

## Minimum record requirements

An OKF design candidate must represent:

- corpus and document identity;
- source URL, retrieval timestamp and content hash;
- page/section/span provenance;
- entities and canonical identifiers;
- concepts and classifications;
- atomic claims or propositions;
- typed relationships;
- temporal scope and document version;
- extraction method and configuration version;
- confidence or validation status without presenting confidence as truth;
- conflicts, supersession and human review state;
- language and content licence/usage metadata where known.

## Candidate shape

The following is a shortened illustration. The normative machine-readable contract is `schemas/okf-1.0.schema.json`.

```json
{
  "okf_version": "0.1-draft",
  "corpus": {"id": "corpus-v1"},
  "documents": [],
  "entities": [],
  "claims": [
    {
      "id": "claim-001",
      "subject": "entity-001",
      "predicate": "relationship-type",
      "object": "entity-002",
      "provenance": [
        {"document_id": "doc-001", "page": 7, "span": "..."}
      ],
      "status": "machine_extracted"
    }
  ]
}
```

## Implemented decisions

1. Canonical JSON 1.0 is the portable baseline; JSON-LD/RDF exporters can be added without changing record identity.
2. The format has a fixed evidence-first core plus an `extensions` object for versioned domains.
3. Stable identifiers are SHA-256-derived from canonical source evidence and normalized values.
4. Claims are atomic evidence sentences with typed arguments and zero or more entity references.
5. Conflicting propositions coexist and are emitted as potential-conflict review records; history is not overwritten.
6. JSON Schema documents structure; runtime validation additionally proves every quoted evidence span against Stage 2 text.
7. External graph compatibility is an exporter concern rather than a core-storage dependency.
8. Machine-extracted records remain visibly labelled; future human decisions must be append-only amendments.

## Acceptance criteria for the format

- Every accepted claim is traceable to source evidence.
- The format validates deterministically against a versioned schema.
- Conflicting claims can coexist without silent overwrite.
- A newer document version does not destroy historical provenance.
- Domain extensions do not break the core format.
- The same corpus can be regenerated reproducibly from recorded pipeline versions.
- Query results can cite the exact supporting document location.

## Research comparison rule

OKF and RAG must answer from the same approved corpus snapshot. OKF receives no additional manual knowledge that is unavailable to RAG unless that intervention is explicitly measured as part of the experiment.
