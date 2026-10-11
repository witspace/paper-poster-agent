"""An explicit offline demonstration made entirely from original synthetic material."""
from pathlib import Path
import tempfile

import fitz

from .ingest import ingest
from .project import content_digest, read_json, write_json
from .render import export_project


TITLE = "TRACE: Evidence-Linked Visual Summaries"
DEMO_NOTICE = "DEMO / SYNTHETIC DATA - Original fixture, not a published study or conference acceptance."
PROBLEM = (
    "A visual summary is easier to inspect when the question, workflow and supporting evidence form one continuous story. "
    "Disconnected cards can hide the relationship between a claim and its source. TRACE is a synthetic workflow illustration, "
    "created to exercise figure preservation, readable evidence tables and local revision."
)
METHOD = (
    "Attach a stable evidence identifier to every section. Preserve the supplied vector figures and their labels, "
    "then place the protocol beside the comparison. A reviewer can select a region, request a local visual change, "
    "compare the new version and freeze the exact version when satisfied."
)
PROTOCOL = (
    "The demonstration uses three hypothetical layouts and twelve invented review tasks per layout. "
    "The table contains illustrative values only: disconnected layout, 14.0 minutes and 65 percent traceable claims; "
    "evidence-linked layout, 9.5 minutes and 87 percent; local revision, 6.0 minutes and 100 percent. "
    "No participants were recruited and no experiment was conducted. These numbers test rendering and evidence links."
)
LIMITS = (
    "The values cannot support a scientific performance claim. The demo does not test research correctness, human preferences "
    "or real printing conditions. Its deterministic source files support software checks: single-page A0 geometry, "
    "embedded fonts, preserved vectors, full text and independent HTML/PDF previews. The configured page is 841 by 1189 mm; "
    "the PNG output is 6000 by 8483 pixels. Neither technical checks nor an export substitute for human design approval."
)


