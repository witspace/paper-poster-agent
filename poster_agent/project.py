"""Project state, exact-version approval and reversible local revisions."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def project_path(project, relative):
    root = Path(project).resolve()
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("A project-relative path is required")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path leaves the project directory")
    return path


def validate_spec(spec):
    if spec.get("schema_version") != 1:
        raise ValueError("Unsupported poster schema")
    canvas = spec.get("canvas", {})
    if not all(isinstance(canvas.get(k), (int, float)) and 50 <= canvas[k] <= 3000
               for k in ("width_mm", "height_mm")):
        raise ValueError("Canvas must specify real physical dimensions in mm")
    if not spec.get("title") or not spec.get("sections"):
        raise ValueError("A title and evidence-grounded sections are required")
    identifiers = [s.get("id") for s in spec["sections"]]
    if len(identifiers) != len(set(identifiers)) or any(
        not isinstance(i, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", i) for i in identifiers
    ):
        raise ValueError("Section IDs must be unique lowercase identifiers")
    if spec.get("layout", {}).get("columns", 2) not in (1, 2, 3):
        raise ValueError("Supported column counts are 1, 2 and 3")
    columns = spec.get("layout", {}).get("columns", 2)
    if any(s.get("span", 1) not in range(1, columns + 1) for s in spec["sections"]):
        raise ValueError("Section span cannot exceed the column count")
    for color in spec.get("theme", {}).values():
        if isinstance(color, str) and color.startswith("#") and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Use six-digit hex colors")
    return spec


def load_spec(project):
    return validate_spec(read_json(Path(project) / "poster.json"))


def spec_digest(spec):
    content = {k: v for k, v in spec.items() if k not in ("approval", "status", "visual_review")}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def content_digest(spec):
    """Identify scientific content independently of visual arrangement."""
    content = {key: spec.get(key, "") for key in
               ("title", "subtitle", "authors", "affiliations", "footer")}
    sections = []
    for section in sorted(spec.get("sections", []), key=lambda item: item["id"]):
        facts = {key: section.get(key, "") for key in ("id", "heading", "caption", "image")}
        facts.update({key: section.get(key, []) for key in
                      ("paragraphs", "bullets", "source_refs", "rows")})
        facts["tables"] = [{"title": table.get("title", ""), "rows": table.get("rows", []),
                            "caption": table.get("caption", "")} for table in section.get("tables", [])]
        sections.append(facts)
    content["sections"] = sections
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def approved(spec):
    approval = spec.get("approval") or {}
    return approval.get("version") == spec.get("version") and approval.get("sha256") == spec_digest(spec)


def save_revision(project, spec, reason):
    project = Path(project)
    previous = load_spec(project)
    spec = copy.deepcopy(validate_spec(spec))
    if previous.get("status") == "approved" or approved(previous):
        raise ValueError("Design is frozen. Explicitly reopen it before requesting a revision")
    locked = previous.get("locked_regions", [])
    if locked:
        global_styles_changed = any(previous.get(key) != spec.get(key) for key in ("theme", "layout"))
        size_changed = any(previous["canvas"][key] != spec["canvas"][key] for key in ("width_mm", "height_mm"))
        if global_styles_changed or size_changed:
            raise ValueError("Global styles affect locked regions; unlock them explicitly first")
        if "header" in locked and any(previous.get(key) != spec.get(key) for key in
                                      ("title", "subtitle", "authors", "affiliations", "conference", "branding")):
            raise ValueError("The header is locked")
        old_sections = {section["id"]: section for section in previous["sections"]}
        new_sections = {section["id"]: section for section in spec["sections"]}
        old_order, new_order = list(old_sections), list(new_sections)
        for region in locked:
            if region == "header":
                continue
            if old_sections.get(region) != new_sections.get(region) or old_order.index(region) != new_order.index(region):
                raise ValueError(f"Section {region} is locked")
    content_changed = content_digest(previous) != content_digest(spec)
    history = project / "history"
    history.mkdir(exist_ok=True)
    write_json(history / f"v{previous['version']:04d}.json", previous)
    exports = project / "exports"
    manifest_path = exports / "render-manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    if manifest.get("version") == previous["version"] and manifest.get("spec_sha256") == spec_digest(previous):
        import shutil
        for name, suffix in (("poster-preview.png", "-preview.png"), ("poster.html", ".html")):
            source = exports / name
            if source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() == manifest.get("artifacts", {}).get(name):
                shutil.copy2(source, history / f"v{previous['version']:04d}{suffix}")
    spec.update(version=previous["version"] + 1, status="review", approval=None)
    evidence_path = project / "evidence.json"
    if content_changed and evidence_path.exists():
        evidence = read_json(evidence_path)
        evidence["content_review"] = {"status": "pending", "issues": [],
                                      "note": "Scientific content changed; review the current facts against the paper"}
        write_json(evidence_path, evidence)
    write_json(project / "poster.json", spec)
    log = read_json(project / "changes.json") if (project / "changes.json").exists() else []
    log.append({"version": spec["version"], "reason": reason, "timestamp": timestamp()})
    write_json(project / "changes.json", log)
    return spec


def approve(project):
    project = Path(project)
    spec = load_spec(project)
    report_path = project / "exports/quality-report.json"
    if not report_path.exists():
        raise ValueError("Render and check the current version before approving")
    report = read_json(report_path)
    report_digest = report.get("spec_sha256", report.get("spec_digest"))
    if report_digest != spec_digest(spec):
        raise ValueError("Checks are stale; render and check the current version")
    # Review must be technically sound before the human can approve it.
    blocking = [i for i in report.get("issues", []) if i.get("severity") in ("error", "critical", "blocking")]
    if blocking or report.get("technical_pass") is not True:
        raise ValueError("Resolve the listed technical errors before approving")
    if report.get("content_pass") is not True:
        raise ValueError("Content evidence review has unresolved errors")
    spec["status"] = "approved"
    manifest = read_json(project / "exports/render-manifest.json")
    spec["approval"] = {"version": spec["version"], "sha256": spec_digest(spec), "timestamp": timestamp(),
                        "artifacts_sha256": manifest.get("artifacts", {})}
    spec["visual_review"] = {"status": "accepted", "version": spec["version"], "sha256": spec_digest(spec),
                             "reviewer": "human", "timestamp": timestamp()}
    write_json(project / "poster.json", spec)
    return spec


def undo(project):
    project = Path(project)
    spec = load_spec(project)
    snapshots = sorted((project / "history").glob("v*.json"))
    if not snapshots:
        raise ValueError("No previous version is available")
    previous = read_json(snapshots[-1])
    return save_revision(project, previous, f"Restore design from version {previous['version']}")


def record_feedback(project, target, message, bbox=None):
    project = Path(project)
    spec = load_spec(project)
    valid_targets = {s["id"] for s in spec["sections"]} | {"global", "header"}
    if target not in valid_targets:
        raise ValueError("Unknown feedback region")
    if not isinstance(message, str) or not message.strip() or len(message) > 12000:
        raise ValueError("Describe the desired change in 1–12000 characters")
    if bbox is not None and (not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or
                            not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in bbox)):
        raise ValueError("Selection bounds must contain four normalized coordinates")
    path = project / "feedback.json"
    items = read_json(path) if path.exists() else []
    item = {"id": f"f{len(items) + 1:04d}", "version": spec["version"], "target": target,
            "message": message.strip(), "bbox": bbox, "status": "pending", "timestamp": timestamp()}
    items.append(item)
    write_json(path, items)
    return item


def apply_visual_patch(project, patch, reason):
    """Limited visual edits never silently change scientific content or originals."""
    old = load_spec(project)
    if approved(old):
        raise ValueError("Design is frozen. Explicitly reopen it before requesting a revision")
    spec = copy.deepcopy(old)
    if set(patch) - {"theme", "layout", "sections", "section_order"}:
        raise ValueError("Visual patches may only change layout and style")
    allowed_theme = {"accent", "secondary", "ink", "background", "font"}
    allowed_layout = {"columns", "gap_mm", "margin_mm", "title_pt", "body_pt", "style"}
    for field, allowed in (("theme", allowed_theme), ("layout", allowed_layout)):
        values = patch.get(field, {})
        if not isinstance(values, dict) or set(values) - allowed:
            raise ValueError(f"Unsupported {field} edit")
        if field == "theme":
            for key, value in values.items():
                if not isinstance(value, str) or (key != "font" and not re.fullmatch(r"#[0-9a-fA-F]{6}", value)):
                    raise ValueError("Colors must be six-digit hex strings")
                if key == "font" and value not in ("Arial", "Helvetica", "sans-serif", "Georgia"):
                    raise ValueError("Unsupported font")
        else:
            for key, value in values.items():
                if key == "style":
                    if value not in ("narrative", "standard"):
                        raise ValueError("Use narrative or standard layout style")
                    continue
                if not isinstance(value, (int, float)) or not 0 < value <= 160:
                    raise ValueError("Layout values must be positive numbers")
            if values.get("body_pt", old.get("layout", {}).get("body_pt", 25)) < 18:
                raise ValueError("Body text must remain at least 18 pt; shorten verified content instead")
        spec.setdefault(field, {}).update(values)
    sections = {s["id"]: s for s in spec["sections"]}
    for change in patch.get("sections", []):
        if set(change) - {"id", "span", "image_height_mm", "hide_heading"}:
            raise ValueError("A visual edit cannot change text, data or source figures")
        target = change.get("id")
        if target not in sections:
            raise ValueError("Unknown section")
        for key in ("span", "image_height_mm"):
            if key in change:
                value = change[key]
                if not isinstance(value, (int, float)) or value <= 0:
                    raise ValueError("Invalid section size")
                sections[target][key] = value
        if "hide_heading" in change:
            if not isinstance(change["hide_heading"], bool):
                raise ValueError("hide_heading must be a boolean")
            sections[target]["hide_heading"] = change["hide_heading"]
    if "section_order" in patch:
        order = patch["section_order"]
        if not isinstance(order, list) or len(order) != len(sections) or set(order) != set(sections):
            raise ValueError("Reordering requires each ID exactly once")
        spec["sections"] = [sections[i] for i in order]
    return save_revision(project, spec, reason)


def reopen(project):
    spec = load_spec(project)
    spec["status"] = "review"
    spec["approval"] = None
    write_json(Path(project) / "poster.json", spec)
    return spec
