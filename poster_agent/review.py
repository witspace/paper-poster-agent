"""Local, version-aware review of a poster project."""

from __future__ import annotations

import json
import hashlib
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


class ReviewError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _state(project: Path) -> dict:
    from .project import load_spec, spec_digest

    spec = load_spec(project)
    report = _read_json(project / "exports" / "quality-report.json", None)
    feedback = _read_json(project / "feedback.json", [])
    if isinstance(feedback, dict):
        feedback = feedback.get("items", [])
    history = []
    changes = {item["version"]: item for item in _read_json(project / "changes.json", [])}
    for path in sorted((project / "history").glob("*.json"), reverse=True):
        saved = _read_json(path, {})
        change = changes.get(saved.get("version"), {})
        history.append({"file": path.name, "version": saved.get("version"),
                        "reason": change.get("reason", ""), "timestamp": change.get("timestamp", "")})
    digest = spec_digest(spec)
    reference = spec.get("reference_image")
    critique = _read_json(project / "visual-critique.json", None)
    manifest_path = project / "exports/render-manifest.json"
    critique_current = bool(critique and critique.get("version") == spec["version"] and
                            critique.get("spec_sha256") == digest and manifest_path.is_file() and
                            critique.get("render_manifest_sha256") == hashlib.sha256(manifest_path.read_bytes()).hexdigest())
    previous_html = next((project / "history" / item["file"].replace(".json", ".html")
                          for item in history if (project / "history" / item["file"].replace(".json", ".html")).is_file()), None)
    return {"spec": spec, "digest": digest, "report": report, "feedback": feedback,
            "history": history[:30], "api_available": bool(os.environ.get("OPENAI_API_KEY")),
            "is_demo": _read_json(project / "conference.json", {}).get("is_demo") is True,
            "critique": critique, "critique_current": critique_current,
            "previous_html_url": "/project/history/" + previous_html.name if previous_html else None,
            "reference_url": f"/project/{reference}" if reference else None,
            "html_url": "/project/exports/poster.html",
            "pdf_preview_url": "/project/exports/poster-pdf-preview.png" if
            (project / "exports" / "poster-pdf-preview.png").is_file() else None,
            "pdf_url": "/project/exports/poster-print.pdf" if
            (project / "exports" / "poster-print.pdf").is_file() else None,
            "report_current": bool(report and report.get("spec_sha256") == digest and
                                   report.get("version") == spec["version"])}


def _validate_revision(project: Path, data: dict) -> dict:
    from .project import load_spec, spec_digest

    spec = load_spec(project)
    if data.get("expected_version") != spec["version"] or data.get("expected_digest") != spec_digest(spec):
        raise ReviewError("设计版本已更新，请刷新预览后再操作。 / The poster changed; refresh before continuing.", 409)
    return spec


def _validate_bbox(bbox):
    if bbox is None:
        return None
    if not isinstance(bbox, dict) or set(bbox) != {"x", "y", "width", "height"}:
        raise ReviewError("选区必须包含 x、y、width 和 height。")
    if any(not isinstance(v, (float, int)) or isinstance(v, bool) for v in bbox.values()):
        raise ReviewError("选区坐标必须是数值。")
    x, y, width, height = (bbox[k] for k in ("x", "y", "width", "height"))
    if not (0 <= x < 1 and 0 <= y < 1 and width > 0 and height > 0 and
            x + width <= 1.000001 and y + height <= 1.000001):
        raise ReviewError("选区坐标必须位于海报内，并归一化至 0–1。")
    return bbox


