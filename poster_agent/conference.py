"""Evidence-backed conference rules and explicitly selected printing services."""
from __future__ import annotations

import copy
import ipaddress
import re
import socket
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .project import read_json, timestamp, write_json


RULE_FIELDS = {"width_mm", "height_mm", "orientation", "dimension_policy", "format", "file_name",
               "min_ppi", "max_file_size_mb", "bleed_mm", "pdf_standard", "color_profile",
               "deadline_date", "deadline_time", "deadline_timezone"}


def applicable_requirements(conference, printing_service=False):
    rules = copy.deepcopy(conference.get("requirements", {}))
    service = conference.get("printing_service", {})
    indices = conference.get("requirement_sources", {}).get("file_name", [])
    sources = conference.get("sources", [])
    mandatory_filename = bool(indices) and isinstance(indices, list) and all(
        isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(sources)
        and sources[i].get("category") == "mandatory_poster" for i in indices
    )
    if service and not printing_service and not mandatory_filename:
        # Older profiles kept the optional service filename beside the poster size.
        rules.pop("file_name", None)
    if printing_service:
        if not service:
            raise ValueError("No verified printing-service profile is configured")
        service_rules = service.get("requirements", {})
        rules.update({key: value for key, value in service_rules.items()
                      if key in RULE_FIELDS and value is not None})
        rules.update({key: value for key, value in service.items()
                      if key in RULE_FIELDS and value is not None})
        if service.get("template"):
            rules["file_name"] = service["template"]
    return rules


def _domain(value):
    if not isinstance(value, str):
        raise ValueError("Official domains must be hostname strings")
    host = value.strip().lower().rstrip(".")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or "." not in host:
        raise ValueError("Use the official public website hostname, without URL paths")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise ValueError("An IP address is not an official conference website")


def _validate_url(url, domains):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if (parts.scheme != "https" or parts.username or parts.password or
            parts.port not in (None, 443) or len(url) > 2048):
        raise ValueError("Conference sources require public HTTPS URLs without credentials")
    if not any(host == domain or host.endswith("." + domain) for domain in domains):
        raise ValueError("Source is outside the stated official conference domains")
    return host


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks = []
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignore += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.ignore = max(0, self.ignore - 1)

    def handle_data(self, data):
        if not self.ignore:
            self.chunks.append(data)


def _normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


