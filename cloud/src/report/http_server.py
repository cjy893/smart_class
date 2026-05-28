import asyncio
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


class ReportHttpServer:
    def __init__(self, reports_dir: str | Path, host: str = "0.0.0.0", port: int = 8081):
        self.reports_dir = Path(reports_dir).resolve()
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._server:
            return
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        handler_cls = self._make_handler()
        self._server = ThreadingHTTPServer((self.host, self.port), handler_cls)
        self._task = asyncio.create_task(asyncio.to_thread(self._server.serve_forever))

    async def stop(self) -> None:
        if self._server:
            await asyncio.to_thread(self._server.shutdown)
            await asyncio.to_thread(self._server.server_close)
            self._server = None
        if self._task:
            await self._task
            self._task = None

    async def handle_get(self, path: str) -> tuple[int, dict[str, str], bytes]:
        parsed = urlparse(path)
        if not parsed.path.startswith("/reports/"):
            return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"not found"

        relative = unquote(parsed.path[len("/reports/"):])
        file_path = (self.reports_dir / relative).resolve()
        if not _is_relative_to(file_path, self.reports_dir):
            raise ValueError("requested path is outside reports directory")
        if not file_path.is_file():
            return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"not found"

        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        return 200, {"Content-Type": content_type}, file_path.read_bytes()

    def _make_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                try:
                    status, headers, body = asyncio.run(outer.handle_get(self.path))
                except ValueError:
                    status = 403
                    headers = {"Content-Type": "text/plain; charset=utf-8"}
                    body = b"forbidden"

                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        return Handler


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False
