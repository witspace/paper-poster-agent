"""Preserve paper and supplied originals; previews never stand in for source detail."""
from pathlib import Path
import hashlib
import math
import re
import shutil
import xml.etree.ElementTree as ET

import fitz
from PIL import Image

from .project import project_path, read_json, write_json


SUPPORTED_ASSETS = {".pdf", ".svg", ".png", ".jpg", ".jpeg"}


def validate_svg(path):
    """Accept self-contained static SVGs without executable or remote resources."""
    text = Path(path).read_text(encoding="utf-8-sig")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I):
        raise ValueError(f"SVG must not contain a DTD or entities: {Path(path).name}")
    if re.search(r"<\?xml-stylesheet", text, re.I):
        raise ValueError(f"SVG external stylesheets are not supported: {Path(path).name}")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise ValueError(f"Invalid SVG: {Path(path).name}") from error
    if root.tag.split("}")[-1] != "svg":
        raise ValueError(f"Expected an SVG root: {Path(path).name}")
    for element in root.iter():
        tag = element.tag.split("}")[-1].lower()
        if tag in {"script", "foreignobject", "animate", "animatemotion", "animatetransform", "set"}:
            raise ValueError(f"SVG must be static and non-executable: {Path(path).name}")
        for key, value in element.attrib.items():
            local_key = key.split("}")[-1].lower()
            if local_key.startswith("on"):
                raise ValueError(f"SVG event handlers are not supported: {Path(path).name}")
            if local_key == "base":
                raise ValueError(f"SVG resource base URLs are not supported: {Path(path).name}")
            if local_key in {"href", "src"} and not (
                value.startswith("#") or re.fullmatch(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=\s]+", value)
            ):
                raise ValueError(f"SVG resources must be embedded or local fragments: {Path(path).name}")
        css = " ".join(element.attrib.values()) + " " + ((element.text or "") if tag == "style" else "")
        if "\\" in css:
            raise ValueError(f"SVG CSS escapes are not supported: {Path(path).name}")
        if re.search(r"@import|javascript\s*:|expression\s*\(", css, re.I):
            raise ValueError(f"SVG contains executable or external styles: {Path(path).name}")
        for resource in re.findall(r"url\s*\(\s*['\"]?([^)'\"]+)", css, re.I):
            if not resource.strip().startswith("#"):
                raise ValueError(f"SVG CSS resources must be local fragments: {Path(path).name}")
    return root


def _asset_files(assets_dir, project):
    if assets_dir is None:
        return []
    directory = Path(assets_dir).resolve()
    if not directory.is_dir():
        raise ValueError("Original asset directory does not exist")
    if Path(project).resolve().is_relative_to(directory):
        raise ValueError("Keep the output project outside the original asset directory")
    files = []
    for path in sorted(directory.rglob("*"), key=lambda p: p.relative_to(directory).as_posix().casefold()):
        if path.suffix.lower() not in SUPPORTED_ASSETS or not path.is_file():
            continue
        if not path.resolve().is_relative_to(directory) or path.is_symlink():
            raise ValueError("Original assets must be files inside the supplied directory")
        if path.suffix.lower() == ".svg":
            validate_svg(path)
        elif path.suffix.lower() == ".pdf":
            with fitz.open(path) as document:
                if not document.is_pdf or document.needs_pass or not len(document):
                    raise ValueError(f"Original figure PDF must be readable: {path.name}")
        else:
            with Image.open(path) as image:
                image.verify()
        files.append((path, path.relative_to(directory)))
    return files


def _preview(document, path):
    page = document[0]
    scale = min(1600 / max(page.rect.width, page.rect.height), 2)
    page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(path)


def _catalog_entry(identifier, path, preview, source_file, source_type, **details):
    return {"id": identifier, "path": path, "preview": preview, "type": source_type,
            "source_file": source_file, "preview_note": "Preview only; use the original/vector path in the poster. Enlarging an export does not add source detail.",
            **details}


