"""Read-only setup diagnostics; checking API configuration never makes an API call."""
from __future__ import annotations

import importlib
import importlib.metadata
import os
import shutil
import sys
import tempfile
from pathlib import Path


def doctor(workspace: str | Path | None = None, check_browser: bool = True) -> dict:
    """Inspect this Python environment and both the local and API entry points."""
    root = Path(workspace or Path.cwd()).resolve()
    python = f'"{sys.executable}"'
    repair = []
    packages = {}
    for package, module in (("PyMuPDF", "fitz"), ("Pillow", "PIL"),
                            ("playwright", "playwright.sync_api"), ("openai", "openai")):
        try:
            importlib.import_module(module)
            version = importlib.metadata.version(package)
            packages[package] = {"available": True, "version": version}
        except (ImportError, importlib.metadata.PackageNotFoundError):
            packages[package] = {"available": False, "version": None}
            repair.append(f'{python} -m pip install "{package}"')

    writable = False
    try:
        with tempfile.TemporaryFile(dir=root):
            writable = True
    except OSError:
        repair.append("Choose an existing workspace directory that this user can write to.")

    cli = shutil.which("poster-agent")
    if cli is None:
        candidate = Path(sys.executable).parent / ("poster-agent.exe" if os.name == "nt" else "poster-agent")
        cli = str(candidate) if candidate.is_file() else None
    if cli is None:
        repair.append(f'{python} -m pip install -e .  (run from the poster-agent repository)')

    browser = {"available": False, "launch_checked": bool(check_browser), "executable": None}
    if packages["playwright"]["available"]:
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as playwright:
                browser["executable"] = playwright.chromium.executable_path
                if check_browser:
                    chromium = playwright.chromium.launch()
                    chromium.close()
                    browser["available"] = True
                else:
                    browser["available"] = Path(browser["executable"]).is_file()
        except Exception:
            # The error may contain local launch arguments; report the actionable
            # installation check without copying environment values or secrets.
            browser["available"] = False
    if not browser["available"]:
        repair.append(f"{python} -m playwright install chromium")

    model = os.environ.get("POSTER_MODEL", "").strip() or None
    key_present = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    python_supported = sys.version_info >= (3, 10)
    if not python_supported:
        repair.append("Use Python 3.10 or newer and install this project in that environment.")
    local_ready = python_supported and writable and cli is not None and browser["available"] and all(
        packages[name]["available"] for name in ("PyMuPDF", "Pillow", "playwright"))
    api_ready = local_ready and packages["openai"]["available"] and bool(model) and key_present
    if not model:
        repair.append("Set POSTER_MODEL to the Responses API model you selected for this project.")
    if not key_present:
        repair.append("Set OPENAI_API_KEY in your local environment for the API entry point.")
    report = {
        "status": "ready" if api_ready else "local_ready" if local_ready else "needs_setup",
        "local_ready": bool(local_ready), "api_ready": bool(api_ready),
        "python": {"executable": sys.executable, "version": sys.version.split()[0], "supported": python_supported},
        "packages": packages, "chromium": browser, "cli_path": cli,
        "workspace": {"path": str(root), "writable": writable},
        "api": {"model": model, "image_model": os.environ.get("POSTER_IMAGE_MODEL", "gpt-image-2"),
                "key_present": key_present, "network_verified": False},
        "entry_points": {
            "codex": "Local extraction, rendering, checks and review; the current Codex session supplies research and design.",
            "api": "Standalone research, draft, reference, critique and feedback require configured API access; credentials and model access were not tested."},
        "repair": repair,
    }
    secret = os.environ.get("OPENAI_API_KEY", "")
    def scrub(value):
        if isinstance(value, str):
            return value.replace(secret, "[redacted credential]") if secret else value
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        return value
    return scrub(report)
