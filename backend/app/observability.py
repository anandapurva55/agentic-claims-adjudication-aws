"""Request ids and structured logs. Every request gets an id (returned in X-Request-ID), every log line from that request carries it, and each request ends with one
JSON line saying who called what and how it went. In AWS the lines land in CloudWatch Logs as JSON, so they can be searched by request id.

A pure ASGI middleware, not Starlette's BaseHTTPMiddleware, because the run endpoint streams server-sent events and the wrapper can interfere with streaming.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
access_log = logging.getLogger("adjudication.api")
_SAFE_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z", "level": record.levelname, "logger": record.name,
                "message": record.getMessage(), "request_id": request_id_var.get(), **getattr(record, "fields", {})}
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    root.setLevel(level)
    for noisy in ("botocore", "boto3", "urllib3", "strands", "mcp", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class RequestLogMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex[:16]  # an id a caller supplies is used only if it is plain, so it cannot forge log lines
        token = request_id_var.set(rid)
        started, status = time.perf_counter(), 500

        async def send_with_id(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {**message, "headers": [*message.get("headers", []), (b"x-request-id", rid.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            access_log.exception("request failed", extra={"fields": {"method": scope["method"], "path": scope["path"]}})
            raise
        finally:
            access_log.info("request", extra={"fields": {"method": scope["method"], "path": scope["path"], "status": status,
                                                         "ms": round((time.perf_counter() - started) * 1000), "user": scope.get("state", {}).get("user", "-")}})
            request_id_var.reset(token)
