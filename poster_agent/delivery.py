"""Create a local, checked print package only after exact human approval."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import string
import zipfile
from datetime import date, datetime
from pathlib import Path

from .conference import applicable_requirements
from .project import load_spec, read_json, spec_digest
from .render import check_project


def _safe_pdf_name(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 180:
        raise ValueError("PDF filename must contain 1–180 characters")
    if value != value.strip() or value in (".", "..") or re.search(r'[<>:"/\\|?*\x00-\x1f]', value):
        raise ValueError("PDF filename must be a single safe filename without paths or reserved characters")
    if not value.lower().endswith(".pdf") or value.endswith("."):
        raise ValueError("The print PDF filename must end with .pdf")
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value):
        raise ValueError("The PDF filename is reserved by Windows")
    return value


def _print_filename(conference: dict, requirements: dict, filename, printing_service, paper_id, track) -> str:
    service = conference.get("printing_service") or {}
    mandatory_name = requirements.get("file_name") if conference.get("requirement_sources", {}).get("file_name") else None
    if not printing_service and not mandatory_name:
        return _safe_pdf_name(filename or "poster-print.pdf")
    if printing_service and not service:
        raise ValueError("No conference printing-service profile is recorded")
    template = (service.get("file_name") or service.get("template") or requirements.get("file_name")) if printing_service else mandatory_name
    if not template:
        return _safe_pdf_name(filename or "poster-print.pdf")
    scope = "printing-service" if printing_service else "mandatory conference"
    if not isinstance(template, str):
        raise ValueError(f"{scope} filename template must be text")
    if "{" not in template:
        template = template.replace("Track", "{track}").replace("OpenReviewID", "{paper_id}")
    values_from = service if printing_service else conference
    values = {"track": track or values_from.get("track_token"), "paper_id": paper_id or values_from.get("openreview_id")}
    # Both forms are in current profiles: legacy literal Track/OpenReviewID and
    # explicit {track}/{paper_id} placeholders for newly researched conferences.
    aliases = {"Track": "track", "OpenReviewID": "paper_id", "openreview_id": "paper_id"}
    fields = []
    for _, field, format_spec, conversion in string.Formatter().parse(template):
        if field is not None:
            key = aliases.get(field, field)
            if key not in values or format_spec or conversion:
                raise ValueError(f"Unsupported {scope} filename placeholder: {field}")
            fields.append(key)
    missing = sorted(set(key for key in fields if values[key] in (None, "")))
    if missing:
        raise ValueError(f"Missing {scope} filename values: " + ", ".join(missing))
    for key in set(fields):
        value = str(values[key])
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
            raise ValueError(f"{scope} {key} must use letters, digits, underscores or hyphens")
        values[key] = value
    formatted = template.format(**values, Track=values["track"], OpenReviewID=values["paper_id"],
                                openreview_id=values["paper_id"])
    expected = _safe_pdf_name(formatted)
    if filename and _safe_pdf_name(filename) != expected:
        raise ValueError(f"Selected {scope} rules require filename {expected}")
    return expected


def _public_text(value: str) -> str:
    """Do not put original machine paths or configured credentials in a handoff."""
    text = str(value)
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        text = text.replace(key, "[redacted credential]")
    text = re.sub(r"(?i)(?<![a-z0-9])(?:[a-z]:[\\/]|file://|\\\\)[^\s\"<>]*", "[local path omitted]", text)
    return re.sub(r"(?<![\w:/])/(?:[^/\s]+/)+[^\s\"<>]*", "[local path omitted]", text)


def _public_report(report: dict) -> dict:
    def clean(value):
        if isinstance(value, str):
            return _public_text(value)
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()
                    if key.lower() not in {"key", "api_key", "openai_api_key", "secret", "feedback", "history", "paper", "source"}}
        return value
    # Whitelist measured checks, rather than copying project/evidence/feedback.
    result = {key: report[key] for key in ("version", "spec_sha256", "checked_at", "print_ready",
                   "technical_pass", "content_pass", "required_checks", "issues", "review")}
    result["metrics"] = {key: report["metrics"][key] for key in ("png_pixels", "pdf", "fonts", "images",
                          "pdf_raster_images", "html_pdf_mean_pixel_difference", "ppi_policy") if key in report["metrics"]}
    return clean(result)


def package_project(project: str | Path, filename: str | None = None, printing_service: bool = False,
                    paper_id: str | None = None, track: str | None = None) -> Path:
    """Return a ZIP path after rechecking actual approved artifacts; never upload."""
    project = Path(project).resolve()
    spec = load_spec(project)
    report = check_project(project)
    conference = read_json(project / "conference.json")
    if conference.get("is_demo"):
        raise ValueError("Demo profiles cannot be certified or packaged for a real conference")
    requirements = applicable_requirements(conference, printing_service=printing_service)
    format_rule = requirements.get("format")
    formats = [str(item).upper() for item in format_rule] if isinstance(format_rule, list) else [str(format_rule).upper()]
    if format_rule and not any(value in ("PDF", "APPLICATION/PDF") for value in formats):
        raise ValueError(f"Recorded conference format {format_rule!r} does not support PDF; this renderer cannot certify that output")
    if not report.get("print_ready") or report.get("spec_sha256") != spec_digest(spec):
        failed = [item["id"] for item in report["required_checks"] if not item["passed"]]
        pending = [name for name, passed in report.get("review", {}).items() if not passed]
        detail = "; ".join(failed + pending) or "current exact human approval is missing"
        raise ValueError("Print package requires current human approval, content and technical checks: " + detail)
    if (spec.get("visual_review") or {}).get("reviewer") != "human":
        raise ValueError("Print package requires a recorded human visual reviewer for this exact version")
    if printing_service and (conference.get("printing_service") or {}).get("unresolved_rules"):
        raise ValueError("Selected printing-service rules remain unverified: " +
                         "; ".join(conference["printing_service"]["unresolved_rules"]))
    pdf_name = _print_filename(conference, requirements, filename, printing_service, paper_id, track)
    measured = report["metrics"]["pdf"]["page_sizes_mm"][0]
    for index, field in enumerate(("width_mm", "height_mm")):
        if requirements.get(field) is None:
            continue
        expected = float(requirements[field])
        size_mismatch = measured[index] > expected + .001 if requirements.get("dimension_policy") == "maximum" else abs(measured[index] - expected) >= .001
        if size_mismatch:
            raise ValueError(f"Selected print requirements: actual PDF {field} is {measured[index]} mm, expected {requirements[field]} mm")
    orientation = "portrait" if measured[0] < measured[1] else "landscape" if measured[0] > measured[1] else "square"
    if requirements.get("orientation") not in (None, "either") and orientation != str(requirements["orientation"]).lower():
        raise ValueError("Actual PDF orientation does not satisfy selected print requirements")
    unsupported = [field for field in ("pdf_standard", "color_profile") if requirements.get(field)]
    if float(requirements.get("bleed_mm") or 0) > 0:
        unsupported.append("bleed_mm")
    if unsupported:
        raise ValueError("Selected print profile requires an unverified production step: " + ", ".join(unsupported))
    minimum = requirements.get("min_ppi")
    if minimum is not None:
        if not math.isfinite(float(minimum)) or float(minimum) <= 0:
            raise ValueError("Recorded min_ppi must be a positive finite number")
        if any(image["effective_ppi"] < float(minimum) for image in report["metrics"]["pdf_raster_images"]):
            raise ValueError("Actual PDF raster images fall below the selected print profile min_ppi")
    pdf = project / "exports/poster-print.pdf"
    maximum = requirements.get("max_file_size_mb")
    if maximum is not None:
        if not math.isfinite(float(maximum)) or float(maximum) <= 0:
            raise ValueError("Recorded max_file_size_mb must be a positive finite number")
        if pdf.stat().st_size > float(maximum) * 1_000_000:
            raise ValueError(f"Actual PDF is {pdf.stat().st_size / 1_000_000:.3f} MB, exceeding the selected {maximum} MB limit")
    service = conference.get("printing_service") or {}
    service_deadline = service.get("deadline_date") or service.get("requirements", {}).get("deadline_date") or service.get("deadline")
    deadline = (requirements.get("deadline_date") or service_deadline) if printing_service else service_deadline
    if printing_service and deadline:
        try:
            deadline_day = date.fromisoformat(str(deadline))
        except ValueError as error:
            raise ValueError("Printing-service deadline needs a verified YYYY-MM-DD date") from error
        if datetime.now().astimezone().date() > deadline_day:
            raise ValueError(f"Selected conference printing-service deadline {deadline_day} has passed in the local calendar; choose a local print package")

    warnings = [_public_text(item["message"]) for item in report["issues"] if item["severity"] == "warning"]
    warnings += [_public_text(item) for item in conference.get("warnings", [])]
    if deadline:
        warnings.append(f"Optional conference printing-service deadline: {deadline}. No exact cutoff time is inferred when the official time/timezone is unspecified.")
    identity = conference.get("identity") or spec.get("conference", {})
    sources = [f'- {_public_text(source.get("title", "Official conference source"))}: {_public_text(source.get("url", ""))}' for source in conference.get("sources", [])]
    rules = {key: requirements[key] for key in ("width_mm", "height_mm", "orientation", "dimension_policy", "format",
             "min_ppi", "max_file_size_mb", "bleed_mm", "pdf_standard", "color_profile") if key in requirements}
    readme = (
        f"PRINT PACKAGE — version {spec['version']}\n\n"
        f"Conference: {_public_text(identity.get('name', ''))} {_public_text(identity.get('year', ''))}; track: {_public_text(identity.get('track', ''))}\n"
        f"Purpose: {'selected conference printing service' if printing_service else 'local print handoff'}\n"
        f"Print file: {pdf_name}\nActual PDF: 1 page, {measured[0]:g} × {measured[1]:g} mm ({orientation}).\n"
        f"PNG: {' × '.join(str(value) for value in report['metrics']['png_pixels'])} px.\n"
        "Print at 100% / actual size. Ask the provider to preserve the exact page size.\n"
        "The HTML embeds its assets. The PDF preserves vector content and embedded fonts.\n"
        "PDF/X and ICC production certification are not asserted by this browser exporter.\n\n"
        f"Human approval: exact version {spec['version']}, SHA-256 {report['spec_sha256']}.\n"
        f"Approval time: {_public_text(spec['approval'].get('timestamp', 'recorded without timestamp'))}\n"
        f"Applicable recorded rules: {_public_text(json.dumps(rules, ensure_ascii=False))}\n\n"
        "Official sources:\n" + "\n".join(sources) + "\n\n"
        "Remaining notes:\n" + ("\n".join(f"- {warning}" for warning in warnings) or "- No remaining recorded warnings.") + "\n"
    )
    exports = project / "exports"
    manifest = read_json(exports / "render-manifest.json")
    artifacts = {}
    secret = os.environ.get("OPENAI_API_KEY", "").encode()
    for name in ("poster-print.pdf", "poster.html", "poster-4k.png"):
        artifacts[name] = (exports / name).read_bytes()
        if secret and secret in artifacts[name]:
            raise ValueError(f"Artifact {name} contains a configured credential; remove it and render a new version")
        if hashlib.sha256(artifacts[name]).hexdigest() != manifest.get("artifacts", {}).get(name):
            raise ValueError(f"Artifact {name} changed while packaging; render and approve the current output")
    destination = exports / f"print-package-v{spec['version']:04d}.zip"
    temporary = destination.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(pdf_name, artifacts["poster-print.pdf"])
            archive.writestr("poster.html", artifacts["poster.html"])
            archive.writestr("poster-4k.png", artifacts["poster-4k.png"])
            archive.writestr("quality-report.json", json.dumps(_public_report(report), ensure_ascii=False, indent=2))
            archive.writestr("PRINT_README.txt", readme)
        current = check_project(project)
        if (not current["print_ready"] or current["spec_sha256"] != report["spec_sha256"]
                or read_json(project / "conference.json") != conference):
            raise ValueError("Project changed while packaging; recheck and approve the current version")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
