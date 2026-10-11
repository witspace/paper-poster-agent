"""Explicit local utilities and a separately selected, billed API workflow."""
import argparse
import json
import sys
from pathlib import Path

from .project import read_json, record_feedback, approve, undo, reopen, apply_visual_patch


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Paper → original figures → HTML → independent review → print delivery")
    commands = parser.add_subparsers(dest="command", required=True)
    names = ("init", "research", "draft", "reference", "render", "check", "critique", "repair",
             "review", "feedback", "apply", "patch", "approve", "reopen", "undo", "run", "rules", "package", "demo")
    for name in names:
        command = commands.add_parser(name)
        command.add_argument("project", type=Path)
        if name in ("init", "run"):
            required = name == "init"
            command.add_argument("--paper", type=Path, required=required)
            command.add_argument("--conference", required=required)
            command.add_argument("--year", type=int, required=required)
            command.add_argument("--track", required=required)
            command.add_argument("--assets", type=Path)
        if name == "run":
            command.add_argument("--api", action="store_true", help="Use configured OpenAI API; calls are billed to your account")
            command.add_argument("--resume", action="store_true", help="Preserve valid completed artifacts and continue")
            command.add_argument("--max-rounds", type=int, choices=range(3), default=2)
        if name in ("render", "demo"):
            command.add_argument("--png-width", type=int, default=6000 if name == "demo" else None)
        if name == "reference":
            command.add_argument("--new-version", action="store_true")
        if name == "review":
            command.add_argument("--port", type=int, default=8765)
        if name == "feedback":
            command.add_argument("--target", default="global")
            command.add_argument("--message", required=True)
        if name == "apply":
            command.add_argument("feedback_id")
        if name == "patch":
            command.add_argument("patch_file", type=Path)
            command.add_argument("--reason", required=True)
        if name == "rules":
            command.add_argument("--file", type=Path, required=True,
                                 help="Explicit import of a profile whose official links and excerpts you have checked")
        if name == "package":
            command.add_argument("--filename")
            command.add_argument("--printing-service", action="store_true")
            command.add_argument("--paper-id")
            command.add_argument("--track")
    command = commands.add_parser("doctor")
    command.add_argument("--workspace", type=Path)
    command.add_argument("--skip-browser", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            from .doctor import doctor
            result = doctor(args.workspace, not args.skip_browser)
        elif args.command == "demo":
            from .demo import create_demo
            result = create_demo(args.project, args.png_width)
        elif args.command in ("init", "run"):
            from .ingest import ingest
            if args.command == "run" and not args.api:
                raise ValueError("Select --api to use the standalone billed model workflow. The Codex skill uses current-session tools instead.")
            if args.command == "init" or not (args.project / "source/paper.pdf").exists():
                if not all((args.paper, args.conference, args.year, args.track)):
                    raise ValueError("A new project requires --paper, --conference, --year and --track")
                if args.command == "run" and args.resume:
                    raise ValueError("Resume requires an already initialized project")
                result = ingest(args.project, args.paper,
                                {"name": args.conference, "year": args.year, "track": args.track}, args.assets)
            elif any((args.paper, args.conference, args.year, args.track, args.assets)):
                raise ValueError("Project is initialized; run with its saved identity and paper. Use a new directory for new inputs")
            if args.command == "run":
                from .pipeline import run_pipeline
                result = run_pipeline(args.project, args.resume, args.max_rounds)
        elif args.command in ("research", "draft", "reference", "critique", "repair", "apply"):
            from . import agent
            if args.command == "apply":
                result = agent.apply_feedback(args.project, args.feedback_id)
            elif args.command == "reference":
                result = agent.generate_reference(args.project, args.new_version)
            elif args.command == "repair":
                result = agent.repair_project(args.project)
                if result.get("status") == "applied":
                    from .render import export_project, check_project
                    export_project(args.project)
                    agent.critique_project(args.project)
                    result["quality"] = check_project(args.project)
            else:
                result = {"research": agent.research_conference, "draft": agent.draft_project,
                          "critique": agent.critique_project}[args.command](args.project)
        elif args.command in ("render", "check"):
            from .render import export_project, check_project
            result = export_project(args.project, args.png_width) if args.command == "render" else check_project(args.project)
        elif args.command == "review":
            from .review import serve
            serve(args.project, port=args.port)
            return 0
        elif args.command == "feedback":
            result = record_feedback(args.project, args.target, args.message)
        elif args.command == "patch":
            result = apply_visual_patch(args.project, read_json(args.patch_file), args.reason)
        elif args.command == "rules":
            from .conference import import_profile
            result = import_profile(args.project, args.file)
        elif args.command == "package":
            from .delivery import package_project
            result = {"package": str(package_project(args.project, args.filename, args.printing_service, args.paper_id, args.track))}
        else:
            from .render import export_project, check_project
            if args.command == "approve":
                check_project(args.project)
                approve(args.project)
                result = check_project(args.project)
            elif args.command == "undo":
                undo(args.project)
                result = export_project(args.project)
            else:
                reopen(args.project)
                result = check_project(args.project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(f"poster-agent: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
