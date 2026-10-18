import asyncio
from contextlib import asynccontextmanager
import logging
import time
from uuid import UUID, uuid4
from fastapi import FastAPI, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPBearer
from starlette.exceptions import HTTPException
from .auth import authenticate
from .config import Config
from .errors import LabError, MESSAGES
from .models import RunCreate, IncidentCreate, EventCreate, Version, Question, RunRecord, IncidentRecord, SupportAnswer
from .runs import Runs, stamp
from .storage import Storage
from .incidents import Incidents
from .runbooks import snapshot
from .retrieval import answer
from .safety import strict_json, free_text, canonical
from .triage import CATEGORIES
from .bundles import bundle, markdown

log = logging.getLogger("lab")


class SafeLibraryLog(logging.Filter):
    def filter(self, record):
        record.msg, record.args, record.exc_info = "HTTP library diagnostic omitted.", (), None
        record.exc_text = None
        return True



def error_response(exc, request_id):
    return JSONResponse({"error": {"code": exc.code, "message": MESSAGES[exc.code], "request_id": request_id, "details": exc.details}}, status_code=exc.status,
                        headers={"X-Request-ID": request_id, **({"WWW-Authenticate": "Bearer"} if exc.status == 401 else {})})


class Boundary:
    def __init__(self, app, config):
        self.app, self.config = app, config

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id, start, role, status = str(uuid4()), time.monotonic(), None, 500
        started = False
        scope.setdefault("state", {})["request_id"] = request_id
        try:
            headers = scope["headers"]
            if any(k.lower() == b"origin" for k, _ in headers):
                raise LabError("BROWSER_ORIGIN_DENIED", 403)
            hosts = [v for k, v in headers if k.lower() == b"host"]
            if hosts != [f"127.0.0.1:{self.config.port}".encode()]:
                raise LabError("INVALID_HOST", 400)
            if scope["path"] not in ("/healthz", "/docs", "/redoc"):
                role = authenticate(headers, self.config.tokens)
                scope["state"]["role"] = role
                if scope["method"] not in ("GET", "HEAD") and scope["path"] != "/v1/support/ask":
                    if role == "reader" or (scope["path"] == "/v1/runs" and self.config.mode == "live" and role != "admin"):
                        raise LabError("LOCAL_FORBIDDEN", 403)
            chunks, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                part = message.get("body", b"")
                size += len(part)
                if size > 16384:
                    raise LabError("BODY_TOO_LARGE", 413)
                chunks.append(part)
                if not message.get("more_body", False):
                    break
            body = b"".join(chunks)
            if scope["method"] == "GET" and body:
                raise LabError("GET_BODY_DENIED", 400)
            if scope["method"] in ("POST", "PUT", "PATCH"):
                types = [v for k, v in headers if k.lower() == b"content-type"]
                if len(types) != 1 or types[0].split(b";")[0].strip().lower() != b"application/json":
                    raise LabError("UNSUPPORTED_MEDIA_TYPE", 415)
                try:
                    strict_json(body.decode("utf-8"))
                except (ValueError, UnicodeError, RecursionError):
                    raise LabError("INVALID_JSON", 400) from None
            from urllib.parse import parse_qsl
            pairs = parse_qsl(scope.get("query_string", b"").decode("latin1"), keep_blank_values=True)
            allowed = {"limit", "offset"} if scope["path"] in ("/v1/runs", "/v1/incidents") and scope["method"] == "GET" else {"format"} if scope["path"].endswith("/bundle") else set()
            if any(k not in allowed for k, _ in pairs) or len({k for k, _ in pairs}) != len(pairs):
                raise LabError("INVALID_INPUT")
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            async def safe_send(message):
                nonlocal status, started
                if message["type"] == "http.response.start":
                    status = message["status"]
                    started = True
                    message["headers"].append((b"x-request-id", request_id.encode()))
                await send(message)

            await self.app(scope, replay, safe_send)
        except LabError as exc:
            status = exc.status
            await error_response(exc, request_id)(scope, receive, send)
        except Exception:
            status = 500
            if not started:
                await error_response(LabError("INTERNAL_ERROR", 500), request_id)(scope, receive, send)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            method = scope["method"] if scope["method"] in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS") else "OTHER"
            log.info("request=%s route=%s method=%s status=%d duration_ms=%d role=%s observation=%s", request_id, route, method, status, int((time.monotonic() - start) * 1000), role, scope["state"].get("observation_code"))


def valid_id(value):
    try:
        if str(UUID(value)) != value.lower():
            raise ValueError()
        return str(UUID(value))
    except ValueError:
        raise LabError("INVALID_INPUT") from None


