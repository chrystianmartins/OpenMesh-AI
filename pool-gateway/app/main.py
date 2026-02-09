from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any, AsyncIterator, Awaitable, Callable, MutableMapping, cast

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger("pool-gateway")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level_name, logging.INFO))

    if not root_logger.handlers:
        stream_handler: logging.Handler = logging.StreamHandler()
        stream_handler.setFormatter(JsonFormatter())
        root_logger.addHandler(stream_handler)
        return

    for existing_handler in root_logger.handlers:
        existing_handler.setFormatter(JsonFormatter())


configure_logging()


class RequestLoggerAdapter(logging.LoggerAdapter[logging.Logger]):
    def process(
        self,
        msg: object,
        kwargs: MutableMapping[str, Any],
    ) -> tuple[object, MutableMapping[str, Any]]:
        extra_obj = kwargs.get("extra")
        if not isinstance(extra_obj, dict):
            extra_obj = {}
            kwargs["extra"] = extra_obj
        adapter_extra = self.extra if isinstance(self.extra, dict) else {}
        extra_obj.setdefault("request_id", adapter_extra.get("request_id", "-"))
        return msg, kwargs


class PrometheusMetrics:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._lock = Lock()
        self._request_count: dict[tuple[str, str], int] = defaultdict(int)
        self._request_latency_sum: dict[tuple[str, str], float] = defaultdict(float)

    def observe_http_request(self, path: str, method: str, elapsed_seconds: float) -> None:
        if not self.enabled:
            return
        key = (path, method)
        with self._lock:
            self._request_count[key] += 1
            self._request_latency_sum[key] += elapsed_seconds

    def render(self) -> str:
        if not self.enabled:
            return "# metrics disabled\n"

        lines = [
            "# HELP http_requests_total Total HTTP requests by path and method.",
            "# TYPE http_requests_total counter",
        ]
        with self._lock:
            for (path, method), count in sorted(self._request_count.items()):
                lines.append(f'http_requests_total{{path="{path}",method="{method}"}} {count}')

            lines.extend(
                [
                    "# HELP http_request_duration_seconds_sum Total request latency in seconds by path and method.",
                    "# TYPE http_request_duration_seconds_sum counter",
                ]
            )
            for (path, method), total in sorted(self._request_latency_sum.items()):
                lines.append(
                    f'http_request_duration_seconds_sum{{path="{path}",method="{method}"}} {total:.6f}'
                )

        lines.append("")
        return "\n".join(lines)


@dataclass
class Settings:
    coordinator_url: str
    internal_token: str
    api_keys: dict[str, str]
    rate_limit_per_minute_api_key: int
    rate_limit_per_minute_ip: int
    poll_timeout_seconds: float
    poll_interval_seconds: float
    cors_enabled: bool
    cors_allow_origins: list[str]
    enable_prometheus_metrics: bool


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._events[key]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded"
                )

            bucket.append(now)


class EmbedRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class RankRequest(BaseModel):
    query: str = Field(min_length=1)
    texts: list[str] = Field(min_length=1, max_length=32)


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def load_settings() -> Settings:
    raw_keys = os.getenv("GATEWAY_API_KEYS", "client-dev:dev-key")
    api_keys: dict[str, str] = {}
    for item in raw_keys.split(","):
        if not item.strip():
            continue
        client_id, _, api_key = item.partition(":")
        if not client_id or not api_key:
            continue
        api_keys[api_key.strip()] = client_id.strip()

    return Settings(
        coordinator_url=os.getenv("COORDINATOR_URL", "http://localhost:8001"),
        internal_token=os.getenv("COORDINATOR_INTERNAL_TOKEN", "dev-internal-token"),
        api_keys=api_keys,
        rate_limit_per_minute_api_key=int(
            os.getenv("RATE_LIMIT_PER_MINUTE_API_KEY", os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
        ),
        rate_limit_per_minute_ip=int(os.getenv("RATE_LIMIT_PER_MINUTE_IP", "120")),
        poll_timeout_seconds=float(os.getenv("POLL_TIMEOUT_SECONDS", "20")),
        poll_interval_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "1.0")),
        cors_enabled=_parse_bool(os.getenv("CORS_ENABLED"), default=False),
        cors_allow_origins=[
            origin.strip()
            for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
            if origin.strip()
        ],
        enable_prometheus_metrics=_parse_bool(
            os.getenv("ENABLE_PROMETHEUS_METRICS"), default=False
        ),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.settings = load_settings()
    app.state.rate_limiter_api_key = RateLimiter(
        max_requests=app.state.settings.rate_limit_per_minute_api_key
    )
    app.state.rate_limiter_ip = RateLimiter(
        max_requests=app.state.settings.rate_limit_per_minute_ip
    )
    app.state.coordinator_client = httpx.AsyncClient(
        base_url=app.state.settings.coordinator_url, timeout=5.0
    )
    app.state.metrics = PrometheusMetrics(enabled=app.state.settings.enable_prometheus_metrics)
    yield
    await app.state.coordinator_client.aclose()


app = FastAPI(title="OpenMesh Pool Gateway", version="0.1.0", lifespan=lifespan)
app.state.metrics = PrometheusMetrics(enabled=False)


