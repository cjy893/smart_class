import asyncio
from pathlib import Path

import pytest

from report.http_server import ReportHttpServer


def run(coro):
    return asyncio.run(coro)


def test_report_http_server_serves_report_file(tmp_path):
    report = tmp_path / "report.html"
    report.write_text("<h1>report</h1>", encoding="utf-8")
    server = ReportHttpServer(tmp_path)

    status, headers, body = run(server.handle_get("/reports/report.html"))

    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert body == b"<h1>report</h1>"


def test_report_http_server_serves_json_report(tmp_path):
    report = tmp_path / "report.json"
    report.write_text('{"ok": true}', encoding="utf-8")
    server = ReportHttpServer(tmp_path)

    status, headers, body = run(server.handle_get("/reports/report.json"))

    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert body == b'{"ok": true}'


def test_report_http_server_rejects_path_traversal(tmp_path):
    outside = tmp_path.parent / "secret.html"
    outside.write_text("secret", encoding="utf-8")
    server = ReportHttpServer(tmp_path)

    with pytest.raises(ValueError, match="outside reports directory"):
        run(server.handle_get("/reports/../secret.html"))


def test_report_http_server_returns_404_for_missing_file(tmp_path):
    server = ReportHttpServer(tmp_path)

    status, headers, body = run(server.handle_get("/reports/missing.html"))

    assert status == 404
    assert headers["Content-Type"].startswith("text/plain")
    assert body == b"not found"
