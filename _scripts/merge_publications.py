#!/usr/bin/env python3
"""
Merge the reliable Crossref/OpenAlex publication cache with the most recent
successful Google Scholar cache.

Input files:
    _data/publications_regular.json
    _data/publications_scholar.json

Output file:
    _data/publications.json

The regular database remains authoritative. Google Scholar:
    * adds publications missing from the regular database;
    * fills empty fields on matching records;
    * stores Scholar identifiers and citation counts separately;
    * never replaces reliable metadata with an empty or weaker value.

Duplicate detection uses:
    1. normalized DOI;
    2. normalized title and publication year;
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
FINAL_PATH = Path("_data/publications.json")


def normalize_doi(value: str | None) -> str:
    if not value:
        return ""
    doi = str(value).strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    return doi.rstrip(".,;").strip().casefold()


def normalize_title(value: str | None) -> str:
    value = str(value or "")
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
    text = str(value or "").strip()
    match = re.search(r"\b(19|20)\d{2}\b", text)
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
    print(f"Wrote {path} with {len(payload.get('works', []))} works.")
    return True


def source_names(work: dict[str, Any]) -> list[str]:
    result: list[str] = []

    raw_sources = work.get("data_sources")
    if isinstance(raw_sources, list):
        result.extend(str(value) for value in raw_sources if value)

    single_source = work.get("data_source")
    if single_source:
        result.append(str(single_source))

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(result))


def add_source_names(work: dict[str, Any], additions: list[str]) -> None:
    work["data_sources"] = list(
        dict.fromkeys(source_names(work) + [source for source in additions if source])
    )


def is_scholar_only(work: dict[str, Any]) -> bool:
    sources = set(source_names(work))
    return bool(sources) and sources.issubset({"Google Scholar"})


def regular_payload_with_fallback() -> dict[str, Any]:
    """
    During the first installation, publications_regular.json does not yet exist.
    Use the current final database as a one-time fallback, excluding any records
    that are clearly Scholar-only.
    """
    regular = load_payload(REGULAR_PATH)
    if regular.get("works") is not None:
        return regular

    current = load_payload(FINAL_PATH)
    if not current:
        return {"sources": [], "works": []}

    fallback_works = [
        work
        for work in current.get("works", [])
        if isinstance(work, dict) and not is_scholar_only(work)
    ]

    fallback_sources = [
        source
        for source in current.get("sources", [])
        if source != "Google Scholar"
    ]

    print(
        "publications_regular.json is not present yet; using the current "
        "publications.json as the regular-source fallback."
    )

    return {
        **current,
        "sources": fallback_sources,
        "works": fallback_works,
    }


def merge_regular_duplicate(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """
    Merge duplicate records inside a source list.

    Incoming non-empty metadata is allowed to enrich the existing record.
    """
    combined = dict(existing)

    for field, value in incoming.items():
        if value not in (None, "", [], {}):
            combined[field] = value

    add_source_names(
        combined,
        source_names(existing) + source_names(incoming),
    )
    return combined


def merge_scholar_duplicate(
    regular: dict[str, Any],
    scholar: dict[str, Any],
) -> dict[str, Any]:
    """
    Keep regular metadata as authoritative and use Scholar as supplementary
    metadata only.
    """
    combined = dict(regular)

    fields_that_scholar_may_fill = (
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
    )

    for field in fields_that_scholar_may_fill:
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

    add_source_names(
        combined,
        source_names(regular) + ["Google Scholar"],
    )
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
            work,
            doi_index,
            title_year_index,
            title_index,
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
            continue

        combined = merge_regular_duplicate(deduplicated[match], work)
        deduplicated[match] = combined

        # Rebuild indexes for this record in case the incoming copy added a DOI.
        index_work(
            combined,
            match,
            doi_index,
            title_year_index,
            title_index,
        )

    return deduplicated


def merge_regular_and_scholar(
    regular_works: list[dict[str, Any]],
    scholar_works: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = deduplicate_works(regular_works)

    doi_index: dict[str, int] = {}
    title_year_index: dict[tuple[str, str], int] = {}
    title_index: dict[str, int] = {}

    for index, work in enumerate(merged):
        index_work(
            work,
            index,
            doi_index,
            title_year_index,
            title_index,
        )

    scholar_only_count = 0
    duplicate_count = 0

    for original in deduplicate_works(scholar_works):
        work = dict(original)
        match = find_match_index(
            work,
            doi_index,
            title_year_index,
            title_index,
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
            scholar_only_count += 1
            continue

        combined = merge_scholar_duplicate(merged[match], work)
        merged[match] = combined
        index_work(
            combined,
            match,
            doi_index,
            title_year_index,
            title_index,
        )
        duplicate_count += 1

    def sort_key(work: dict[str, Any]) -> tuple[int, str, str]:
        year = normalize_year(work.get("year"))
        numeric_year = int(year) if year else 0
        return (
            numeric_year,
            str(work.get("publication_date") or ""),
            normalize_title(work.get("title")),
        )

    for work in merged:
        if not work.get("year"):
            work["year"] = "Undated"

    merged.sort(key=sort_key, reverse=True)

    print(
        f"Final merge: {len(regular_works)} regular records, "
        f"{len(scholar_works)} Scholar records, "
        f"{duplicate_count} cross-source duplicates, "
        f"{scholar_only_count} Scholar-only additions, "
        f"{len(merged)} final publications."
    )

    return merged


def build_final_payload() -> dict[str, Any]:
    regular = regular_payload_with_fallback()
    scholar = load_payload(SCHOLAR_PATH)

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

    works = merge_regular_and_scholar(regular_works, scholar_works)

    sources = list(
        dict.fromkeys(
            [
                *regular.get("sources", []),
                *(scholar.get("sources", []) if scholar_works else []),
            ]
        )
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "orcid": regular.get("orcid", "0000-0003-1358-2049"),
        "orcid_url": regular.get(
            "orcid_url",
            "https://orcid.org/0000-0003-1358-2049",
        ),
        "scholar_id": scholar.get("scholar_id", "FzMu3LkAAAAJ"),
        "scholar_url": scholar.get(
            "scholar_url",
            "https://scholar.google.com/citations?user=FzMu3LkAAAAJ&hl=en",
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
        "works": works,
    }


def main() -> int:
    payload = build_final_payload()
    write_payload_if_changed(FINAL_PATH, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
