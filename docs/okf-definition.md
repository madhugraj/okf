# Open Knowledge Format: Definition Workstream

## Status

`PROPOSED` — the project name and intended outcome are confirmed; the exact machine-readable schema requires approval before M5 implementation.

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

The following is illustrative and must not be treated as the accepted schema:

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

## Decisions required before implementation

1. JSON/JSON-LD, RDF or another serialisation strategy
2. Ontology strategy: fixed core, domain extensions, or both
3. Identifier and canonicalisation rules
4. Claim granularity and n-ary relationship support
5. Conflict and temporal version semantics
6. Validation language and schema tooling
7. Compatibility requirements with external knowledge tools
8. Human review and amendment lifecycle

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
