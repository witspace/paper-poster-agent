"""Fixed-size HTML posters, browser export, and checks of the actual artifacts."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import mimetypes
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import fitz
from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import sync_playwright

from .project import content_digest, load_spec, spec_digest


MM_TO_PX = 96 / 25.4
MM_TO_PT = 72 / 25.4


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _asset(project: Path, relative: str) -> Path:
    path = (project / relative).resolve()
    if not path.is_relative_to(project.resolve()):
        raise ValueError(f"Asset must stay within project: {relative}")
    if not path.is_file():
        raise FileNotFoundError(f"Missing poster asset: {relative}")
    return path


def _image_url(path: Path) -> str:
    if path.suffix.lower() == ".svg":
        from .ingest import validate_svg
        validate_svg(path)
    if path.suffix.lower() == ".pdf":
        with fitz.open(path) as document:
            data = document[0].get_pixmap(dpi=240).tobytes("png")
        mime = "image/png"
    else:
        data = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if not mime.startswith("image/"):
            raise ValueError(f"Unsupported poster image: {path.name}")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _color(value: str | None, default: str) -> str:
    return value if value and re.fullmatch(r"#[0-9a-fA-F]{3,8}", value) else default


def _positive(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return number


def _text(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _table_html(table: dict) -> str:
    """Render one evidence table; row indices include the header at index zero."""
    rows = table["rows"]
    if not rows:
        raise ValueError("An evidence table requires a header and rows")
    highlighted = table.get("highlight_rows", [])
    if any(not isinstance(index, int) or not 1 <= index < len(rows) for index in highlighted):
        raise ValueError("highlight_rows must index data rows; rows[0] is the header")
    result = '<div class="evidence-table">'
    if table.get("title"):
        result += f'<h3 class="table-title" data-content="table-title">{_text(table["title"])}</h3>'
    result += '<table><thead><tr>' + ''.join(f'<th data-content="cell">{_text(cell)}</th>' for cell in rows[0]) + '</tr></thead><tbody>'
    for index, row in enumerate(rows[1:], 1):
        row_class = ' class="row-highlight"' if index in highlighted else ""
        result += f'<tr{row_class}>' + ''.join(f'<td data-content="cell">{_text(cell)}</td>' for cell in row) + '</tr>'
    result += '</tbody></table>'
    if table.get("caption"):
        result += f'<p class="section-caption" data-content="table-caption">{_text(table["caption"])}</p>'
    return result + '</div>'


def build_html(project: str | Path) -> Path:
    """Build a self-contained HTML poster; no remote assets or invented branding."""
    project = Path(project).resolve()
    spec = load_spec(project)
    canvas = spec["canvas"]
    width = _positive(canvas["width_mm"], "canvas.width_mm")
    height = _positive(canvas["height_mm"], "canvas.height_mm")
    layout = spec.get("layout", {})
    layout_style = layout.get("style", "standard")
    if layout_style not in ("standard", "narrative"):
        raise ValueError("layout.style must be standard or narrative")
    columns = int(layout.get("columns", 2))
    if columns not in (1, 2, 3):
        raise ValueError("Supported column counts are 1, 2 and 3")
    margin = _positive(layout.get("margin_mm", 20), "layout.margin_mm")
    gap = _positive(layout.get("gap_mm", 10), "layout.gap_mm")
    title_pt = _positive(layout.get("title_pt", 74), "layout.title_pt")
    body_pt = _positive(layout.get("body_pt", 25), "layout.body_pt")
    theme = spec.get("theme", {})
    accent = _color(theme.get("accent"), "#087f8c")
    secondary = _color(theme.get("secondary"), "#dca543")
    ink = _color(theme.get("ink"), "#142d44")
    background = _color(theme.get("background"), "#ffffff")
    font = theme.get("font", "Arial")
    if not re.fullmatch(r"[A-Za-z0-9 _,-]{1,120}", font):
        raise ValueError("theme.font must contain local font family names")
    generic_fonts = {"sans-serif", "serif", "monospace", "system-ui"}
    font_stack = ",".join(name.strip() if name.strip() in generic_fonts else json.dumps(name.strip()) for name in font.split(","))
    conference = spec.get("conference", {})
    identity = " · ".join(str(conference[k]) for k in ("name", "year", "track") if conference.get(k))
    sections = []
    for index, section in enumerate(spec.get("sections", []), 1):
        sid = section["id"]
        kind = section.get("kind", "text")
        span = int(section.get("span", 1))
        if not 1 <= span <= columns:
            raise ValueError(f"Invalid span for section {sid}")
        contents = "".join(f'<p data-content="paragraph">{_text(p)}</p>' for p in section.get("paragraphs", []))
        if section.get("bullets"):
            contents += '<ul>' + ''.join(f'<li data-content="bullet">{_text(b)}</li>' for b in section["bullets"]) + '</ul>'
        if section.get("image"):
            relative = section["image"]
            image_height = section.get("image_height_mm")
            image_style = f' style="height:{_positive(image_height, sid + ".image_height_mm")}mm"' if image_height else ""
            contents += (f'<figure><img src="{_image_url(_asset(project, relative))}" '
                         f'data-asset-path="{_text(relative)}" alt="{_text(section.get("caption", section.get("heading", "")))}"{image_style}>')
            if section.get("caption"):
                contents += f'<figcaption data-content="caption">{_text(section["caption"])}</figcaption>'
            contents += '</figure>'
        if section.get("rows"):
            contents += _table_html({"rows":section["rows"], "highlight_rows":section.get("highlight_rows", [])})
        for table in section.get("tables", []):
            contents += _table_html(table)
        if section.get("caption") and not section.get("image"):
            contents += f'<p class="section-caption" data-content="caption">{_text(section["caption"])}</p>'
        heading = ""
        if section.get("heading") and not section.get("hide_heading"):
            number = f'<span class="section-number">{index:02d}</span>' if layout_style == "standard" else ""
            heading = f'<div class="section-heading">{number}<h2 data-content="heading">{_text(section["heading"])}</h2></div>'
        sections.append(f'''<section id="sec-{_text(sid)}" data-section-id="{_text(sid)}" class="section kind-{_text(kind)} span-{span}">
          {heading}
          <div class="section-content">{contents}</div>
        </section>''')
    subtitle = f'<p class="subtitle" data-content="subtitle">{_text(spec["subtitle"])}</p>' if spec.get("subtitle") else ""
    authors = f'<p class="authors" data-content="authors">{_text(spec["authors"])}</p>' if spec.get("authors") else ""
    affiliations = f'<p class="affiliations" data-content="affiliations">{_text(spec["affiliations"])}</p>' if spec.get("affiliations") else ""
    branding = spec.get("branding", {})
    logo = ""
    if branding.get("logo"):
        relative = branding["logo"]
        logo_width = _positive(branding.get("logo_width_mm", 120), "branding.logo_width_mm")
        logo = (f'<img class="brand-logo" src="{_image_url(_asset(project, relative))}" '
                f'data-asset-path="{_text(relative)}" data-asset-role="branding" '
                f'alt="{_text(branding.get("alt", "Laboratory logo"))}" style="width:{logo_width}mm">')
    document = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_text(spec.get("title", "Academic poster"))}</title>
<style>
@page {{ size: {width}mm {height}mm; margin: 0; }}
:root {{ --ink:{ink}; --accent:{accent}; --secondary:{secondary}; --background:{background}; --preview-scale:1; }}
* {{ box-sizing:border-box; }}
html,body {{ margin:0; padding:0; }}
body {{ font-family:{font_stack},"Microsoft YaHei",sans-serif; color:var(--ink); background:#e9edf0; }}
.stage {{ width:{width}mm; height:{height}mm; }}
.poster {{ position:relative; width:{width}mm; height:{height}mm; padding:{margin}mm; background:var(--background); display:flex; flex-direction:column; overflow:visible; }}
.poster::before {{ content:""; position:absolute; top:0; left:0; right:0; height:5mm; background:var(--accent); }}
.header {{ flex:0 0 auto; padding:5mm 0 11mm; border-bottom:1.2mm solid var(--ink); margin-bottom:{gap}mm; }}
.brand-line {{ display:flex; align-items:center; justify-content:space-between; gap:10mm; margin-bottom:6mm; }}
.brand-logo {{ display:block; flex:0 0 auto; height:auto; object-fit:contain; }}
.conference {{ margin:0; color:var(--accent); font-size:{body_pt * .74:.2f}pt; letter-spacing:.09em; text-transform:uppercase; font-weight:700; }}
h1 {{ font-size:{title_pt}pt; line-height:1.05; letter-spacing:-.025em; margin:0 0 7mm; font-weight:750; max-width:100%; overflow-wrap:break-word; }}
.authors {{ font-size:{body_pt * 1.08:.2f}pt; font-weight:600; line-height:1.3; margin:0 0 3mm; }}
.affiliations {{ font-size:{body_pt * .8:.2f}pt; color:#506477; line-height:1.3; margin:0; }}
.subtitle {{ margin:8mm 0 0; padding:5mm 6mm; border-left:1.5mm solid var(--secondary); background:#f4f7f8; font-size:{body_pt * 1.16:.2f}pt; font-weight:600; line-height:1.35; }}
.sections {{ display:grid; grid-template-columns:repeat({columns},minmax(0,1fr)); column-gap:{gap}mm; row-gap:{gap}mm; align-content:start; align-items:start; }}
.section {{ min-width:0; break-inside:avoid; }}
.span-2 {{ grid-column:span 2; }}
.span-3 {{ grid-column:span 3; }}
.section-heading {{ display:flex; align-items:baseline; gap:4mm; padding-bottom:3mm; margin-bottom:4mm; border-bottom:.45mm solid #cbd8df; }}
.section-number {{ color:var(--accent); font-size:{body_pt * .66:.2f}pt; letter-spacing:.04em; font-weight:700; }}
h2 {{ margin:0; color:var(--ink); font-size:{body_pt * 1.28:.2f}pt; font-weight:700; line-height:1.15; }}
.section-content {{ font-size:{body_pt}pt; line-height:1.36; }}
p {{ margin:0 0 4mm; }}
p:last-child {{ margin-bottom:0; }}
ul {{ margin:0; padding-left:7mm; }}
li {{ margin:0 0 3mm; padding-left:1mm; }}
li::marker {{ color:var(--accent); }}
figure {{ margin:4mm 0 0; }}
figure img {{ display:block; width:100%; height:auto; object-fit:contain; object-position:center; max-width:100%; }}
figcaption,.section-caption {{ margin-top:3mm; font-size:{body_pt * .78:.2f}pt; line-height:1.35; color:#415b6b; }}
table {{ width:100%; border-collapse:collapse; margin-top:4mm; font-size:{body_pt * .84:.2f}pt; line-height:1.3; }}
.evidence-table + .evidence-table {{ margin-top:5mm; }}
.table-title {{ margin:3mm 0 0; font-size:{body_pt}pt; font-weight:700; line-height:1.25; }}
.table-title + table {{ margin-top:2mm; }}
th,td {{ padding:3mm 2.5mm; border-bottom:.35mm solid #d8e1e6; text-align:left; overflow-wrap:anywhere; }}
thead {{ background:#edf5f6; color:var(--ink); }}
tbody tr:nth-child(even) {{ background:#f7f9fa; }}
tbody tr.row-highlight {{ background:#e6f2f3; color:var(--ink); font-weight:700; }}
tbody tr.row-highlight td:first-child {{ border-left:.7mm solid var(--accent); }}
.kind-callout {{ background:#edf5f6; padding:6mm; border-top:1mm solid var(--accent); }}
.kind-callout .section-heading {{ border-bottom:0; padding-bottom:0; }}
.layout-narrative .poster::before {{ height:3mm; }}
.layout-narrative .header {{ border-bottom:.45mm solid #cbd8df; padding-bottom:8mm; }}
.layout-narrative .subtitle {{ background:none; border:0; padding:0; margin-top:6mm; color:var(--accent); }}
.layout-narrative .sections {{ row-gap:{gap * .8}mm; }}
.layout-narrative .section-heading {{ border:0; padding:0; margin-bottom:3mm; }}
.layout-narrative h2 {{ font-size:{body_pt * 1.2:.2f}pt; color:var(--accent); font-weight:700; }}
.layout-narrative .kind-callout {{ background:none; border:0; padding:0; }}
.layout-narrative figure {{ margin-top:2mm; }}
.layout-narrative figcaption,.layout-narrative .section-caption {{ color:#415b6b; }}
.poster-footer {{ margin-top:auto; padding-top:5mm; border-top:.35mm solid #cbd8df; font-size:{body_pt * .58:.2f}pt; color:#607481; display:flex; justify-content:space-between; gap:6mm; }}
@media screen {{ .stage {{ width:calc({width * MM_TO_PX}px * var(--preview-scale)); height:calc({height * MM_TO_PX}px * var(--preview-scale)); }} .poster {{ transform:scale(var(--preview-scale)); transform-origin:top left; }} }}
@media print {{ html,body {{ width:{width}mm; height:{height}mm; background:var(--background); }} .stage,.poster {{ transform:none; }} * {{ print-color-adjust:exact; -webkit-print-color-adjust:exact; }} }}
</style></head><body class="layout-{layout_style}"><div class="stage"><main class="poster" id="poster" data-version="{int(spec.get('version', 1))}">
<header class="header" data-section-id="header"><div class="brand-line"><p class="conference">{_text(identity)}</p>{logo}</div><h1 data-content="title">{_text(spec.get('title',''))}</h1>{authors}{affiliations}{subtitle}</header>
<div class="sections">{''.join(sections)}</div>
<footer class="poster-footer"><span>{_text(identity)}</span><span>{_text(spec.get('footer', ''))}</span></footer>
</main></div><script>
function fitPreview() {{
  const naturalWidth={width * MM_TO_PX};
  const scale=new URLSearchParams(location.search).has('review') ? 1 : Math.min(1,innerWidth/naturalWidth);
  document.documentElement.style.setProperty('--preview-scale',String(scale));
}}
addEventListener('resize',fitPreview); fitPreview();
</script></body></html>'''
    exports = project / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    path = exports / "poster.html"
    path.write_text(document, encoding="utf-8")
    return path


def _measure(page) -> dict:
    return page.evaluate("""() => {
      const poster = document.querySelector('#poster');
      const base = poster.getBoundingClientRect();
      const rect = el => {const r=el.getBoundingClientRect(); return {x:r.x-base.x,y:r.y-base.y,width:r.width,height:r.height};};
      const elements = [...document.querySelectorAll('[data-content], [data-section-id], img[data-asset-path], .poster-footer')];
      const outside = elements.filter(el => {const r=el.getBoundingClientRect();return r.left<base.left-.8 || r.top<base.top-.8 || r.right>base.right+.8 || r.bottom>base.bottom+.8;})
        .map(el=>({section_id:el.closest('[data-section-id]')?.dataset.sectionId || 'footer',tag:el.tagName,...rect(el)}));
      const sections=[...document.querySelectorAll('[data-section-id]')].map(el=>({id:el.dataset.sectionId,...rect(el)}));
      const overlaps=[];
      for(let i=0;i<sections.length;i++) for(let j=i+1;j<sections.length;j++){
        const a=sections[i],b=sections[j];
        if(Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x)>.8 && Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y)>.8) overlaps.push([a.id,b.id]);
      }
      const images=[...document.querySelectorAll('img[data-asset-path]')].map(el=>{
        const r=el.getBoundingClientRect(),ratio=el.naturalWidth/el.naturalHeight;
        const w=Math.min(r.width,r.height*ratio),h=Math.min(r.height,r.width/ratio);
        return {path:el.dataset.assetPath,section_id:el.closest('[data-section-id]').dataset.sectionId,asset_role:el.dataset.assetRole||'figure',complete:el.complete&&el.naturalWidth>0,natural_width:el.naturalWidth,natural_height:el.naturalHeight,display_width_mm:w*25.4/96,display_height_mm:h*25.4/96};
      });
      const textElements=[...document.querySelectorAll('[data-content], .poster-footer, .section-number, .conference')].filter(e=>e.textContent.trim());
      return {canvas:rect(poster),sections,outside,overlaps,images,smallest_font_pt:Math.min(...textElements.map(e=>parseFloat(getComputedStyle(e).fontSize)*72/96))};
    }""")


def _browser(playwright):
    try:
        return playwright.chromium.launch()
    except Exception as error:
        raise RuntimeError("Chromium is unavailable. Run: python -m playwright install chromium") from error


def _open_page(browser, html_path: Path, spec: dict, scale: float = 1):
    canvas = spec["canvas"]
    context = browser.new_context(
        viewport={"width": math.ceil(canvas["width_mm"] * MM_TO_PX), "height": math.ceil(canvas["height_mm"] * MM_TO_PX)},
        device_scale_factor=scale,
    )
    page = context.new_page()
    page.emulate_media(media="print")
    page.goto(html_path.as_uri(), wait_until="load")
    page.evaluate("async () => {await document.fonts.ready; await Promise.all([...document.images].map(i=>i.decode()));}")
    return context, page


def export_project(project: str | Path, png_width: int | None = None) -> dict:
    """Export a draft or approved project; export alone does not confer approval."""
    project = Path(project).resolve()
    spec = load_spec(project)
    html_path = build_html(project)
    exports = project / "exports"
    canvas = spec["canvas"]
    pixel_width = int(png_width or canvas.get("png_width", 6000))
    if pixel_width < 3840:
        raise ValueError("PNG width must be at least 3840 pixels")
    css_width = canvas["width_mm"] * MM_TO_PX
    with sync_playwright() as playwright:
        browser = _browser(playwright)
        context, page = _open_page(browser, html_path, spec, pixel_width / css_width)
        metrics = _measure(page)
        page.screenshot(path=str(exports / "poster-4k.png"), clip={"x":0,"y":0,"width":css_width,"height":canvas["height_mm"] * MM_TO_PX}, timeout=120000)
        page.pdf(path=str(exports / "poster-print.pdf"), width=f'{canvas["width_mm"]}mm', height=f'{canvas["height_mm"]}mm', margin={"top":"0","right":"0","bottom":"0","left":"0"}, print_background=True, prefer_css_page_size=True)
        context.close()
        browser.close()
    # Chromium rounds paper sizes to its internal unit grid. Normalize the
    # page boxes to the requested physical size without flattening its content.
    with fitz.open(exports / "poster-print.pdf") as document:
        exact_box = fitz.Rect(0, 0, canvas["width_mm"] * MM_TO_PT, canvas["height_mm"] * MM_TO_PT)
        for page in document:
            page.set_mediabox(exact_box)
            page.set_cropbox(page.mediabox)
        document.saveIncr()
    with Image.open(exports / "poster-4k.png") as image:
        native_pixels = list(image.size)
        # Chromium rounds its fractional device scale; correct the output grid,
        # typically by one or two pixels, without claiming improved source detail.
        corrected = image.resize((pixel_width, round(pixel_width * canvas["height_mm"] / canvas["width_mm"])), Image.Resampling.LANCZOS) if image.width != pixel_width else image.copy()
    corrected.save(exports / "poster-4k.png")
    with Image.open(exports / "poster-4k.png") as image:
        image.thumbnail((1600, 2200), Image.Resampling.LANCZOS)
        image.save(exports / "poster-preview.png")
    with fitz.open(exports / "poster-print.pdf") as document:
        if len(document):
            page = document[0]
            page.get_pixmap(matrix=fitz.Matrix(1600 / page.rect.width, 1600 / page.rect.width), alpha=False).save(exports / "poster-pdf-preview.png")
    metrics["native_png_pixels"] = native_pixels
    manifest = {"version":spec.get("version"),"spec_sha256":spec_digest(spec),"created_at":datetime.now(timezone.utc).isoformat(),"metrics":metrics,
                "artifacts":{name:hashlib.sha256((exports/name).read_bytes()).hexdigest() for name in ["poster.html","poster-4k.png","poster-print.pdf","poster-preview.png","poster-pdf-preview.png"]}}
    _write(exports / "render-manifest.json", manifest)
    return check_project(project)


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", "", value).casefold()


def _content_strings(spec: dict) -> list[str]:
    values = [spec.get(k, "") for k in ("title", "subtitle", "authors", "affiliations")]
    for section in spec.get("sections", []):
        if not section.get("hide_heading"):
            values.append(section.get("heading", ""))
        values.append(section.get("caption", ""))
        values.extend(section.get("paragraphs", []))
        values.extend(section.get("bullets", []))
        values.extend(str(cell) for row in section.get("rows", []) for cell in row)
        for table in section.get("tables", []):
            values.extend([table.get("title", ""), table.get("caption", "")])
            values.extend(str(cell) for row in table["rows"] for cell in row)
    return [str(value) for value in values if value]


def check_project(project: str | Path) -> dict:
    """Verify current files, physical geometry, assets, evidence, and review gates."""
    project = Path(project).resolve()
    spec = load_spec(project)
    exports = project / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    evidence = _read(project / "evidence.json")
    conference = _read(project / "conference.json")
    manifest = _read(exports / "render-manifest.json")
    digest = spec_digest(spec)
    report = {"version":spec.get("version"),"spec_sha256":digest,"checked_at":datetime.now(timezone.utc).isoformat(),"print_ready":False,"required_checks":[],"issues":[],"metrics":{},"review":{}}

    def check(identifier, passed, detail, suggestion="", section_id=None):
        report["required_checks"].append({"id":identifier,"passed":bool(passed),"detail":detail})
        if not passed:
            report["issues"].append({"severity":"error","section_id":section_id,"message":detail,"suggestion":suggestion})

    files = [exports/name for name in ("poster.html","poster-4k.png","poster-print.pdf","poster-preview.png","poster-pdf-preview.png")]
    check("exports_present", all(path.is_file() for path in files), "All HTML, PNG, PDF and independent PDF preview exist" if all(p.is_file() for p in files) else "One or more export artifacts are missing", "Run poster-agent render for this version")
    artifacts = manifest.get("artifacts", {})
    current_files = bool(artifacts) and all((exports/name).is_file() and hashlib.sha256((exports/name).read_bytes()).hexdigest() == expected for name, expected in artifacts.items())
    current = manifest.get("spec_sha256") == digest and manifest.get("version") == spec.get("version") and current_files
    check("current_export", current, "Export matches current spec and artifact bytes" if current else "Export is stale, missing, or changed after export", "Export the current version again")

    from .conference import applicable_requirements
    requirements = applicable_requirements(conference)
    is_demo = conference.get("is_demo") is True
    report["is_demo"] = is_demo
    official_ppi = requirements.get("min_ppi")
    minimum = _positive(official_ppi, "conference.requirements.min_ppi") if official_ppi is not None else 150
    ppi_source = "conference requirement" if official_ppi is not None else "recommended target; not an official requirement"
    report["metrics"]["ppi_policy"] = {"minimum_ppi":official_ppi,"recommended_ppi":150,"source":ppi_source}
    unresolved = conference.get("unresolved", [])
    dimensions_known = requirements.get("width_mm") is not None and requirements.get("height_mm") is not None
    maximum_size = requirements.get("dimension_policy", "exact") == "maximum"
    dimensions_match = dimensions_known and all(
        float(spec["canvas"][key]) <= float(requirements[key]) + .1 if maximum_size else
        abs(float(requirements[key]) - float(spec["canvas"][key])) < .1
        for key in ("width_mm", "height_mm"))
    check("conference_dimensions", dimensions_match, "Canvas matches verified conference dimensions" if dimensions_match else "Conference dimensions are unverified or do not match the canvas", "Resolve official size requirements or record an explicitly confirmed printing size")
    orientation = requirements.get("orientation")
    actual_orientation = "landscape" if spec["canvas"]["width_mm"] > spec["canvas"]["height_mm"] else "portrait" if spec["canvas"]["width_mm"] < spec["canvas"]["height_mm"] else "square"
    check("conference_orientation", not orientation or orientation == "either" or str(orientation).lower() == actual_orientation, f"Canvas orientation is {actual_orientation}; requested orientation: {orientation or 'unspecified'}", "Use the required canvas orientation")
    rules_checked = (is_demo or bool(conference.get("sources"))) and not unresolved
    check("conference_requirements", rules_checked,
          "Explicit synthetic demo canvas; conference submission is disabled" if is_demo else
          "Conference requirements have sources and no unresolved entries" if rules_checked else
          f"Conference requirements need verification: {unresolved or 'no sources recorded'}",
          "Check the current year and track official guidelines")
    check("delivery_format", requirements.get("format") in (None, "PDF", "pdf", "application/pdf"),
          "Print delivery uses PDF" if requirements.get("format") in (None, "PDF", "pdf", "application/pdf") else
          f"Required delivery format is {requirements['format']}", "Add and verify the required delivery format")

    items = {item["id"]:item for item in evidence.get("items", [])}
    missing_refs = []
    for section in spec.get("sections", []):
        refs = section.get("source_refs", [])
        if not refs or any(ref not in items for ref in refs):
            missing_refs.append(section["id"])
    check("source_evidence", not missing_refs and bool(evidence.get("paper")), "Every section refers to recorded paper evidence" if not missing_refs and evidence.get("paper") else f"Missing paper evidence in sections: {', '.join(missing_refs) or 'paper record'}", "Add source evidence and review scientific claims against the paper")

    metrics = manifest.get("metrics", {}) if current else {}
    report["metrics"]["browser"] = metrics
    if metrics:
        check("layout_bounds", not metrics.get("outside") and not metrics.get("overlaps"), "No content lies outside the canvas and section boxes do not overlap" if not metrics.get("outside") and not metrics.get("overlaps") else "Content overflow or overlapping sections detected", "Reduce content, resize images, or adjust grid spacing")
        for sid in sorted({element["section_id"] for element in metrics.get("outside", [])}):
            report["issues"].append({"severity":"error","section_id":sid,"message":f"Section {sid} extends beyond the printable canvas","suggestion":"Reduce its text or image height, or move content into available grid space"})
        for left, right in metrics.get("overlaps", []):
            report["issues"].append({"severity":"error","section_id":left,"message":f"Section {left} overlaps {right}","suggestion":"Adjust the grid or section size and re-render"})
        ppi_records = []
        for image in metrics.get("images", []):
            svg = Path(image["path"]).suffix.lower() == ".svg"
            embedded_raster = svg and any(element.tag.split("}")[-1] == "image" for element in ET.parse(_asset(project, image["path"])).iter())
            vector = svg and not embedded_raster
            ppi = None if svg else min(image["natural_width"] / (image["display_width_mm"] / 25.4), image["natural_height"] / (image["display_height_mm"] / 25.4))
            ppi_records.append({**image,"vector":vector,"embedded_raster":embedded_raster,"effective_ppi":round(ppi, 1) if ppi else None,"minimum_ppi":official_ppi,"recommended_ppi":150,"threshold_source":ppi_source,"meets_target":None if embedded_raster else vector or ppi >= minimum,"passed":image["complete"] and (svg or official_ppi is None or ppi >= minimum)})
        report["metrics"]["images"] = ppi_records
        failed = [r for r in ppi_records if not r["passed"]]
        detail = "All placed images load; effective PPI is reported separately" if official_ppi is None else "All placed images meet the official effective PPI threshold"
        check("image_resolution", not failed, detail if not failed else "Placed images are missing or below the official effective PPI threshold", "Use original vector assets or higher-resolution paper figures; avoid upscaling")
        for image in ppi_records:
            if image["effective_ppi"] is not None and image["effective_ppi"] < minimum:
                target = f"official minimum {minimum:g}" if official_ppi is not None else "recommended 150 PPI; conference does not specify a minimum"
                report["issues"].append({"severity":"error" if official_ppi is not None else "warning","section_id":image["section_id"],"message":f'{image["path"]}: original {image["natural_width"]} × {image["natural_height"]} px placed at {image["display_width_mm"]:.1f} × {image["display_height_mm"]:.1f} mm gives {image["effective_ppi"]} effective PPI; {target}',"suggestion":"Use a higher-resolution original, reduce its printed size, or review the print preview; a 4K poster export does not increase source detail"})
    else:
        check("layout_bounds", False, "Current browser geometry measurements are unavailable", "Export the current version")
        check("image_resolution", False, "Current image placement measurements are unavailable", "Export the current version")

    png_path = exports / "poster-4k.png"
    if png_path.exists():
        with Image.open(png_path) as image:
            png_size = list(image.size)
        report["metrics"]["png_pixels"] = png_size
        check("png_resolution", png_size[0] >= 3840 and png_size[0] * png_size[1] >= 3840 * 2160, f"PNG is {png_size[0]} × {png_size[1]} pixels", "Export a wider PNG")
    else:
        check("png_resolution", False, "High-resolution PNG is missing", "Export the current version")

    pdf_path = exports / "poster-print.pdf"
    size_limit = requirements.get("max_file_size_mb")
    if size_limit is not None:
        actual_size = pdf_path.stat().st_size / 1_000_000 if pdf_path.is_file() else None
        check("pdf_file_size", actual_size is not None and actual_size <= _positive(size_limit, "max_file_size_mb"),
              f"PDF size is {actual_size} MB; official limit {size_limit} MB", "Reduce file size while preserving original scientific detail")
    if pdf_path.exists():
        with fitz.open(pdf_path) as document:
            measured_mm = [[page.rect.width/MM_TO_PT,page.rect.height/MM_TO_PT] for page in document]
            actual_mm = [[round(value, 6) for value in size] for size in measured_mm]
            size_ok = len(document) == 1 and all(abs(measured-target) < .001 for measured,target in zip(measured_mm[0], [spec["canvas"]["width_mm"], spec["canvas"]["height_mm"]]))
            report["metrics"]["pdf"] = {"pages":len(document),"page_sizes_mm":actual_mm}
            check("pdf_geometry", size_ok, f"PDF has {len(document)} page(s), measured sizes {actual_mm} mm", "Fix print CSS page size and overflow before printing")
            fonts = {}
            for page in document:
                for font in page.get_fonts(full=True):
                    xref, extension, font_type, name = font[:4]
                    if xref not in fonts:
                        data = document.extract_font(xref)[3] if xref else b""
                        fonts[xref] = {"name":name,"type":font_type,"embedded":bool(data),"bytes":len(data)}
            report["metrics"]["fonts"] = list(fonts.values())
            check("font_embedding", bool(fonts) and all(f["embedded"] for f in fonts.values()), "All PDF fonts contain embedded font data" if fonts and all(f["embedded"] for f in fonts.values()) else "PDF has unembedded fonts or no extractable fonts", "Use locally installed embeddable fonts and re-export")
            pdf_text = _normalize("\n".join(page.get_text() for page in document))
            missing_text = [value for value in _content_strings(spec) if _normalize(value) not in pdf_text]
            report["metrics"]["pdf_missing_text"] = missing_text
            check("pdf_content", not missing_text, "All configured text appears in extracted PDF text" if not missing_text else f"PDF text extraction could not find {len(missing_text)} configured text item(s)", "Inspect clipped or missing text; check unusual glyph extraction manually")
            raster_images = []
            for page_number, page in enumerate(document, 1):
                seen = set()
                for image in page.get_images(full=True):
                    xref, _, pixels_x, pixels_y = image[:4]
                    if xref in seen:
                        continue
                    seen.add(xref)
                    for rect, transform in page.get_image_rects(xref, transform=True):
                        scale_x, scale_y = math.hypot(transform.a, transform.b), math.hypot(transform.c, transform.d)
                        if scale_x <= 0 or scale_y <= 0:
                            continue
                        ppi = min(pixels_x * 72 / scale_x, pixels_y * 72 / scale_y)
                        raster_images.append({"page":page_number,"xref":xref,"pixels":[pixels_x,pixels_y],"placement_mm":[round(rect.width/MM_TO_PT, 2),round(rect.height/MM_TO_PT, 2)],"effective_ppi":round(ppi, 1),"minimum_ppi":official_ppi,"recommended_ppi":150,"threshold_source":ppi_source,"meets_target":ppi >= minimum,"passed":official_ppi is None or ppi >= minimum})
            report["metrics"]["pdf_raster_images"] = raster_images
            low_ppi = [image for image in raster_images if not image["meets_target"]]
            passed = official_ppi is None or not low_ppi
            detail = "Final PDF raster PPI measured, including images embedded in SVG; no official minimum specified" if official_ppi is None else f"Final PDF raster placements checked against official minimum {minimum:g} PPI"
            check("pdf_image_resolution", passed, detail if passed else f"Final PDF has {len(low_ppi)} raster image placement(s) below official minimum {minimum:g} PPI", "Inspect PDF raster placements and replace low-resolution figures")
            if low_ppi and official_ppi is None:
                report["issues"].append({"severity":"warning","section_id":None,"message":f"Final PDF has {len(low_ppi)} raster image placement(s) below the recommended 150 PPI; lowest {min(image['effective_ppi'] for image in low_ppi):g} PPI. The conference does not specify a minimum.","suggestion":"Inspect these regions at actual print scale; retain original data and request higher-resolution originals where available"})
        if (exports/"poster-preview.png").exists() and (exports/"poster-pdf-preview.png").exists():
            with Image.open(exports/"poster-preview.png") as browser_preview, Image.open(exports/"poster-pdf-preview.png") as pdf_preview:
                a = browser_preview.convert("RGB").resize((1000,round(1000*browser_preview.height/browser_preview.width)))
                b = pdf_preview.convert("RGB").resize(a.size)
                difference = sum(ImageStat.Stat(ImageChops.difference(a,b)).mean)/3/255
            report["metrics"]["html_pdf_mean_pixel_difference"] = round(difference, 5)
            check("html_pdf_consistency", difference < .10, f"Independent HTML/PDF preview mean pixel difference: {difference:.3%}", "Compare the actual PDF with the accepted HTML preview")
        else:
            check("html_pdf_consistency", False, "HTML or independently rendered PDF preview is missing", "Export the current version")
    else:
        for identifier in ("pdf_geometry","font_embedding","pdf_content","pdf_image_resolution","html_pdf_consistency"):
            check(identifier, False, "PDF export is missing", "Export the current version")

    # Browser PDF is RGB and does not claim PDF/X, ICC conversion, or printer certification.
    unsupported = [key for key in ("pdf_standard","color_profile") if requirements.get(key)]
    if float(requirements.get("bleed_mm") or 0) > 0:
        unsupported.append("bleed_mm")
    check("print_profile", not unsupported, "No additional PDF/X, color-profile, or bleed requirements recorded" if not unsupported else f"Printer-specific output requirements need a verified production step: {', '.join(unsupported)}", "Configure the required print conversion and validate its final file")

    approval = spec.get("approval") or {}
    approval_current = (approval.get("version") == spec.get("version") and approval.get("sha256") == digest and current and
                        bool(approval.get("artifacts_sha256")) and approval["artifacts_sha256"] == artifacts)
    content_review = evidence.get("content_review", {})
    content_current = content_review.get("content_sha256") == content_digest(spec)
    content_accepted = content_current and content_review.get("status") in ("accepted","approved") and not content_review.get("issues")
    visual_review = spec.get("visual_review", {}) or {}
    visual_accepted = visual_review.get("status") in ("accepted","approved") and visual_review.get("version") == spec.get("version") and visual_review.get("sha256") == digest
    report["review"] = {"human_approval_current":approval_current,"content_accepted":content_accepted,"visual_accepted_current":visual_accepted}
    for name, passed, suggestion in [("human approval",approval_current,"Review this exact version and select Approve"),("content review",content_accepted,"Verify scientific content against the paper"),("visual review",visual_accepted,"Review reference, poster, and PDF; record acceptance for this exact version")]:
        if not passed:
            report["issues"].append({"severity":"review","section_id":None,"message":f"Pending {name}","suggestion":suggestion})
    report["technical_pass"] = all(item["passed"] for item in report["required_checks"])
    report["content_pass"] = content_accepted and next(item["passed"] for item in report["required_checks"] if item["id"] == "source_evidence")
    report["print_ready"] = not is_demo and report["technical_pass"] and report["content_pass"] and approval_current and visual_accepted
    _write(exports / "quality-report.json", report)
    return report