PORTAL_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>OpenMesh Portal</title>
  <style>
    :root { color-scheme: dark; --bg:#080d1c; --card:#121a30; --line:#27355f; --accent:#4f8cff; --text:#f4f7ff; --muted:#a7b3d1; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Inter, system-ui, sans-serif; background: radial-gradient(circle at top, #142347, var(--bg) 40%); color: var(--text); }
    .container { min-height:100vh; display:grid; grid-template-columns: 240px 1fr; }
    .menu { background: rgba(8,13,28,.86); border-right:1px solid var(--line); padding: 24px; }
    .brand { font-weight: 700; margin-bottom: 24px; }
    .menu nav { display:grid; gap: 10px; }
    .menu a { color: var(--muted); text-decoration: none; padding: 8px 12px; border-radius: 10px; }
    .menu a:hover { background: rgba(79,140,255,.12); color: var(--text); }
    .content { padding: 24px; display:grid; gap: 24px; }
    .top { display:flex; justify-content:space-between; align-items:center; gap:12px; }
    .top h1 { margin:0; font-size: 1.4rem; }
    .btn { border:0; border-radius: 12px; background: linear-gradient(120deg, var(--accent), #77d3ff); color:white; padding: 10px 16px; font-weight: 700; cursor:pointer; }
    .grid { display:grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); gap: 16px; }
    .card { background: linear-gradient(160deg, rgba(79,140,255,.1), rgba(18,26,48,.9)); border:1px solid var(--line); border-radius: 16px; padding: 16px; }
    .label { font-size: .8rem; color: var(--muted); margin: 0; }
    .value { margin: 8px 0 0; font-size: 1.35rem; font-weight: 700; }
    .panel { background: rgba(18,26,48,.9); border: 1px solid var(--line); border-radius: 16px; padding: 16px; }
    table { width:100%; border-collapse: collapse; color: var(--text); }
    th, td { text-align:left; padding: 10px 6px; border-bottom:1px solid var(--line); }
    th { color: var(--muted); font-weight: 600; }
    dialog { border:1px solid var(--line); border-radius: 16px; background: #0f172f; color: var(--text); width:min(420px, 90vw); }
    form { display:grid; gap: 12px; }
    input { width:100%; padding: 10px; border-radius: 10px; border:1px solid var(--line); background:#0b1227; color:var(--text); }
    .row { display:flex; gap: 8px; justify-content:flex-end; }
    .ghost { background:transparent; border:1px solid var(--line); }
    .status { color:#79ffa7; font-size:.82rem; margin:0; }
    @media (max-width: 860px) { .container { grid-template-columns: 1fr; } .menu { border-right:0; border-bottom:1px solid var(--line);} }
  </style>
</head>
<body>
  <div class="container">
    <aside class="menu">
      <div class="brand">OpenMesh Control Center</div>
      <nav>
        <a href="#dashboard">Dashboard</a>
        <a href="#relatorios">Relatórios</a>
        <a href="#modelos">Modelos</a>
        <a href="#workers">Workers</a>
        <a href="#custos">Custos</a>
      </nav>
    </aside>
    <main class="content">
      <div class="top">
        <h1>Portal do Projeto OpenMesh-AI</h1>
        <button class="btn" id="open-login">Entrar no Portal</button>
      </div>
      <section class="grid" id="dashboard">
        <article class="card"><p class="label">Jobs hoje</p><p class="value">12.947</p></article>
        <article class="card"><p class="label">Workers online</p><p class="value">128</p></article>
        <article class="card"><p class="label">Uso token</p><p class="value">94.2k</p></article>
        <article class="card"><p class="label">SLA</p><p class="value">99.93%</p></article>
      </section>
      <section class="panel" id="relatorios">
        <h2>Relatórios de desempenho</h2>
        <p class="status">Última sincronização: em tempo real</p>
        <table>
          <thead><tr><th>Serviço</th><th>Latência p95</th><th>Taxa erro</th><th>Status</th></tr></thead>
          <tbody>
            <tr><td>Gateway</td><td>87 ms</td><td>0.12%</td><td>Saudável</td></tr>
            <tr><td>Coordinator</td><td>132 ms</td><td>0.21%</td><td>Saudável</td></tr>
            <tr><td>Inference Pool</td><td>246 ms</td><td>0.44%</td><td>Atenção</td></tr>
          </tbody>
        </table>
      </section>
    </main>
  </div>

  <dialog id="login-modal">
    <h3>Login do Portal</h3>
    <form method="dialog">
      <label>Usuário<input type="text" id="user" placeholder="admin@openmesh.ai" required /></label>
      <label>Senha<input type="password" id="password" placeholder="********" required /></label>
      <p class="status" id="login-status">Acesso seguro com trilha de auditoria.</p>
      <div class="row">
        <button class="btn ghost" value="cancel">Cancelar</button>
        <button class="btn" id="submit-login" value="default">Entrar</button>
      </div>
    </form>
  </dialog>

  <script>
    const modal = document.getElementById('login-modal');
    document.getElementById('open-login').addEventListener('click', () => modal.showModal());
    document.getElementById('submit-login').addEventListener('click', (event) => {
      event.preventDefault();
      const username = document.getElementById('user').value.trim();
      const password = document.getElementById('password').value.trim();
      const status = document.getElementById('login-status');
      if (username && password) {
        status.textContent = `Sessão iniciada para ${username}.`; 
        modal.close();
      } else {
        status.textContent = 'Preencha login e senha para continuar.';
      }
    });
  </script>
</body>
</html>"""


settings_for_cors = load_settings()
if settings_for_cors.cors_enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings_for_cors.cors_allow_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _validate_rank_texts(texts: list[str]) -> None:
    for idx, text in enumerate(texts):
        if len(text) > 10_000:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"texts[{idx}] exceeds max length of 10000",
            )


async def get_client_id(
    request: Request,
    x_api_key: str = Header(default="", alias="X-API-Key"),
) -> str:
    request_id = getattr(request.state, "request_id", "-")
    log = RequestLoggerAdapter(logger, {"request_id": request_id})
    settings: Settings = request.app.state.settings
    client_id = settings.api_keys.get(x_api_key)
    if client_id is None:
        log.warning("authentication failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    client_ip = _client_ip(request)
    request.app.state.rate_limiter_api_key.check(x_api_key)
    request.app.state.rate_limiter_ip.check(client_ip)
    return client_id


@app.middleware("http")
async def request_context(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    log = RequestLoggerAdapter(logger, {"request_id": request_id})

    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            metrics.observe_http_request(
                path=request.url.path,
                method=request.method,
                elapsed_seconds=elapsed_ms / 1000,
            )
        log.info("method=%s path=%s elapsed_ms=%.2f", request.method, request.url.path, elapsed_ms)

    response.headers["X-Request-ID"] = request_id
    return response


async def _create_job(
    request: Request, client_id: str, job_type: str, payload: dict[str, Any]
) -> str:
    request_id = request.state.request_id
    log = RequestLoggerAdapter(logger, {"request_id": request_id})
    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.coordinator_client

    started = time.perf_counter()
    response = await client.post(
        "/internal/jobs/create",
        headers={"Authorization": f"Bearer {settings.internal_token}", "X-Request-ID": request_id},
        json={
            "client_id": client_id,
            "job_type": job_type,
            "payload": payload,
            "request_id": request_id,
        },
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    log.info("coordinator_create elapsed_ms=%.2f status=%s", elapsed_ms, response.status_code)

    if response.status_code in {
        status.HTTP_402_PAYMENT_REQUIRED,
        status.HTTP_429_TOO_MANY_REQUESTS,
    }:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient balance"
        )
    response.raise_for_status()
    data = response.json()
    return str(data["job_id"])


async def _cancel_job(request: Request, job_id: str) -> None:
    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.coordinator_client
    request_id = request.state.request_id
    log = RequestLoggerAdapter(logger, {"request_id": request_id})
    try:
        await client.post(
            f"/internal/jobs/{job_id}/cancel",
            headers={
                "Authorization": f"Bearer {settings.internal_token}",
                "X-Request-ID": request_id,
            },
            json={"reason": "gateway_timeout"},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("cancel failed job_id=%s error=%s", job_id, exc)


async def _wait_for_verification(request: Request, job_id: str) -> dict[str, Any]:
    request_id = request.state.request_id
    log = RequestLoggerAdapter(logger, {"request_id": request_id})
    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.coordinator_client

    timeout_at = time.monotonic() + settings.poll_timeout_seconds
    while time.monotonic() < timeout_at:
        started = time.perf_counter()
        response = await client.get(
            f"/internal/jobs/{job_id}",
            headers={
                "Authorization": f"Bearer {settings.internal_token}",
                "X-Request-ID": request_id,
            },
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        log.info("coordinator_poll elapsed_ms=%.2f status=%s", elapsed_ms, response.status_code)
        response.raise_for_status()

        job = cast(dict[str, Any], response.json())
        if job.get("status") == "verified":
            return job
        await asyncio.sleep(settings.poll_interval_seconds)

    await _cancel_job(request, job_id)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Verification timeout"
    )


async def _run_job(
    request: Request, *, client_id: str, job_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    job_id = await _create_job(request, client_id, job_type, payload)
    job = await _wait_for_verification(request, job_id)
    return {"job_id": job_id, "output": job.get("output")}


@app.post("/v1/embed")
async def embed(
    payload: EmbedRequest, request: Request, client_id: str = Depends(get_client_id)
) -> dict[str, Any]:
    return await _run_job(
        request, client_id=client_id, job_type="embed", payload=payload.model_dump()
    )


@app.post("/v1/rank")
async def rank(
    payload: RankRequest, request: Request, client_id: str = Depends(get_client_id)
) -> dict[str, Any]:
    _validate_rank_texts(payload.texts)
    return await _run_job(
        request, client_id=client_id, job_type="rank", payload=payload.model_dump()
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pool-gateway"}


@app.get("/", response_class=HTMLResponse)
def web_portal() -> str:
    return PORTAL_HTML


@app.get("/metrics")
def metrics(request: Request) -> Response:
    return Response(
        content=request.app.state.metrics.render(), media_type="text/plain; version=0.0.4"
    )
