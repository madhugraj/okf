# ADR-0001: Technology Direction and Pilot Order

- Status: Proposed
- Date: 2026-07-21

## Context

The project needs an agentic but controllable workflow for multi-step discovery, recovery and human approval. It also needs two pilot sites that test both initial feasibility and broader generalisation.

## Decision

- Use Python as the backend language.
- Use LangGraph for workflow state, routing, bounded recovery and approval interruption.
- Keep retrieval, browser automation, parsing, hashing and storage in specialised deterministic components.
- Use AISATS as Pilot 1.
- Use Kolte Patil as Pilot 2.
- Limit archive discovery to archive/history structures exposed within each target website.

## Rationale

AISATS provides a smaller initial surface with publicly visible document storage and tender material. Kolte Patil provides a more complex second validation surface. This order reduces initial uncertainty while preventing the system from becoming a single-site crawler.

LangGraph is appropriate for durable state and human-in-the-loop workflow, but using an LLM for deterministic URL, byte-integrity or state-transition decisions would add avoidable variability.

## Consequences

- Graph nodes require explicit typed inputs, outputs and state transitions.
- Site-specific discovery rules must be isolated as adapters and documented.
- A deterministic implementation must exist for every policy and validation control.
- Technology choices below this level remain replaceable behind interfaces.

## Validation

Accept when the M0 reviewer confirms the pilot order, archive boundary, Python baseline and LangGraph's bounded role.