class _OfficialRedirect(HTTPRedirectHandler):
    def __init__(self, domains):
        super().__init__()
        self.domains = domains

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = _validate_url(newurl, self.domains)
        _public_address(host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _public_address(host):
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Conference source resolves to a non-public network address")


def fetch_source(url, domains):
    host = _validate_url(url, domains)
    _public_address(host)
    request = Request(url, headers={"User-Agent": "PaperPosterAgent/0.1 (conference-rules verification)"})
    with build_opener(_OfficialRedirect(domains)).open(request, timeout=15) as response:
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("Official specification exceeds the 2 MiB source limit; supply a focused official notice")
        if data.startswith(b"%PDF"):
            import fitz
            with fitz.open(stream=data, filetype="pdf") as pdf:
                return "\n".join(page.get_text() for page in pdf)
        reader = _Text()
        reader.feed(data.decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
        return " ".join(reader.chunks)


def _profile_shape(profile, identity):
    if not isinstance(profile, dict):
        raise ValueError("Conference profile must be a JSON object")
    if profile.get("identity") != identity:
        raise ValueError("Conference name, year and track must match this project")
    rules = profile.get("requirements", {})
    if not isinstance(rules, dict) or not isinstance(profile.get("requirement_sources", {}), dict):
        raise ValueError("Requirements and their source mapping must be JSON objects")
    for key in ("width_mm", "height_mm"):
        value = rules.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 50 <= value <= 3000:
            raise ValueError("Confirmed physical width and height in millimetres are required")
    if rules.get("orientation") not in (None, "portrait", "landscape", "either"):
        raise ValueError("Orientation must be portrait, landscape, either or unstated")
    if rules.get("dimension_policy", "exact") not in ("exact", "maximum"):
        raise ValueError("Dimension policy must be exact or maximum")
    if not isinstance(profile.get("unresolved", []), list):
        raise ValueError("Unresolved requirements must be an explicit list")
    sources = profile.get("sources", [])
    if not isinstance(sources, list) or any(not isinstance(source, dict) for source in sources):
        raise ValueError("Sources must be a list of official excerpt records")
    service = profile.get("printing_service", {})
    if not isinstance(service, dict) or any(not isinstance(service.get(key, {}), dict) for key in ("requirements", "requirement_sources")):
        raise ValueError("Printing service and its rules/mapping must be JSON objects")


_PAPER_MM = {"A0": (841.0, 1189.0), "A1": (594.0, 841.0), "A2": (420.0, 594.0)}
_NUMBER = r"\d+(?:\.\d+)?"
_UNIT = r'(?:millimet(?:er|re)s?|mm|centimet(?:er|re)s?|cm|inches|inch|in|\")'


def _millimetres(number, unit):
    unit = unit.casefold()
    multiplier = 25.4 if unit in ('"', "in", "inch", "inches") else 10 if unit.startswith("cm") or unit.startswith("centimet") else 1
    return float(number) * multiplier


def _close_size(left, right):
    return all(abs(a - b) <= .1 for a, b in zip(left, right))


def _geometry_evidence(quote):
    """Read explicit paper sizes, width-by-height pairs and orientation conservatively."""
    quote = _normalized(quote)
    lower = quote.casefold()
    portrait = bool(re.search(r"\bportrait\b|\bvertical\s+(?:format|orientation|poster)\b", lower))
    landscape = bool(re.search(r"\blandscape\b|\bhorizontal\s+(?:format|orientation|poster)\b", lower))
    either = bool(re.search(r"\b(?:either|any|both)\s+(?:orientation|portrait|landscape)|(?:portrait\s*(?:or|and|/|&)\s*landscape)|(?:landscape\s*(?:or|and|/|&)\s*portrait)", lower))
    orientation = "either" if either else "portrait" if portrait and not landscape else "landscape" if landscape and not portrait else None
    ambiguous_orientation = portrait and landscape and not either
    papers = {_PAPER_MM[paper.upper()] for paper in re.findall(r"\bA[012]\b", quote, re.I)}
    pairs = []
    pattern = rf"(?<![\w.])({_NUMBER})\s*({_UNIT})?\s*(?:[x×*]|by)\s*({_NUMBER})\s*({_UNIT})?(?!\w)"
    for match in re.finditer(pattern, lower):
        first, first_unit, second, second_unit = match.groups()
        if not first_unit and not second_unit:
            continue
        pairs.append((_millimetres(first, first_unit or second_unit), _millimetres(second, second_unit or first_unit)))
    labelled = rf"\bwidth\s*[:=]?\s*({_NUMBER})\s*({_UNIT}).{{0,50}}?\bheight\s*[:=]?\s*({_NUMBER})\s*({_UNIT})"
    for match in re.finditer(labelled, lower):
        first, first_unit, second, second_unit = match.groups()
        pairs.append((_millimetres(first, first_unit), _millimetres(second, second_unit)))
    unique = []
    for pair in pairs:
        if not any(_close_size(pair, old) for old in unique):
            unique.append(pair)
    if len(papers) > 1:
        return [], orientation, "excerpt contains multiple paper sizes; applicability needs human interpretation"
    if len(unique) > 1 and not (orientation == "either" and all(_close_size(sorted(pair), sorted(unique[0])) for pair in unique)):
        return [], orientation, "excerpt contains multiple physical sizes; applicability needs human interpretation"
    if papers:
        short, long = next(iter(papers))
        paper_pairs = [(short, long)] if orientation == "portrait" else [(long, short)] if orientation == "landscape" else [(short, long), (long, short)]
        if unique and any(not any(_close_size(pair, paper) for paper in paper_pairs) for pair in unique):
            return [], orientation, "paper-size label, explicit dimensions and orientation conflict"
        unique = unique or paper_pairs
    if ambiguous_orientation:
        return [], None, "excerpt mentions both orientations without a clear allowed choice"
    if not unique:
        return [], orientation, "excerpt does not state a recognized paper size or explicit physical dimensions"
    return unique, orientation, None


def _source_metadata(source, identity, semantic_scope=True):
    if source.get("category") not in ("mandatory_poster", "optional_printing", "official_identity"):
        raise ValueError("Source category must distinguish poster rules from optional printing")
    if source.get("year") != identity["year"] or source.get("track") not in (identity["track"], "all_tracks"):
        raise ValueError("Source year or track does not apply to this project")
    if source.get("scope") is not None and source["scope"] not in (identity["track"], "all_tracks"):
        raise ValueError("Source scope must be the requested track or all_tracks")
    quote = source.get("quote", "")
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError("An exact official excerpt is required")
    quoted_years = set(re.findall(r"\b20\d{2}\b", quote))
    if quoted_years and str(identity["year"]) not in quoted_years:
        raise ValueError("Quoted notice identifies another conference year")
    if semantic_scope and source["category"] == "mandatory_poster" and re.search(r"(?:printing|print)\s+service|optional\s+(?:printing|service)", quote, re.I):
        raise ValueError("Printing-service excerpts cannot define mandatory poster rules")
    requested_track = identity["track"].casefold()
    restricted = re.findall(r"\b(main|workshop|doctoral|demo)\s+(?:track|papers?|posters?|participants?)\b", quote, re.I)
    if semantic_scope and restricted and not re.search(r"\ball\s+(?:tracks|posters|papers)\b", quote, re.I) and any(track.casefold() not in requested_track for track in restricted):
        raise ValueError("Quoted notice is restricted to another track")


def _mapped_sources(mapping, field, sources, category, verification):
    indices = mapping.get(field, [])
    if not isinstance(indices, list) or not indices or any(
        not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(sources) for i in indices
    ):
        return None
    if any(sources[i].get("category") != category or sources[i].get("verification") != verification for i in indices):
        return None
    return [sources[i] for i in indices]


def _verify_geometry(field, value, rules, mapped):
    parsed = [_geometry_evidence(source["quote"]) for source in mapped]
    if field in ("width_mm", "height_mm"):
        index = 0 if field == "width_mm" else 1
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or error or
               not any(abs(pair[index] - value) <= .1 for pair in pairs) for pairs, _, error in parsed):
            return "physical size cannot be deterministically matched to the cited excerpt; use rules --file after checking the official notice"
        requested_pair = (rules.get("width_mm"), rules.get("height_mm"))
        if all(isinstance(number, (int, float)) and not isinstance(number, bool) for number in requested_pair) and any(
            not any(_close_size(pair, requested_pair) for pair in pairs) for pairs, _, _ in parsed
        ):
            return "physical width-height pair does not match one allowed size; do not combine axes from different options"
        if rules.get("orientation") in ("portrait", "landscape"):
            width, height = rules.get("width_mm"), rules.get("height_mm")
            if isinstance(width, (int, float)) and isinstance(height, (int, float)) and (
                (rules["orientation"] == "portrait" and width >= height) or (rules["orientation"] == "landscape" and width <= height)
            ):
                return "physical dimensions contradict the stated orientation"
        if rules.get("dimension_policy", "exact") == "exact" and any(
            re.search(r"(?:maximum|\bmax\b|at most|up to|not exceed|no larger than).{0,50}(?:\bA[012]\b|\d+\s*(?:mm|cm|inch|in\b))", _normalized(source["quote"]), re.I)
            for source in mapped
        ):
            return "excerpt states a maximum size; record dimension_policy maximum or import a checked profile"
    elif field == "orientation":
        if value not in ("portrait", "landscape", "either") or any(orientation != value for _, orientation, _ in parsed):
            return "orientation does not match an explicit choice in the cited excerpt; use rules --file after checking"
    elif field == "dimension_policy":
        maximum = [bool(re.search(r"maximum|\bmax\b|at most|up to|not exceed|no larger than", _normalized(source["quote"]), re.I)) for source in mapped]
        if value not in ("exact", "maximum") or any(marked != (value == "maximum") for marked in maximum):
            return "dimension policy does not match the cited excerpt"
    return None


def _verify_rule_mapping(rules, mapping, sources, category, verification, semantic_geometry=True):
    unresolved = []
    for field, value in rules.items():
        if value is None or field not in RULE_FIELDS:
            continue
        mapped = _mapped_sources(mapping, field, sources, category, verification)
        if mapped is None:
            unresolved.append(f"{field}: map this rule to verified {category} source indices")
            continue
        problem = _verify_geometry(field, value, rules, mapped) if semantic_geometry else None
        if problem:
            unresolved.append(f"{field}: {problem}")
    return unresolved


def _service_fields(service):
    fields = {**service.get("requirements", {}), **{key: value for key, value in service.items() if key in RULE_FIELDS}}
    if service.get("template"):
        fields["file_name"] = service["template"]
    return fields


def validate_research(project, result):
    """Validate model research against fetched official text; never self-certify it."""
    project = Path(project)
    identity = read_json(project / "conference.json")["identity"]
    profile = copy.deepcopy(result)
    _profile_shape(profile, identity)
    domains = [_domain(host) for host in profile.get("official_domains", [])]
    sources = profile.get("sources", [])
    if not domains or not sources:
        raise ValueError("Official website domains and direct sources are required")
    unresolved = list(profile.get("unresolved", []))
    for source in sources:
        source["verified_at"] = timestamp()
        try:
            _validate_url(source.get("url", ""), domains)
            _source_metadata(source, identity)
            quote = source["quote"]
            text = fetch_source(source["url"], domains)
            if _normalized(quote) not in _normalized(text):
                raise ValueError("Quoted requirement was not found in the actual official page")
            stated_years = set(re.findall(r"\b20\d{2}\b", text))
            if stated_years and str(identity["year"]) not in stated_years:
                raise ValueError("The retrieved document identifies another year")
            if str(identity["year"]) not in text + source["url"]:
                raise ValueError("The retrieved document does not identify the requested year")
            source["verification"] = "fetched_quote_matched"
        except Exception as error:
            # Source URLs and public rule errors carry no account credentials.
            source["verification"] = "unconfirmed"
            source["verification_error"] = str(error)

    mapping = profile.get("requirement_sources", {})
    unresolved.extend(_verify_rule_mapping(profile["requirements"], mapping, sources, "mandatory_poster", "fetched_quote_matched"))
    service = profile.get("printing_service", {})
    if service:
        service_unresolved = list(service.get("unresolved_rules", []))
        service_mapping = service.get("requirement_sources", {})
        service_unresolved.extend(_verify_rule_mapping(_service_fields(service), service_mapping, sources, "optional_printing", "fetched_quote_matched"))
        service["unresolved_rules"] = list(dict.fromkeys(service_unresolved))
        service["unresolved"] = list(dict.fromkeys([*service.get("unresolved", []), *service_unresolved]))
    profile.update(checked_at=timestamp(), unresolved=list(dict.fromkeys(unresolved)))
    profile["review_note"] = "Official excerpts and physical size/orientation were checked against retrieved pages. Ambiguous rules need explicit rules --file import after human verification. Check official website identity and any track-specific notices before submission."
    write_json(project / "conference.json", profile)
    if profile["unresolved"]:
        raise ValueError("Conference rules are unconfirmed; inspect conference.json or explicitly import a checked official profile with poster-agent rules")
    return profile


def import_profile(project, file):
    """Explicit local import after a person/session has checked the official notice."""
    project = Path(project)
    profile = read_json(file)
    identity = read_json(project / "conference.json")["identity"]
    _profile_shape(profile, identity)
    if profile.get("is_demo") or profile.get("unresolved") or not profile.get("sources"):
        raise ValueError("Import a complete, checked official conference profile with source links and excerpts")
    domains = profile.get("official_domains") or sorted({urlsplit(s.get("url", "")).hostname or "" for s in profile["sources"]})
    domains = [_domain(host) for host in domains]
    for source in profile["sources"]:
        _validate_url(source.get("url", ""), domains)
        _source_metadata(source, identity, semantic_scope=False)
        source.update(verification="explicitly_imported_checked_profile", verified_at=timestamp())
    unresolved = _verify_rule_mapping(profile["requirements"], profile.get("requirement_sources", {}), profile["sources"], "mandatory_poster", "explicitly_imported_checked_profile", semantic_geometry=False)
    if unresolved:
        raise ValueError("Imported rules require applicable mandatory source mappings: " + "; ".join(unresolved))
    service = profile.get("printing_service", {})
    if service:
        service_unresolved = _verify_rule_mapping(_service_fields(service), service.get("requirement_sources", {}), profile["sources"], "optional_printing", "explicitly_imported_checked_profile", semantic_geometry=False)
        service["unresolved_rules"] = list(dict.fromkeys([*service.get("unresolved_rules", []), *service_unresolved]))
        service["unresolved"] = list(dict.fromkeys([*service.get("unresolved", []), *service_unresolved]))
    profile.update(official_domains=domains, imported_at=timestamp(),
                   verification_mode="explicit_local_profile_import")
    write_json(project / "conference.json", profile)
    return profile