def create_server(project: str | Path, host: str = "127.0.0.1", port: int = 8765) -> HTTPServer:
    """Create the loopback server; the caller owns its lifetime."""
    if host != "127.0.0.1":
        raise ValueError("Review serves on 127.0.0.1 only.")
    project = Path(project).resolve(strict=True)
    web = Path(__file__).parent / "web" / "review.html"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _allowed_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def _send(self, code: int, body: bytes, content_type: str):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # The local browser closed its request.

        def _json(self, code: int, value):
            self._send(code, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _project_file(self, path: str) -> Path:
            resolved = (project / unquote(path).replace("\\", "/")).resolve()
            if not resolved.is_relative_to(project):
                raise ReviewError("File is outside this project.", 403)
            if not resolved.is_file():
                raise ReviewError("File not found.", 404)
            return resolved

        def do_GET(self):
            if not self._allowed_host():
                self._json(403, {"error": "Invalid local Host header."})
                return
            try:
                path = urlsplit(self.path).path
                if path == "/api/state":
                    self._json(200, _state(project))
                elif path in ("/", "/review"):
                    self._send(200, web.read_bytes(), "text/html; charset=utf-8")
                elif path == "/api/print-package":
                    query = parse_qs(urlsplit(self.path).query)
                    data = {"expected_version": int(query.get("version", ["0"])[0]),
                            "expected_digest": query.get("digest", [""])[0]}
                    _validate_revision(project, data)
                    from .delivery import package_project
                    archive = package_project(project)
                    body = archive.read_bytes()
                    _validate_revision(project, data)
                    self._send(200, body, "application/zip")
                elif path.startswith("/project/"):
                    file = self._project_file(path[len("/project/"):])
                    if file.suffix.lower() == ".zip":
                        raise ReviewError("Use the current approved-version print-package download.", 403)
                    content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                    self._send(200, file.read_bytes(), content_type)
                else:
                    self._json(404, {"error": "Not found."})
            except ReviewError as error:
                self._json(error.status, {"error": str(error)})
            except (ValueError, OSError) as error:
                self._json(400, {"error": str(error)})

        def do_POST(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if not self._allowed_host() or self.headers.get("Origin") != origin:
                self._json(403, {"error": "Mutations require the local review page's Origin."})
                return
            try:
                if self.headers.get_content_type() != "application/json":
                    raise ReviewError("Use application/json.", 415)
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ReviewError("Request body must be 1–65536 bytes.", 413)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ReviewError("Expected a JSON object.")
                spec = _validate_revision(project, data)
                path = urlsplit(self.path).path
                from .project import approve, approved, load_spec, record_feedback, reopen, save_revision, spec_digest, undo
                from .render import build_html, check_project, export_project

                if path == "/api/feedback":
                    target = data.get("target", "poster")
                    ids = {section["id"] for section in spec["sections"]} | {"header", "poster"}
                    if not isinstance(target, str) or target not in ids:
                        raise ReviewError("Choose an existing section or the whole poster.")
                    message = data.get("message", "")
                    if not isinstance(message, str) or not message.strip():
                        raise ReviewError("请先填写修改意见。 / Enter feedback first.")
                    selection = _validate_bbox(data.get("bbox"))
                    bounds = [selection[k] for k in ("x", "y", "width", "height")] if selection else None
                    record = record_feedback(project, "global" if target == "poster" else target, message.strip(), bounds)
                    self._json(200, {"saved": True, "applied": False, "feedback": record,
                                     "message": "反馈已保存，当前海报尚未修改。 / Feedback saved; the poster is unchanged."})
                elif path == "/api/apply":
                    from .agent import apply_feedback
                    if approved(spec):
                        raise ReviewError("当前设计已冻结，请先明确重新开启修改。 / Reopen the approved design before editing it.", 409)
                    feedback_id = data.get("feedback_id")
                    if not isinstance(feedback_id, str) or not feedback_id:
                        raise ReviewError("Save feedback before applying it.")
                    if not os.environ.get("OPENAI_API_KEY"):
                        raise ReviewError(
                            "反馈已保留，当前海报未修改。请在 Codex 中让 $academic-poster-agent 处理 feedback.json，"
                            "或在本机配置 OPENAI_API_KEY 和 POSTER_MODEL 后再应用。 / Feedback is preserved; "
                            "use the Codex skill or configure the local API environment.", 422)
                    before = spec_digest(spec)
                    result = apply_feedback(project, feedback_id)
                    changed = spec_digest(load_spec(project)) != before
                    if changed:
                        build_html(project)
                        check_project(project)
                    self._json(200, {"applied": changed, "result": result,
                                     "message": "修改已应用，请查看前后对照。" if changed else
                                     "反馈已处理，当前设计未发生变更。 / No design changes were applied."})
                elif path == "/api/locks":
                    if approved(spec):
                        raise ReviewError("当前设计已冻结，请先明确重新开启修改。 / Reopen the approved design before editing it.", 409)
                    regions = data.get("locked_regions")
                    ids = {section["id"] for section in spec["sections"]} | {"header"}
                    if not isinstance(regions, list) or any(not isinstance(x, str) or x not in ids for x in regions):
                        raise ReviewError("Unknown locked region.")
                    regions = list(dict.fromkeys(regions))
                    if regions != spec.get("locked_regions", []):
                        spec["locked_regions"] = regions
                        save_revision(project, spec, "User updated preserved regions")
                        export_project(project)
                    self._json(200, {"message": "保留区域已保存。 / Preserved regions saved."})
                elif path == "/api/check":
                    report = check_project(project)
                    self._json(200, {"report": report, "message": "验证已完成，请检查问题清单。"})
                elif path == "/api/approve":
                    report = check_project(project)
                    if report.get("version") != spec["version"] or report.get("spec_sha256") != spec_digest(spec):
                        raise ReviewError("验证结果与当前版本不一致，请重新验证。", 409)
                    checks = report.get("required_checks")
                    if not checks or any(check.get("passed") is not True for check in checks):
                        raise ReviewError("必需检查尚未通过，请先处理验证面板中的问题。 / Required checks must pass before approval.", 422)
                    result = approve(project)
                    check_project(project)
                    self._json(200, {"approved": True, "result": result,
                                     "message": "当前设计版本已确认。最终导出仍需执行打印检查。"})
                elif path == "/api/reopen":
                    result = reopen(project)
                    check_project(project)
                    self._json(200, {"result": result, "message": "已明确重新开启修改；后续版本需要再次审阅确认。"})
                elif path == "/api/package":
                    from .delivery import package_project
                    package_project(project)
                    self._json(200, {"download_url": f"/api/print-package?version={spec['version']}&digest={spec_digest(spec)}",
                                     "message": "当前已确认版本通过打印检查，打印包已准备。"})
                elif path == "/api/undo":
                    if approved(spec):
                        raise ReviewError("当前设计已冻结，请先明确重新开启修改。", 409)
                    result = undo(project)
                    export_project(project)
                    self._json(200, {"result": result, "message": "已撤销上一轮修改，请重新审阅当前版本。"})
                else:
                    raise ReviewError("Unknown review action.", 404)
            except ReviewError as error:
                self._json(error.status, {"error": str(error)})
            except (ValueError, RuntimeError, OSError) as error:
                self._json(400, {"error": str(error)})

    return HTTPServer((host, port), Handler)


def serve(project: str | Path, host: str = "127.0.0.1", port: int = 8765):
    from .render import build_html

    build_html(Path(project))
    server = create_server(project, host, port)
    print(f"Review: http://127.0.0.1:{server.server_port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
