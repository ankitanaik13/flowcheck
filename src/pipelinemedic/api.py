import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import date as Date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ARTIFACTS, ROOT
from .detection import CALIBRATION_END, TRAIN_END, daily_history
from .pipeline import LINEAGE, SCENARIOS, batch_dates, manifest
from .service import RunStore


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str = "join_fanout"
    date: Date = Date(2011, 10, 5)
    seed: int = Field(default=42, ge=0, le=1_000_000)
    severity: float = Field(default=0.3, ge=0.05, le=0.8)
    mode: str = "offline"


def create_app(store=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = store or RunStore()
        yield
        if store is None:
            app.state.store.close()

    app = FastAPI(title="FlowCheck", version="1.0.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}, 422)

    @app.middleware("http")
    async def protection(request: Request, call_next):
        request_id = str(uuid.uuid4())
        token = os.environ.get("PIPELINEMEDIC_TOKEN")
        if token and request.url.path.startswith("/api/"):
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
            if not secrets.compare_digest(supplied, token):
                return JSONResponse({"detail": "Authentication required"}, 401)
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Cross-origin writes are not allowed"}, 403)
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "Invalid content length"}, 400)
            if length > 8192:
                return JSONResponse({"detail": "Request too large"}, 413)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "dataset_ready": (ROOT / "data/processed/manifest.json").exists()}

    @app.get("/api/overview")
    def overview():
        try:
            history = daily_history()
            return {
                "dataset": manifest(),
                "history": history.to_dict(orient="records"),
                "dates": [d for d in batch_dates() if "2011-09-01" <= d <= "2011-11-30"],
                "scenarios": [{"id": k, "name": v[0], "description": v[1]} for k, v in SCENARIOS.items()],
                "lineage": LINEAGE,
                "train_end": TRAIN_END,
                "calibration_end": CALIBRATION_END,
                "modes": [
                    {"id": "offline", "label": "Offline · deterministic policy"},
                    {"id": "ollama", "label": "Live LLM · Ollama required"},
                ],
            }
        except FileNotFoundError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/runs", status_code=202)
    def create_run(body: RunRequest, request: Request):
        if body.scenario not in SCENARIOS or body.mode not in {"offline", "ollama"}:
            raise HTTPException(422, "Unknown scenario or investigator mode")
        day = body.date.isoformat()
        if not "2011-09-01" <= day <= "2011-11-30" or day not in batch_dates():
            raise HTTPException(422, "Choose an available held-out batch from September–November 2011")
        key = request.headers.get("idempotency-key")
        if key and len(key) > 128:
            raise HTTPException(422, "Idempotency key too long")
        try:
            return {"id": app.state.store.create(body.model_dump(mode="json"), key)}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(429, str(exc)) from exc

    @app.get("/api/runs")
    def runs():
        return app.state.store.list()

    def valid_id(run_id):
        try:
            return str(uuid.UUID(run_id))
        except ValueError as exc:
            raise HTTPException(422, "Invalid run identifier") from exc

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        try:
            return app.state.store.get(valid_id(run_id))
        except KeyError as exc:
            raise HTTPException(404, "Run not found") from exc

    @app.post("/api/runs/{run_id}/{action}")
    def transition(run_id: str, action: str):
        try:
            return app.state.store.transition(valid_id(run_id), action)
        except KeyError as exc:
            raise HTTPException(404, "Run not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/runs/{run_id}/export")
    def export(run_id: str):
        run = get_run(run_id)
        return Response(
            json.dumps(run, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="incident-{run["id"][:8]}.json"'},
        )

    @app.get("/api/benchmark")
    def benchmark():
        path = ARTIFACTS / "benchmark.json"
        return json.loads(path.read_text()) if path.exists() else {"available": False}

    @app.get("/api/report")
    def report():
        path = ROOT / "docs/PipelineMedic-Report.pdf"
        if not path.exists():
            raise HTTPException(404, "Report has not been generated yet")
        return FileResponse(path, filename=path.name)

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    return app


app = create_app()