def create_app(config=None, *, clock=None, monotonic=None, uuid=None, transport=None):
    config = config or Config.load()
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.WARNING)
        logger.propagate = False
        if not any(isinstance(item, logging.NullHandler) for item in logger.handlers):
            logger.addHandler(logging.NullHandler())
        if not any(isinstance(item, SafeLibraryLog) for item in logger.filters):
            logger.addFilter(SafeLibraryLog())
    storage = Storage(config.root / ".local/state.sqlite3")
    kwargs = {k: v for k, v in {"clock": clock, "monotonic": monotonic, "uuid": uuid, "transport": transport}.items() if v is not None}
    runs = Runs(config, storage, **kwargs)
    incidents = Incidents(storage, runs.clock, runs.uuid, config.secrets)

    @asynccontextmanager
    async def lifespan(_):
        await asyncio.to_thread(storage.initialize)
        await asyncio.to_thread(storage.recover, stamp(runs.clock))
        yield

    app = FastAPI(title="Synthetic Langdock Support Lab", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.runs, app.state.storage, app.state.incidents = runs, storage, incidents
    app.add_middleware(Boundary, config=config)
    security = HTTPBearer(auto_error=False)

    @app.exception_handler(LabError)
    async def lab_error(request, exc):
        return error_response(exc, request.state.request_id)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        return error_response(LabError("INTERNAL_ERROR", 500), request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Field locations may contain attacker-controlled unknown keys. Fixed reason only.
        return error_response(LabError("INVALID_INPUT", details=[{"field": "request", "reason": "invalid"}]), request.state.request_id)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(LabError("NOT_FOUND", exc.status_code), request.state.request_id)

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/openapi.json", dependencies=[Depends(security)])
    async def schema():
        return app.openapi()

    @app.get("/v1/scenarios", dependencies=[Depends(security)])
    async def scenarios():
        return {"items": sorted(runs.scenarios, key=lambda row: row["id"])}

    @app.post("/v1/runs", response_model=RunRecord, status_code=201, dependencies=[Depends(security)])
    async def create_run(body: RunCreate, request: Request):
        result = await runs.create(body)
        request.state.observation_code = result["observation"]["code"]
        return result

    @app.get("/v1/runs", dependencies=[Depends(security)])
    async def list_runs(limit: int = 50, offset: int = 0):
        return await listing("runs", limit, offset)

    async def listing(kind, limit, offset):
        if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise LabError("INVALID_INPUT")
        return await asyncio.to_thread(storage.listing, kind, limit, offset)

    @app.get("/v1/runs/{run_id}", response_model=RunRecord, dependencies=[Depends(security)])
    async def get_run(run_id: str):
        return await asyncio.to_thread(storage.run, valid_id(run_id))

    @app.post("/v1/incidents", response_model=IncidentRecord, status_code=201, dependencies=[Depends(security)])
    async def create_incident(body: IncidentCreate, request: Request):
        return await asyncio.to_thread(incidents.create, body, request.state.role)

    @app.get("/v1/incidents", dependencies=[Depends(security)])
    async def list_incidents(limit: int = 50, offset: int = 0):
        return await listing("incidents", limit, offset)

    @app.get("/v1/incidents/{incident_id}", response_model=IncidentRecord, dependencies=[Depends(security)])
    async def get_incident(incident_id: str):
        return await asyncio.to_thread(storage.incident, valid_id(incident_id))

    @app.post("/v1/incidents/{incident_id}/events", response_model=IncidentRecord, dependencies=[Depends(security)])
    async def event(incident_id: str, body: EventCreate, request: Request):
        return await asyncio.to_thread(incidents.update, valid_id(incident_id), body, request.state.role)

    def books():
        return snapshot(config.root, runs.clock(), config.secrets)[0]

    @app.post("/v1/incidents/{incident_id}/triage", response_model=IncidentRecord, dependencies=[Depends(security)])
    async def triage(incident_id: str, body: Version, request: Request):
        current = await asyncio.to_thread(books)
        return await asyncio.to_thread(incidents.update, valid_id(incident_id), body, request.state.role, current)

    @app.get("/v1/incidents/{incident_id}/bundle", dependencies=[Depends(security)])
    async def export(incident_id: str, format: str = "json"):
        if format not in ("json", "markdown"):
            raise LabError("INVALID_INPUT")
        data = await asyncio.to_thread(bundle, storage, valid_id(incident_id))
        item = data["incident"]
        ext = "json" if format == "json" else "md"
        return Response(canonical(data) if ext == "json" else markdown(data), media_type="application/json" if ext == "json" else "text/markdown", headers={"Content-Disposition": f'attachment; filename="incident-{item["id"]}-v{item["version"]}.{ext}"'})

    @app.get("/v1/runbooks", dependencies=[Depends(security)])
    async def list_books():
        current = await asyncio.to_thread(books)
        return {"items": [{k: b[k] for k in ("id", "title", "category", "sha256", "review")} for b in current.values()]}

    @app.get("/v1/runbooks/{book_id}", dependencies=[Depends(security)])
    async def get_book(book_id: str):
        current = await asyncio.to_thread(books)
        if book_id not in current:
            raise LabError("NOT_FOUND", 404)
        return current[book_id]

    @app.post("/v1/support/ask", response_model=SupportAnswer, dependencies=[Depends(security)])
    async def ask(body: Question):
        free_text(body.question, config.secrets)
        category = None
        if body.incident_id:
            item = await asyncio.to_thread(storage.incident, body.incident_id)
            if item["triage"]:
                category = "success" if item["triage"]["recommended_action"] == "verify_recovery" else next((CATEGORIES[c] for c in reversed(item["triage"]["observed_codes"]) if c in CATEGORIES), None)
        current = await asyncio.to_thread(books)
        return answer(body.question, current, category)

    return app