def _svg(body, width, height):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
    <rect width="{width}" height="{height}" fill="#ffffff"/>
    <g font-family="Arial, sans-serif" fill="#183448">{body}</g></svg>'''


def _original_figures(directory):
    problem = '''
      <text x="35" y="40" font-size="24" font-weight="700">Connect the question to its evidence</text>
      <rect x="35" y="70" width="225" height="115" rx="8" fill="#edf4f6"/>
      <text x="55" y="105" font-size="21" font-weight="700">Research question</text>
      <text x="55" y="140" font-size="16">Meaning of the claim?</text>
      <text x="55" y="165" font-size="16">Where is its source?</text>
      <path d="M280 125 H350 M335 112 L350 125 L335 138" fill="none" stroke="#157b86" stroke-width="5"/>
      <rect x="370" y="70" width="225" height="115" rx="8" fill="#e7f3f2"/>
      <text x="390" y="105" font-size="21" font-weight="700">Source relationship</text>
      <text x="390" y="140" font-size="16">Paper page + source figure</text>
      <text x="390" y="165" font-size="16">Protocol + exact numbers</text>
      <path d="M615 125 H685 M670 112 L685 125 L670 138" fill="none" stroke="#157b86" stroke-width="5"/>
      <rect x="705" y="70" width="225" height="115" rx="8" fill="#fff3df"/>
      <text x="725" y="105" font-size="21" font-weight="700">Reviewer decision</text>
      <text x="725" y="140" font-size="16">Inspect, revise or approve</text>
      <text x="725" y="165" font-size="16">Freeze the exact version</text>
      <text x="35" y="225" font-size="17">DEMO - original vector drawing; all labels are preserved in the print output.</text>'''
    workflow = '''
      <text x="35" y="40" font-size="24" font-weight="700">A traceable local revision loop</text>
      <rect x="35" y="70" width="245" height="110" rx="8" fill="#edf4f6"/>
      <text x="55" y="105" font-size="22" font-weight="700">Preserve originals</text>
      <text x="55" y="137" font-size="18">Vector path + source file</text>
      <text x="55" y="162" font-size="18">Preview is for inspection</text>
      <path d="M295 125 H345 M330 112 L345 125 L330 138" fill="none" stroke="#157b86" stroke-width="5"/>
      <rect x="360" y="70" width="245" height="110" rx="8" fill="#e7f3f2"/>
      <text x="380" y="105" font-size="22" font-weight="700">Render + compare</text>
      <text x="380" y="137" font-size="18">Reference / HTML / PDF</text>
      <text x="380" y="162" font-size="18">Check sources and geometry</text>
      <path d="M620 125 H670 M655 112 L670 125 L655 138" fill="none" stroke="#157b86" stroke-width="5"/>
      <rect x="685" y="70" width="245" height="110" rx="8" fill="#fff3df"/>
      <text x="705" y="105" font-size="22" font-weight="700">Human review</text>
      <text x="705" y="137" font-size="18">Point to a specific region</text>
      <text x="705" y="162" font-size="18">Explain the desired change</text>
      <path d="M805 200 V245 H480 V200 M467 215 L480 200 L493 215" fill="none" stroke="#d39439" stroke-width="5"/>
      <text x="505" y="230" font-size="18">Local revision + version comparison</text>
      <text x="35" y="295" font-size="17">Approval binds to the current version. A new edit requires a new inspection.</text>'''
    chart = '''
      <text x="35" y="42" font-size="25" font-weight="700">Illustrative inspection time</text>
      <text x="35" y="73" font-size="18" fill="#587080">SYNTHETIC DATA - not measured participants</text>
      <path d="M100 115 V455 H575" fill="none" stroke="#183448" stroke-width="2"/>
      <text x="38" y="285" font-size="18" transform="rotate(-90 38 285)">Minutes per review task</text>
      <path d="M100 115 H575 M100 200 H575 M100 285 H575 M100 370 H575" fill="none" stroke="#dbe5ea" stroke-width="1"/>
      <text x="73" y="461" font-size="18">0</text><text x="65" y="376" font-size="18">4</text>
      <text x="65" y="291" font-size="18">8</text><text x="55" y="206" font-size="18">12</text><text x="55" y="121" font-size="18">16</text>
      <rect x="135" y="157.5" width="95" height="297.5" fill="#879eaa"/>
      <rect x="295" y="253.125" width="95" height="201.875" fill="#157b86"/>
      <rect x="455" y="327.5" width="95" height="127.5" fill="#d39439"/>
      <text x="158" y="140" font-size="24" font-weight="700">14.0</text>
      <text x="321" y="237" font-size="24" font-weight="700">9.5</text>
      <text x="480" y="311" font-size="24" font-weight="700">6.0</text>
      <text x="132" y="490" font-size="18">Disconnected</text><text x="295" y="490" font-size="18">Evidence links</text><text x="456" y="490" font-size="18">Local revision</text>
      <text x="35" y="540" font-size="17">12 invented tasks per layout; this chart exercises the export pipeline.</text>'''
    for name, body, width, height in (("question.svg", problem, 965, 250), ("workflow.svg", workflow, 965, 320), ("illustrative-results.svg", chart, 625, 565)):
        (directory / name).write_text(_svg(body, width, height), encoding="utf-8")


def _source_paper(path):
    with fitz.open() as document:
        for index, sections in enumerate((("Question", PROBLEM, "Workflow", METHOD), ("Illustrative protocol", PROTOCOL, "Limits", LIMITS)), 1):
            page = document.new_page(width=595, height=842)
            page.insert_text((42, 50), TITLE, fontsize=17, color=(.09, .35, .41))
            page.insert_text((42, 76), "DEMO / SYNTHETIC DATA - not a scientific publication", fontsize=10)
            position = 122
            for heading, paragraph in zip(sections[::2], sections[1::2]):
                page.insert_text((42, position), heading, fontsize=14)
                position += 20
                remaining = page.insert_textbox(fitz.Rect(42, position, 550, position + 190), paragraph, fontsize=11, lineheight=1.45)
                if remaining < 0:
                    raise ValueError("Synthetic source paper text does not fit")
                position += 215
            page.insert_text((42, 802), f"Original Poster Agent demonstration fixture - page {index}", fontsize=9)
        document.set_metadata({"title": TITLE, "author": "Poster Agent Demo Team", "subject": DEMO_NOTICE})
        document.save(path)


def create_demo(project, png_width=6000):
    """Create and render an explicit synthetic demo; never contact a model or a website."""
    project = Path(project).resolve()
    if project.exists() and any(project.iterdir()):
        raise ValueError("Demo requires a new or empty project directory")
    identity = {"name": "Demonstration", "year": 2026, "track": "Synthetic example"}
    with tempfile.TemporaryDirectory() as temporary:
        inputs = Path(temporary)
        figures = inputs / "figures"
        figures.mkdir()
        _original_figures(figures)
        _source_paper(inputs / "demo-paper.pdf")
        ingest(project, inputs / "demo-paper.pdf", identity, assets_dir=figures)
    catalog = read_json(project / "assets/catalog.json")
    assets = {Path(entry["original_relative_path"]).name: entry["path"] for entry in catalog["entries"]}
    spec = {
        "schema_version": 1, "version": 1, "status": "review", "conference": identity,
        "canvas": {"width_mm": 841, "height_mm": 1189, "png_width": png_width},
        "title": TITLE, "subtitle": "Connect the question, workflow and evidence in one readable story.",
        "authors": "Poster Agent Demo Team", "affiliations": DEMO_NOTICE,
        "theme": {"accent": "#157B86", "secondary": "#D39439", "ink": "#183448", "background": "#FFFFFF", "font": "Arial"},
        "layout": {"style": "narrative", "columns": 2, "margin_mm": 24, "gap_mm": 10, "title_pt": 78, "body_pt": 27},
        "sections": [
            {"id": "question", "heading": "Make every visual claim traceable", "kind": "figure", "span": 2,
             "paragraphs": [PROBLEM], "image": assets["question.svg"], "image_height_mm": 150,
             "caption": "Original synthetic vector figure. Shared alignment connects the question, evidence and reviewer decision.", "source_refs": ["question", "question-figure"]},
            {"id": "workflow", "heading": "Keep evidence beside each claim", "kind": "figure", "span": 2,
             "paragraphs": [METHOD], "image": assets["workflow.svg"], "image_height_mm": 200,
             "caption": "The original workflow preserves source detail. A saved comment remains pending until a revision is applied and inspected.", "source_refs": ["workflow", "workflow-figure"]},
            {"id": "results", "heading": "Inspect the evidence and its limits", "kind": "figure", "span": 1,
             "image": assets["illustrative-results.svg"], "image_height_mm": 250,
             "caption": "SYNTHETIC DATA. All values are invented for software verification. No participants were recruited and no experiment was conducted.", "source_refs": ["protocol", "results-figure"]},
            {"id": "protocol", "heading": "", "hide_heading": True, "kind": "table", "span": 1,
             "tables": [{"title": "Illustrative protocol - synthetic values", "rows": [["Layout", "Tasks", "Minutes", "Traceable"], ["Disconnected", "12", "14.0", "65%"], ["Evidence-linked", "12", "9.5", "87%"], ["Local revision", "12", "6.0", "100%"]],
                         "caption": "SYNTHETIC DATA: hypothetical values, not empirical performance. Traceable means an illustrative claim has an explicit source link.", "highlight_rows": [3]}],
             "paragraphs": ["Each layout uses twelve invented review tasks. The table and chart share the same exact values; their evidence records point to page 2 of the synthetic source.", "The values cannot support a scientific performance claim. This fixture tests presentation and software behavior; it does not assess research correctness or human preferences."], "source_refs": ["protocol", "limits"]},
            {"id": "delivery", "heading": "From evidence to a reviewable print package", "kind": "callout", "span": 2,
             "paragraphs": ["Technical checks make the file reviewable. The reviewer still inspects source fidelity, visual hierarchy, density and readability, then selects Approve for the exact version. A demo remains a demonstration after approval."],
             "rows": [["Output", "Configured check", "Review responsibility"], ["Print PDF", "841 x 1189 mm; one page; embedded fonts", "Check full figures, labels and actual print scale"], ["Editable HTML", "Original vectors; stable section identifiers", "Compare content and design with the source"], ["High-resolution PNG", "6000 x 8483 pixels; independent PDF preview", "Judge clarity, hierarchy and information density"], ["Evidence + history", "Source links; local revisions; exact-version approval", "Request a focused change or approve the result"]],
             "caption": "Original synthetic fixture. No real conference rules, institutional logos, research results or unpublished paper assets are included.", "source_refs": ["limits", "workflow"]},
        ],
        "footer": "DEMO / SYNTHETIC DATA | Local A0 configuration | Original material distributed with this repository",
        "locked_regions": [], "approval": None,
    }
    write_json(project / "poster.json", spec)
    write_json(project / "conference.json", {"identity": identity, "is_demo": True, "checked_at": None, "sources": [],
                                             "requirements": {"width_mm": 841, "height_mm": 1189, "orientation": "portrait", "min_ppi": None},
                                             "unresolved": [], "warnings": ["Explicit local demonstration configuration; not real conference requirements."]})
    evidence = read_json(project / "evidence.json")
    evidence["is_demo"] = True
    evidence["items"] = [{"id": "question", "page": 1, "quote": PROBLEM}, {"id": "workflow", "page": 1, "quote": METHOD},
                         {"id": "protocol", "page": 2, "quote": PROTOCOL}, {"id": "limits", "page": 2, "quote": LIMITS},
                         *[{"id": key, "source_asset": assets[name], "note": "Original synthetic illustration, not a scientific result."} for key, name in
                           (("question-figure", "question.svg"), ("workflow-figure", "workflow.svg"), ("results-figure", "illustrative-results.svg"))]]
    evidence["content_review"] = {"status": "accepted", "content_sha256": content_digest(spec), "issues": [],
                                   "note": "Deterministic synthetic fixture checked against its supplied original text and values; human visual approval is pending."}
    write_json(project / "evidence.json", evidence)
    write_json(project / "reference/demo-note.json", {"is_demo": True, "notice": DEMO_NOTICE,
                                                      "reference_generation": "No ImageGen call: this explicit offline demo tests import, rendering and review. Production pipeline generates and compares an ImageGen reference."})
    return {"project": str(project), "status": "synthetic_demo_created", "quality": export_project(project, png_width=png_width)}