def _import_assets(project, files):
    entries = []
    for original, relative in files:
        source_relative = (Path("source/original-assets") / relative).as_posix()
        source = project_path(project, source_relative)
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, source)
        suffix = original.suffix.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", relative.as_posix().lower()).strip("-")
        identifier = "original-" + slug + "-" + hashlib.sha256(relative.as_posix().encode()).hexdigest()[:8]
        common = {"original_relative_path": relative.as_posix(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        if suffix == ".pdf":
            with fitz.open(source) as document:
                for index, page in enumerate(document):
                    stem = (Path("assets/imported") / relative / f"page-{index + 1:03d}").as_posix()
                    svg = project_path(project, stem + ".svg")
                    svg.parent.mkdir(parents=True, exist_ok=True)
                    svg.write_text(page.get_svg_image(text_as_path=True), encoding="utf-8")
                    with fitz.open(stream=svg.read_bytes(), filetype="svg") as preview_document:
                        _preview(preview_document, project_path(project, stem + ".png"))
                    rasters = [{"pixels": [image[2], image[3]]} for image in page.get_images(full=True)]
                    entries.append(_catalog_entry(f"{identifier}-p{index + 1:03d}", stem + ".svg", stem + ".png", source_relative,
                                                   "pdf", page=index + 1, original_size_pt=[page.rect.width, page.rect.height],
                                                   vector_preserved=True, embedded_rasters=rasters, **common))
        else:
            preview_relative = (Path("assets/previews") / (relative.as_posix() + ".png")).as_posix()
            preview = project_path(project, preview_relative)
            preview.parent.mkdir(parents=True, exist_ok=True)
            if suffix == ".svg":
                with fitz.open(source) as document:
                    _preview(document, preview)
                details = {"vector_preserved": True}
            else:
                with Image.open(source) as image:
                    details = {"native_pixels": list(image.size), "vector_preserved": False}
                    image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                    image.convert("RGB").save(preview)
            entries.append(_catalog_entry(identifier, source_relative, preview_relative, source_relative,
                                           suffix.lstrip("."), **common, **details))
    write_json(project / "assets/catalog.json", {"entries": entries})
    return entries


def ingest(project, paper, identity, assets_dir=None):
    project = Path(project)
    managed = ("source/paper.pdf", "poster.json", "conference.json", "evidence.json", "assets/catalog.json", "run-report.json")
    if any((project / name).exists() for name in managed):
        raise ValueError("Project already contains managed inputs; choose a new project directory or resume it")
    with fitz.open(paper) as document:
        if not document.is_pdf or document.needs_pass or not len(document):
            raise ValueError("Paper must be a readable, non-empty PDF")
    files = _asset_files(assets_dir, project)
    source = project / "source"
    source.mkdir(parents=True, exist_ok=True)
    (project / "assets").mkdir(exist_ok=True)
    (project / "reference").mkdir(exist_ok=True)
    shutil.copy2(paper, source / "paper.pdf")
    pages = []
    with fitz.open(source / "paper.pdf") as document:
        for index, page in enumerate(document):
            pages.append(f"\n--- PAPER PAGE {index + 1} ---\n{page.get_text()}")
            page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7)).save(source / f"page-{index + 1:02d}.png")
    (source / "paper.txt").write_text("".join(pages), encoding="utf-8")
    entries = _import_assets(project, files)
    write_json(project / "conference.json", {"identity": identity, "checked_at": None,
               "sources": [], "requirements": {}, "unresolved": ["Official physical dimensions must be verified"], "warnings": []})
    write_json(project / "evidence.json", {"paper": {"path": "source/paper.pdf", "sha256": hashlib.sha256((source / "paper.pdf").read_bytes()).hexdigest()},
               "items": [], "content_review": {"status": "pending", "issues": []}})
    return {"project": str(project.resolve()), "pages": len(pages), "assets": len(entries), "status": "paper_ingested"}


def extract_regions(project, regions):
    """Extract exact, one-based PDF regions and append their original provenance."""
    project = Path(project)
    provenance_path = project / "assets/provenance.json"
    provenance = read_json(provenance_path) if provenance_path.exists() else []
    catalog_path = project / "assets/catalog.json"
    catalog = read_json(catalog_path) if catalog_path.exists() else {"entries": []}
    existing = {entry["id"] for entry in provenance} | {entry["id"] for entry in catalog["entries"]}
    validated = []
    with fitz.open(project / "source/paper.pdf") as document:
        for region in regions:
            name = region["id"]
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", name):
                raise ValueError("Invalid figure ID")
            if name in existing or project_path(project, f"assets/{name}.svg").exists() or project_path(project, f"assets/{name}.png").exists():
                raise ValueError(f"Figure ID already exists: {name}")
            existing.add(name)
            number = region["page"]
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= len(document):
                raise ValueError("Figure page must be a one-based integer within the paper")
            box = region["bbox"]
            if not isinstance(box, (list, tuple)) or len(box) != 4 or not all(
                not isinstance(v, bool) and isinstance(v, (float, int)) and math.isfinite(v) and 0 <= v <= 1 for v in box
            ) or box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError("Invalid normalized figure region; use x0,y0,x1,y1 in 0..1")
            validated.append((region, number, box))
        result = []
        for region, number, box in validated:
            name = region["id"]
            page = document[number - 1]
            rect = fitz.Rect(box[0]*page.rect.width, box[1]*page.rect.height, box[2]*page.rect.width, box[3]*page.rect.height)
            with fitz.open() as cropped:
                cropped.new_page(width=rect.width, height=rect.height).show_pdf_page(fitz.Rect(0, 0, rect.width, rect.height), document, number - 1, clip=rect)
                project_path(project, f"assets/{name}.svg").write_text(cropped[0].get_svg_image(text_as_path=True), encoding="utf-8")
                cropped[0].get_pixmap(dpi=160).save(project_path(project, f"assets/{name}.png"))
            item = {**region, "svg": f"assets/{name}.svg", "png": f"assets/{name}.png", "source": "source/paper.pdf", "note": "Original PDF region; visual crop verification required"}
            result.append(item)
            catalog["entries"].append(_catalog_entry(name, item["svg"], item["png"], item["source"], "pdf-region", page=number, bbox=list(box), vector_preserved=True))
    write_json(provenance_path, provenance + result)
    write_json(catalog_path, catalog)
    return result
