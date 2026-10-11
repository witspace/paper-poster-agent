"""Bounded, resumable API workflow driven by actual project artifacts."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from . import agent
from .project import (approved, load_spec, project_path, read_json, spec_digest,
                      timestamp, write_json)
from .render import check_project, export_project


def _conference_ready(project):
    profile = read_json(project / "conference.json")
    rules = profile.get("requirements", {})
    verified = any(source.get("verification") in ("fetched_quote_matched", "explicitly_imported_checked_profile")
                   for source in profile.get("sources", []))
    return bool(profile.get("sources") and not profile.get("unresolved") and
                rules.get("width_mm") and rules.get("height_mm") and verified and
                (profile.get("checked_at") or profile.get("imported_at")))


def _reference_ready(project, spec):
    path = project_path(project, spec["reference_image"])
    if not path.exists():
        return False
    with Image.open(path) as image:
        image.verify()
    return True


def _current_export(project):
    report = check_project(project)
    current = next((item["passed"] for item in report["required_checks"] if item["id"] == "current_export"), False)
    return current, report


def _current_critique(project, spec):
    path = project / "visual-critique.json"
    manifest = project / "exports/render-manifest.json"
    if not path.exists() or not manifest.exists():
        return False
    critique = read_json(path)
    return (critique.get("spec_sha256") == spec_digest(spec) and
            critique.get("version") == spec["version"] and
            critique.get("render_manifest_sha256") == hashlib.sha256(manifest.read_bytes()).hexdigest() and
            critique.get("human_acceptance") is False)


def run_pipeline(project, resume=False, max_rounds=2):
    """Run an explicitly selected API workflow on an already ingested project.

    Artifacts survive failures. Resume skips complete, current stages, and the
    entire run permits at most two automatic visual revisions. Human approval
    is always a separate explicit operation.
    """
    project = Path(project).resolve()
    if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or not 0 <= max_rounds <= 2:
        raise ValueError("max_rounds must be an integer from 0 to 2")
    if not (project / "source/paper.pdf").is_file():
        raise ValueError("Initialize the project with a paper before running the pipeline")
    report_path = project / "run-report.json"
    previous = read_json(report_path) if report_path.exists() else None
    if not resume and ((project / "poster.json").exists() or previous):
        raise ValueError("Project already has a workflow or draft; select resume to preserve existing artifacts")
    state = previous if resume and previous else {"schema_version": 1, "started_at": timestamp(), "steps": [], "repair_rounds": 0}
    state.update(status="running", failed_step=None, error=None, next_action=None, max_rounds=max_rounds, updated_at=timestamp())
    write_json(report_path, state)
    active_step = "source"

    def step(name, operation=None, skip=False):
        nonlocal active_step
        active_step = name
        event = {"step": name, "status": "reused" if skip else "running", "started_at": timestamp()}
        if (project / "poster.json").exists():
            event["base_version"] = load_spec(project)["version"]
        state["steps"].append(event)
        write_json(report_path, state)
        result = None if skip else operation()
        event.update(status="reused" if skip else "completed", finished_at=timestamp())
        if (project / "poster.json").exists():
            spec = load_spec(project)
            event.update(version=spec["version"], spec_sha256=spec_digest(spec))
        if isinstance(result, dict) and result.get("status"):
            event["result_status"] = result["status"]
        state["updated_at"] = timestamp()
        write_json(report_path, state)
        return result

    try:
        paper_digest = hashlib.sha256((project / "source/paper.pdf").read_bytes()).hexdigest()
        evidence = read_json(project / "evidence.json")
        if evidence.get("paper", {}).get("sha256") != paper_digest or (state.get("source_sha256") and state["source_sha256"] != paper_digest):
            raise ValueError("Original paper bytes changed; initialize a new project for the changed source")
        state["source_sha256"] = paper_digest
        state["repair_rounds"] = max(state["repair_rounds"], sum(
            event.get("result_status") == "applied" for event in state["steps"] if event["step"] == "repair"))
        step("research", lambda: agent.research_conference(project), skip=_conference_ready(project))
        if not _conference_ready(project):
            raise ValueError("Official mandatory dimensions remain unresolved; inspect conference.json")
        if (project / "poster.json").exists():
            load_spec(project)
            step("draft", skip=True)
        else:
            step("draft", lambda: agent.draft_project(project))
        spec = load_spec(project)
        if approved(spec):
            active_step = "check"
            checks = check_project(project)
            state.update(status="approved" if checks["print_ready"] else "needs_manual_fix",
                         next_action="Accepted design is frozen; inspect quality-report.json" if not checks["print_ready"] else "Use the accepted print PDF",
                         version=spec["version"], spec_sha256=spec_digest(spec), print_ready=checks["print_ready"])
            write_json(report_path, state)
            return state
        step("reference", lambda: agent.generate_reference(project), skip=_reference_ready(project, spec))
        current, checks = _current_export(project)
        step("render", lambda: export_project(project), skip=current)
        spec = load_spec(project)
        step("critique", lambda: agent.critique_project(project), skip=_current_critique(project, spec))
        checks = check_project(project)
        stop = None
        while state["repair_rounds"] < max_rounds:
            repair = step("repair", lambda: agent.repair_project(project))
            if repair["status"] != "applied":
                stop = repair
                break
            state["repair_rounds"] += 1
            write_json(report_path, state)
            step("render", lambda: export_project(project))
            step("critique", lambda: agent.critique_project(project))
            checks = check_project(project)
        spec = load_spec(project)
        checks = step("check", lambda: check_project(project))
        if not checks["content_pass"] or (stop and stop["status"] == "needs_author"):
            status = "needs_author"
            action = "Compare listed scientific issues with source/paper.pdf, correct them with author verification, then resume"
        elif not checks["technical_pass"]:
            status = "needs_manual_fix"
            action = "Resolve actual errors in exports/quality-report.json and visual-critique.json, then resume"
        elif stop and stop["status"] in ("needs_assets", "manual_review"):
            status = stop["status"]
            action = stop["message"]
        else:
            status = "awaiting_human_review"
            action = f'poster-agent review "{project}"; inspect reference, original figures, local crops and print PDF, then approve only when satisfied'
        state.update(status=status, failed_step=None, version=spec["version"], spec_sha256=spec_digest(spec),
                     technical_pass=checks["technical_pass"], content_pass=checks["content_pass"],
                     print_ready=checks["print_ready"], next_action=action,
                     automatic_revision_limit_reached=state["repair_rounds"] >= max_rounds,
                     artifacts={name: f"exports/{name}" for name in ("poster.html", "poster-4k.png", "poster-print.pdf", "quality-report.json")},
                     updated_at=timestamp())
        write_json(report_path, state)
        return state
    except Exception as error:
        action = {"source": "Restore the exact ingested paper or initialize a new project with the changed paper",
                  "research": "Inspect conference.json and supply verified official requirements before resuming",
                  "draft": "Inspect original catalog and model schema; existing source material is preserved",
                  "reference": "Inspect ImageGen model/key and raster original previews; resume reuses any valid existing reference",
                  "render": "Install Chromium if required, then export the current design and resume",
                  "critique": "Inspect current render geometry/model response, then resume independent review",
                  "repair": "Inspect critique and protected regions; resolve the indicated issue and resume",
                  "check": "Inspect actual artifacts and quality-report.json"}.get(active_step, "Inspect project artifacts and resume")
        state.update(status="failed", failed_step=active_step, error=str(error), next_action=action, updated_at=timestamp())
        if state["steps"] and state["steps"][-1]["status"] == "running":
            state["steps"][-1].update(status="failed", error=str(error), finished_at=timestamp())
        write_json(report_path, state)
        raise RuntimeError(f"Pipeline failed at {active_step}: {error}. Next: {action}. Resume preserves completed artifacts.") from error
