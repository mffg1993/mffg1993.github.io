#!/usr/bin/env python3
"""
Merge three publication sources for the Jekyll website:

1. Reliable automatic metadata:
       _data/publications_regular.json
   generated from Crossref/OpenAlex.

2. Last successful Google Scholar cache:
       _data/publications_scholar.json

3. User-verified BibTeX:
       _data/publications_verified.bib

Outputs:
       _data/publications.json
       _data/publications_audit.json

Source priority for bibliographic metadata:
       Verified BibTeX > Crossref/OpenAlex > Google Scholar

Citation counts and source-specific identifiers are preserved independently.

Duplicate matching:
       1. normalized DOI;
       2. normalized title and year;
       3. exact normalized title.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REGULAR_PATH = Path("_data/publications_regular.json")
SCHOLAR_PATH = Path("_data/publications_scholar.json")
BIBTEX_PATH = Path("_data/publications_verified.bib")
FINAL_PATH = Path("_data/publications.json")
AUDIT_PATH = Path("_data/publications_audit.json")

ORCID_ID = "0000-0003-1358-2049"
SCHOLAR_ID = "FzMu3LkAAAAJ"


def normalize_doi(value: str | None) -> str:
    if not value:
        return ""
    doi = str(value).strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    return doi.rstrip(".,;").strip().casefold()


def normalize_title(value: str | None) -> str:
    value = str(value or "")
    value = latex_to_unicode(value)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        character
        for character in value
        if not unicodedata.combining(character)
    )
    value = value.casefold()
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def normalize_year(value: Any) -> str:
    match = re.search(r"\b(19|20)\d{2}\b", str(value or ""))
    return match.group(0) if match else ""


def first_nonempty(values: list[Any], default: Any = None) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return default


def load_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def comparable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key != "generated_at"
    }


def write_payload_if_changed(path: Path, payload: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    old_payload = load_payload(path)

    if old_payload and comparable_payload(old_payload) == comparable_payload(payload):
        print(f"{path} has no metadata changes.")
        return False

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if isinstance(payload.get("works"), list):
        print(f"Wrote {path} with {len(payload['works'])} works.")
    else:
        print(f"Wrote {path}.")
    return True


# ---------------------------------------------------------------------------
# BibTeX parsing
# ---------------------------------------------------------------------------

_LATEX_REPLACEMENTS = {
    r"{\'a}": "á",
    r"{\'e}": "é",
    r"{\'i}": "í",
    r"{\'o}": "ó",
    r"{\'u}": "ú",
    r"{\'A}": "Á",
    r"{\'E}": "É",
    r"{\'I}": "Í",
    r"{\'O}": "Ó",
    r"{\'U}": "Ú",
    r"{\`a}": "à",
    r"{\`e}": "è",
    r"{\`i}": "ì",
    r"{\`o}": "ò",
    r"{\`u}": "ù",
    r"{\"a}": "ä",
    r"{\"e}": "ë",
    r"{\"i}": "ï",
    r"{\"o}": "ö",
    r"{\"u}": "ü",
    r"{\~n}": "ñ",
    r"{\c c}": "ç",
    r"\&": "&",
    r"\%": "%",
    r"\_": "_",
}


def latex_to_unicode(value: str) -> str:
    text = str(value or "")
    for source, replacement in _LATEX_REPLACEMENTS.items():
        text = text.replace(source, replacement)

    # Also support compact accent forms such as {\'o}.
    accent_patterns = [
        (r"\{\\'([aeiouAEIOU])\}", {
            "a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú",
            "A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú",
        }),
        (r"\{\\~([nN])\}", {"n": "ñ", "N": "Ñ"}),
    ]
    for pattern, table in accent_patterns:
        text = re.sub(
            pattern,
            lambda match: table.get(match.group(1), match.group(1)),
            text,
        )

    # Braces used only for BibTeX capitalization/grouping should not be shown.
    text = text.replace("{", "").replace("}", "")
    return " ".join(text.split())


def find_matching_brace(text: str, opening_index: int) -> int:
    opening = text[opening_index]
    closing = "}" if opening == "{" else ")"
    depth = 0
    in_quote = False
    escaped = False

    for index in range(opening_index, len(text)):
        character = text[index]

        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            continue

        if character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index

    raise ValueError(f"Unclosed BibTeX entry beginning at character {opening_index}.")


def split_top_level(text: str, delimiter: str = ",") -> list[str]:
    parts: list[str] = []
    start = 0
    brace_depth = 0
    parenthesis_depth = 0
    in_quote = False
    escaped = False

    for index, character in enumerate(text):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            continue

        if character == "{":
            brace_depth += 1
        elif character == "}":
            brace_depth = max(0, brace_depth - 1)
        elif character == "(":
            parenthesis_depth += 1
        elif character == ")":
            parenthesis_depth = max(0, parenthesis_depth - 1)
        elif (
            character == delimiter
            and brace_depth == 0
            and parenthesis_depth == 0
        ):
            parts.append(text[start:index].strip())
            start = index + 1

    final = text[start:].strip()
    if final:
        parts.append(final)
    return parts


def unwrap_bibtex_value(value: str) -> str:
    value = value.strip()
    while len(value) >= 2:
        if value[0] == "{" and value[-1] == "}":
            try:
                if find_matching_brace(value, 0) == len(value) - 1:
                    value = value[1:-1].strip()
                    continue
            except ValueError:
                pass
        if value[0] == '"' and value[-1] == '"':
            value = value[1:-1].strip()
            continue
        break
    return latex_to_unicode(value)


def parse_bibtex(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []

    text = path.read_text(encoding="utf-8")
    entries: list[dict[str, str]] = []
    warnings: list[str] = []
    position = 0

    while True:
        match = re.search(r"@([A-Za-z]+)\s*([\{\(])", text[position:])
        if not match:
            break

        entry_type = match.group(1).casefold()
        opening_index = position + match.end() - 1

        try:
            closing_index = find_matching_brace(text, opening_index)
        except ValueError as exc:
            warnings.append(str(exc))
            break

        body = text[opening_index + 1:closing_index].strip()
        position = closing_index + 1

        parts = split_top_level(body)
        if not parts:
            warnings.append(f"Empty @{entry_type} entry was ignored.")
            continue

        citation_key = parts[0].strip()
        fields: dict[str, str] = {
            "ENTRYTYPE": entry_type,
            "ID": citation_key,
        }

        for field_text in parts[1:]:
            if not field_text or "=" not in field_text:
                continue
            field_name, raw_value = field_text.split("=", 1)
            fields[field_name.strip().casefold()] = unwrap_bibtex_value(raw_value)

        if not fields.get("title"):
            warnings.append(f"{citation_key}: entry has no title and was ignored.")
            continue

        entries.append(fields)

    return entries, warnings


def split_bibtex_authors(value: str) -> list[str]:
    parts = re.split(r"\s+and\s+", value.strip(), flags=re.I)
    return [part.strip() for part in parts if part.strip()]


def display_author_name(value: str) -> str:
    value = latex_to_unicode(value)
    if "," not in value:
        return value

    family, given = [part.strip() for part in value.split(",", 1)]
    return " ".join(part for part in (given, family) if part)


def author_is_me(name: str) -> bool:
    normalized = re.sub(r"[^a-z]", "", normalize_title(name))
    return "ferrer" in normalized and (
        "manuel" in normalized
        or normalized.startswith("mf")
        or "manuel" in name.casefold()
    )


def bibtex_entry_to_work(entry: dict[str, str]) -> dict[str, Any]:
    year_text = normalize_year(entry.get("year"))
    year: int | str = int(year_text) if year_text else "Undated"

    authors = []
    for raw_author in split_bibtex_authors(entry.get("author", "")):
        name = display_author_name(raw_author)
        is_me = author_is_me(name)
        authors.append(
            {
                "name": name,
                "orcid": ORCID_ID if is_me else None,
                "is_me": is_me,
            }
        )

    doi = normalize_doi(entry.get("doi"))
    url = entry.get("url") or ""
    journal = entry.get("journal") or entry.get("booktitle") or ""
    eprint = entry.get("eprint") or ""

    if not url and doi:
        url = f"https://doi.org/{doi}"
    if not url:
        arxiv_match = re.search(
            r"arXiv[:\s]+(\d{4}\.\d{4,5})",
            journal,
            flags=re.I,
        )
        if not arxiv_match and eprint:
            arxiv_match = re.search(r"(\d{4}\.\d{4,5})", eprint)
        if arxiv_match:
            url = f"https://arxiv.org/abs/{arxiv_match.group(1)}"

    entry_type = entry.get("ENTRYTYPE", "article")
    pages = (entry.get("pages") or "").replace("--", "–")

    return {
        "title": entry.get("title", ""),
        "authors": authors,
        "venue": journal,
        "year": year,
        "publication_date": (
            f"{year_text}-01-01" if year_text else ""
        ),
        "type": entry_type,
        "doi": doi or None,
        "url": url or None,
        "open_access_url": entry.get("eprint_url") or None,
        "volume": entry.get("volume") or None,
        "issue": entry.get("number") or entry.get("issue") or None,
        "pages": pages or None,
        "publisher": entry.get("publisher") or None,
        "data_source": "Verified BibTeX",
        "data_sources": ["Verified BibTeX"],
        "bibtex_key": entry.get("ID"),
        "verified": True,
    }


# ---------------------------------------------------------------------------
# Record matching and merging
# ---------------------------------------------------------------------------

def source_names(work: dict[str, Any]) -> list[str]:
    result: list[str] = []
    raw_sources = work.get("data_sources")
    if isinstance(raw_sources, list):
        result.extend(str(value) for value in raw_sources if value)

    single_source = work.get("data_source")
    if single_source:
        result.append(str(single_source))

    return list(dict.fromkeys(result))


def add_source_names(work: dict[str, Any], additions: list[str]) -> None:
    work["data_sources"] = list(
        dict.fromkeys(source_names(work) + [source for source in additions if source])
    )


def is_supplementary_only(work: dict[str, Any]) -> bool:
    sources = set(source_names(work))
    return bool(sources) and sources.issubset(
        {"Google Scholar", "Verified BibTeX"}
    )


def regular_payload_with_fallback() -> dict[str, Any]:
    regular = load_payload(REGULAR_PATH)
    if regular.get("works") is not None:
        return regular

    current = load_payload(FINAL_PATH)
    if not current:
        return {"sources": [], "works": []}

    fallback_works = [
        work
        for work in current.get("works", [])
        if isinstance(work, dict) and not is_supplementary_only(work)
    ]
    fallback_sources = [
        source
        for source in current.get("sources", [])
        if source not in {"Google Scholar", "Verified BibTeX"}
    ]

    print(
        "publications_regular.json is not present; using regular-source "
        "records from the current publications.json as a fallback."
    )
    return {
        **current,
        "sources": fallback_sources,
        "works": fallback_works,
    }


def merge_duplicate(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    combined = dict(existing)
    for field, value in incoming.items():
        if value not in (None, "", [], {}):
            combined[field] = value
    add_source_names(combined, source_names(existing) + source_names(incoming))
    return combined


def merge_scholar_duplicate(
    regular: dict[str, Any],
    scholar: dict[str, Any],
) -> dict[str, Any]:
    combined = dict(regular)

    for field in (
        "authors",
        "venue",
        "year",
        "publication_date",
        "type",
        "doi",
        "url",
        "open_access_url",
        "volume",
        "issue",
        "pages",
    ):
        if combined.get(field) in (None, "", [], {}):
            value = scholar.get(field)
            if value not in (None, "", [], {}):
                combined[field] = value

    if scholar.get("scholar_id"):
        combined["scholar_id"] = scholar["scholar_id"]
    if scholar.get("scholar_url"):
        combined["scholar_url"] = scholar["scholar_url"]

    scholar_citations = scholar.get("scholar_citations")
    if scholar_citations is None:
        scholar_citations = scholar.get("cited_by_count")
    if scholar_citations is not None:
        combined["scholar_citations"] = scholar_citations

    add_source_names(combined, source_names(regular) + ["Google Scholar"])
    return combined


def merge_bibtex_duplicate(
    existing: dict[str, Any],
    verified: dict[str, Any],
) -> dict[str, Any]:
    """
    BibTeX is user-verified and therefore authoritative for stable
    bibliographic fields. It never removes citation counts or source IDs.
    """
    combined = dict(existing)

    for field in (
        "title",
        "authors",
        "venue",
        "year",
        "publication_date",
        "type",
        "doi",
        "url",
        "volume",
        "issue",
        "pages",
        "publisher",
        "bibtex_key",
        "verified",
    ):
        value = verified.get(field)
        if value not in (None, "", [], {}):
            combined[field] = value

    # BibTeX may contain an OA link, but an existing OA link should survive
    # when the BibTeX record does not specify one.
    if verified.get("open_access_url"):
        combined["open_access_url"] = verified["open_access_url"]

    add_source_names(combined, source_names(existing) + ["Verified BibTeX"])
    return combined


def find_match_index(
    work: dict[str, Any],
    doi_index: dict[str, int],
    title_year_index: dict[tuple[str, str], int],
    title_index: dict[str, int],
) -> int | None:
    doi = normalize_doi(work.get("doi"))
    if doi and doi in doi_index:
        return doi_index[doi]

    title = normalize_title(work.get("title"))
    year = normalize_year(work.get("year"))

    if title and year and (title, year) in title_year_index:
        return title_year_index[(title, year)]

    if title and title in title_index:
        return title_index[title]

    return None


def index_work(
    work: dict[str, Any],
    index: int,
    doi_index: dict[str, int],
    title_year_index: dict[tuple[str, str], int],
    title_index: dict[str, int],
) -> None:
    doi = normalize_doi(work.get("doi"))
    title = normalize_title(work.get("title"))
    year = normalize_year(work.get("year"))

    if doi:
        doi_index[doi] = index
    if title and year:
        title_year_index[(title, year)] = index
    if title:
        title_index[title] = index


def deduplicate_works(works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []
    doi_index: dict[str, int] = {}
    title_year_index: dict[tuple[str, str], int] = {}
    title_index: dict[str, int] = {}

    for original in works:
        if not isinstance(original, dict):
            continue
        if not normalize_title(original.get("title")):
            continue

        work = dict(original)
        add_source_names(work, source_names(work))
        match = find_match_index(
            work, doi_index, title_year_index, title_index
        )

        if match is None:
            deduplicated.append(work)
            index_work(
                work,
                len(deduplicated) - 1,
                doi_index,
                title_year_index,
                title_index,
            )
        else:
            combined = merge_duplicate(deduplicated[match], work)
            deduplicated[match] = combined
            index_work(
                combined,
                match,
                doi_index,
                title_year_index,
                title_index,
            )

    return deduplicated


def merge_all_sources(
    regular_works: list[dict[str, Any]],
    scholar_works: list[dict[str, Any]],
    bibtex_works: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    merged = deduplicate_works(regular_works)

    doi_index: dict[str, int] = {}
    title_year_index: dict[tuple[str, str], int] = {}
    title_index: dict[str, int] = {}

    for index, work in enumerate(merged):
        index_work(
            work, index, doi_index, title_year_index, title_index
        )

    scholar_only_titles: list[str] = []
    scholar_matched_titles: list[str] = []

    for original in deduplicate_works(scholar_works):
        work = dict(original)
        match = find_match_index(
            work, doi_index, title_year_index, title_index
        )

        if match is None:
            add_source_names(work, ["Google Scholar"])
            work["data_source"] = "Google Scholar"
            if work.get("scholar_citations") is not None:
                work["cited_by_count"] = work["scholar_citations"]
                work["citation_source"] = "Google Scholar"
            merged.append(work)
            index_work(
                work,
                len(merged) - 1,
                doi_index,
                title_year_index,
                title_index,
            )
            scholar_only_titles.append(str(work.get("title") or ""))
        else:
            combined = merge_scholar_duplicate(merged[match], work)
            merged[match] = combined
            index_work(
                combined,
                match,
                doi_index,
                title_year_index,
                title_index,
            )
            scholar_matched_titles.append(str(combined.get("title") or ""))

    bibtex_added_titles: list[str] = []
    bibtex_matched_titles: list[str] = []

    for original in deduplicate_works(bibtex_works):
        work = dict(original)
        match = find_match_index(
            work, doi_index, title_year_index, title_index
        )

        if match is None:
            add_source_names(work, ["Verified BibTeX"])
            work["data_source"] = "Verified BibTeX"
            merged.append(work)
            index_work(
                work,
                len(merged) - 1,
                doi_index,
                title_year_index,
                title_index,
            )
            bibtex_added_titles.append(str(work.get("title") or ""))
        else:
            combined = merge_bibtex_duplicate(merged[match], work)
            merged[match] = combined
            index_work(
                combined,
                match,
                doi_index,
                title_year_index,
                title_index,
            )
            bibtex_matched_titles.append(str(combined.get("title") or ""))

    for work in merged:
        if not work.get("year"):
            work["year"] = "Undated"

    def sort_key(work: dict[str, Any]) -> tuple[int, str, str]:
        year = normalize_year(work.get("year"))
        numeric_year = int(year) if year else 0
        return (
            numeric_year,
            str(work.get("publication_date") or ""),
            normalize_title(work.get("title")),
        )

    merged.sort(key=sort_key, reverse=True)

    audit = {
        "regular_records": len(regular_works),
        "scholar_records": len(scholar_works),
        "bibtex_records": len(bibtex_works),
        "scholar_matched": len(scholar_matched_titles),
        "scholar_added": len(scholar_only_titles),
        "bibtex_matched": len(bibtex_matched_titles),
        "bibtex_added": len(bibtex_added_titles),
        "final_publications": len(merged),
        "scholar_added_titles": scholar_only_titles,
        "bibtex_added_titles": bibtex_added_titles,
        "bibtex_matched_titles": bibtex_matched_titles,
    }

    print(
        f"Final merge: {len(regular_works)} regular, "
        f"{len(scholar_works)} Scholar, "
        f"{len(bibtex_works)} BibTeX; "
        f"{len(bibtex_added_titles)} BibTeX additions; "
        f"{len(merged)} final publications."
    )

    return merged, audit


def build_outputs() -> tuple[dict[str, Any], dict[str, Any]]:
    regular = regular_payload_with_fallback()
    scholar = load_payload(SCHOLAR_PATH)
    bib_entries, bib_warnings = parse_bibtex(BIBTEX_PATH)
    bibtex_works = [bibtex_entry_to_work(entry) for entry in bib_entries]

    regular_works = [
        work
        for work in regular.get("works", [])
        if isinstance(work, dict)
    ]
    scholar_works = [
        work
        for work in scholar.get("works", [])
        if isinstance(work, dict)
    ]

    works, audit = merge_all_sources(
        regular_works,
        scholar_works,
        bibtex_works,
    )

    sources = list(
        dict.fromkeys(
            [
                *regular.get("sources", []),
                *(scholar.get("sources", []) if scholar_works else []),
                *(["Verified BibTeX"] if bibtex_works else []),
            ]
        )
    )

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    payload = {
        "generated_at": timestamp,
        "orcid": regular.get("orcid", ORCID_ID),
        "orcid_url": regular.get(
            "orcid_url",
            f"https://orcid.org/{ORCID_ID}",
        ),
        "scholar_id": scholar.get("scholar_id", SCHOLAR_ID),
        "scholar_url": scholar.get(
            "scholar_url",
            f"https://scholar.google.com/citations?user={SCHOLAR_ID}&hl=en",
        ),
        "author_name": first_nonempty(
            [
                regular.get("author_name"),
                scholar.get("author_name"),
                "Manuel F. Ferrer-Garcia",
            ]
        ),
        "openalex_author_id": regular.get("openalex_author_id"),
        "sources": sources,
        "regular_generated_at": regular.get("generated_at"),
        "scholar_generated_at": scholar.get("generated_at"),
        "bibtex_file": str(BIBTEX_PATH),
        "works": works,
    }

    audit_payload = {
        "generated_at": timestamp,
        **audit,
        "bibtex_warnings": bib_warnings,
    }

    return payload, audit_payload


def main() -> int:
    payload, audit = build_outputs()
    write_payload_if_changed(FINAL_PATH, payload)
    write_payload_if_changed(AUDIT_PATH, audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
