"""FastAPI application for user-led Stage 1 crawl validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from .knowledge_service import KnowledgeService
from .run_service import QaRunner, RunConfig, RunService, Runner, execute_crawl, execute_qa
from .stage2 import Stage2Service


class CrawlRequest(BaseModel):
    url: str
    allowed_hosts: list[str] = Field(default_factory=list)
    max_pages: int = Field(default=500, ge=1, le=100_000)
    max_depth: int = Field(default=8, ge=0, le=50)
    max_attempts: int = Field(default=3, ge=1, le=10)


class QaExceptionRequest(BaseModel):
    finding_fingerprint: str = Field(min_length=64, max_length=64)
    accepted: bool = False
    reason: str = Field(min_length=20, max_length=2_000)
    residual_risk: str = Field(min_length=10, max_length=2_000)


class ApprovalRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    inventory_reviewed: bool = False
    exceptions_reviewed: bool = False
    robots_reviewed: bool = False
    archive_coverage_reviewed: bool = False
    qa_findings_reviewed: bool = False
    qa_exceptions: list[QaExceptionRequest] = Field(default_factory=list)


class KnowledgeQueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)
    filters: dict[str, object] = Field(default_factory=dict)


class EvaluationCaseRequest(BaseModel):
    id: str | None = Field(default=None, max_length=120)
    question: str = Field(min_length=3, max_length=2_000)
    expected_terms: list[str] = Field(default_factory=list)
    expected_source_urls: list[str] = Field(default_factory=list)
    filters: dict[str, object] = Field(default_factory=dict)


class EvaluationRequest(BaseModel):
    cases: list[EvaluationCaseRequest] = Field(min_length=1, max_length=500)


def create_app(
    *,
    data_dir: Path | None = None,
    runner: Runner = execute_crawl,
    qa_runner: QaRunner = execute_qa,
) -> FastAPI:
    app = FastAPI(title="OKF Corpus and Knowledge Preparation", version="0.8.0")
    static_dir = Path(__file__).with_name("static")
    store = RunService(
        data_dir or Path(os.getenv("OKF_DATA_DIR", ".okf-data")),
        runner=runner,
        qa_runner=qa_runner,
    )
    app.state.run_service = store
    stage2 = Stage2Service(store.data_dir)
    app.state.stage2_service = stage2
    knowledge = KnowledgeService(store.data_dir)
    app.state.knowledge_service = knowledge
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/rag/config")
    def rag_config() -> dict[str, object]:
        return knowledge.rag_config()

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, object]]:
        return store.list_runs()

    @app.get("/api/corpora")
    def list_approved_corpora() -> list[dict[str, object]]:
        return store.list_approved_corpora()

    @app.post("/api/runs", status_code=202)
    def start_run(request: CrawlRequest) -> dict[str, object]:
        try:
            config = RunConfig.create(
                request.url,
                allowed_hosts=tuple(request.allowed_hosts),
                max_pages=request.max_pages,
                max_depth=request.max_depth,
                max_attempts=request.max_attempts,
            )
            return store.start_run(config)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, object]:
        try:
            return store.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="crawl run not found") from exc

    @app.post("/api/runs/{run_id}/verification", status_code=202)
    def start_verification(run_id: str) -> dict[str, object]:
        try:
            return store.start_verification(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="crawl run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/qa", status_code=202)
    def start_qa(run_id: str) -> dict[str, object]:
        try:
            return store.start_qa(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="crawl run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/approval")
    def approve(
        run_id: str,
        request: Annotated[ApprovalRequest, Body()],
    ) -> dict[str, object]:
        try:
            payload = request.model_dump()
            exceptions = payload.pop("qa_exceptions")
            reviewer = payload.pop("reviewer")
            return store.approve(run_id, reviewer, payload, exceptions)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="crawl run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/evidence")
    def evidence(run_id: str) -> JSONResponse:
        try:
            payload = store.evidence(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="crawl run not found") from exc
        return JSONResponse(
            payload,
            headers={"Content-Disposition": f'attachment; filename="okf-crawl-{run_id}.json"'},
        )

    @app.post("/api/corpora/{corpus_id}/stage2/extraction")
    def start_stage2_extraction(corpus_id: str) -> dict[str, object]:
        try:
            return stage2.extract(corpus_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approved corpus snapshot not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/corpora/{corpus_id}/okf/build")
    def start_okf_build(corpus_id: str) -> dict[str, object]:
        try:
            return knowledge.build_okf(corpus_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approved corpus snapshot not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/corpora/{corpus_id}/rag/build")
    def start_rag_build(corpus_id: str) -> dict[str, object]:
        try:
            return knowledge.build_rag(corpus_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approved corpus snapshot not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/corpora/{corpus_id}/compare")
    def compare_knowledge(
        corpus_id: str, request: Annotated[KnowledgeQueryRequest, Body()]
    ) -> dict[str, object]:
        try:
            return knowledge.compare(
                corpus_id,
                request.question,
                filters=request.filters,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approved corpus snapshot not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/corpora/{corpus_id}/evaluate")
    def evaluate_knowledge(
        corpus_id: str, request: Annotated[EvaluationRequest, Body()]
    ) -> dict[str, object]:
        try:
            return knowledge.evaluate(
                corpus_id, [case.model_dump() for case in request.cases]
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approved corpus snapshot not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return app


app = create_app()


def main() -> None:
    uvicorn.run("okf_platform.web:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
