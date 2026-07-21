#!/usr/bin/env python3
"""
Attempt a lightweight monthly refresh from a specific Google Scholar profile.

The script deliberately does not fill each publication individually. The
author-profile publication list normally contains enough information to find
papers missing from Crossref/OpenAlex, while making fewer Scholar requests.

Failure policy:
    * Never overwrite _data/publications_scholar.json after an exception,
      CAPTCHA/block, empty response, or suspiciously incomplete response.
    * Emit a GitHub Actions warning.
    * Exit successfully so the workflow can merge the previous cache.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from merge_publications import (
    deduplicate_works,
    load_payload,
    normalize_doi,
    write_payload_if_changed,
)


SCHOLAR_ID = os.getenv("SCHOLAR_ID", "FzMu3LkAAAAJ").strip()
SCHOLAR_CACHE_PATH = Path("_data/publications_scholar.json")

DOI_PATTERN = re.compile(
    r"10\.\d{4,9}/[-._;()/:A-Z0-9]+",
    flags=re.I,
)


def action_warning(message: str) -> None:
    safe_message = message.replace("\n", " ").replace("\r", " ")
    print(f"::warning title=Google Scholar refresh skipped::{safe_message}")


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def extract_doi(value: Any) -> str:
    """
    Search recursively through the lightly filled Scholar record for a DOI.
    Many Scholar profile records do not include one, so an empty result is
    expected and title matching remains the normal fallback.
    """
    strings: list[str] = []

    def collect(item: Any) -> None:
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, dict):
            for child in item.values():
                collect(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                collect(child)

    collect(value)

    for text in strings:
        match = DOI_PATTERN.search(text)
        if match:
            return normalize_doi(match.group(0).rstrip(".,;)]}"))

    return ""


def author_objects(raw_authors: Any) -> list[dict[str, Any]]:
    if isinstance(raw_authors, list):
        names = [str(name).strip() for name in raw_authors if str(name).strip()]
    elif isinstance(raw_authors, str):
        if " and " in raw_authors:
            names = [
                name.strip()
                for name in raw_authors.split(" and ")
                if name.strip()
            ]
        else:
            names = [raw_authors.strip()] if raw_authors.strip() else []
    else:
        names = []

    result: list[dict[str, Any]] = []
    for name in names:
        normalized = re.sub(r"[^a-z]", "", name.casefold())
        is_me = "manuel" in normalized and "ferrer" in normalized
        result.append(
            {
                "name": name,
                "orcid": "0000-0003-1358-2049" if is_me else None,
                "is_me": is_me,
            }
        )
    return result


def publication_url(publication: dict[str, Any]) -> str | None:
    bib = publication.get("bib") or {}

    for key in ("pub_url", "eprint_url"):
        value = publication.get(key) or bib.get(key)
        if value:
            return str(value)

    author_pub_id = publication.get("author_pub_id")
    if author_pub_id:
        return (
            "https://scholar.google.com/citations?"
            "view_op=view_citation&hl=en&citation_for_view="
            f"{quote(str(author_pub_id), safe=':')}"
        )

    return None


def convert_publication(publication: dict[str, Any]) -> dict[str, Any] | None:
    bib = publication.get("bib") or {}
    title = str(bib.get("title") or publication.get("title") or "").strip()
    if not title:
        return None

    raw_year = (
        bib.get("pub_year")
        or bib.get("year")
        or publication.get("pub_year")
        or publication.get("year")
    )
    year_match = re.search(r"\b(19|20)\d{2}\b", str(raw_year or ""))
    year: int | str = int(year_match.group(0)) if year_match else "Undated"

    venue = next(
        (
            str(value).strip()
            for value in (
                bib.get("journal"),
                bib.get("conference"),
                bib.get("venue"),
                bib.get("citation"),
                bib.get("publisher"),
            )
            if value and str(value).strip()
        ),
        "",
    )

    doi = extract_doi(publication)
    scholar_id = publication.get("author_pub_id")
    scholar_url = publication_url(publication)
    citations = safe_int(publication.get("num_citations"))

    return {
        "title": title,
        "authors": author_objects(bib.get("author")),
        "venue": venue,
        "year": year,
        "publication_date": f"{year:04d}-01-01" if isinstance(year, int) else "",
        "type": str(bib.get("pub_type") or "article"),
        "doi": doi or None,
        "url": (
            f"https://doi.org/{quote(doi, safe='/()')}"
            if doi
            else scholar_url
        ),
        "open_access_url": publication.get("eprint_url") or None,
        "volume": bib.get("volume") or None,
        "issue": bib.get("number") or bib.get("issue") or None,
        "pages": bib.get("pages") or None,
        "cited_by_count": citations,
        "citation_source": "Google Scholar",
        "scholar_citations": citations,
        "data_source": "Google Scholar",
        "data_sources": ["Google Scholar"],
        "scholar_id": scholar_id,
        "scholar_url": scholar_url,
        "openalex_id": None,
    }


def retrieve_scholar_payload() -> dict[str, Any]:
    try:
        from scholarly import scholarly
    except ImportError as exc:
        raise RuntimeError(
            "The scholarly package could not be imported. "
            "The previous Scholar cache will be retained."
        ) from exc

    print(f"Requesting Google Scholar profile {SCHOLAR_ID}...")

    author = scholarly.search_author_id(SCHOLAR_ID)
    author = scholarly.fill(
        author,
        sections=["basics", "publications"],
    )

    returned_id = str(author.get("scholar_id") or "").strip()
    if returned_id and returned_id != SCHOLAR_ID:
        raise RuntimeError(
            f"Scholar returned profile {returned_id}, not {SCHOLAR_ID}."
        )

    publications = author.get("publications") or []
    works = []

    for publication in publications:
        if not isinstance(publication, dict):
            continue
        converted = convert_publication(publication)
        if converted:
            works.append(converted)

    works = deduplicate_works(works)
    if not works:
        raise RuntimeError(
            "Google Scholar returned no usable publications. This may be a "
            "temporary block or CAPTCHA response."
        )

    previous = load_payload(SCHOLAR_CACHE_PATH)
    previous_count = len(previous.get("works", []))

    # Reject a suspiciously truncated profile instead of destroying a good cache.
    if previous_count >= 5:
        minimum_acceptable = max(3, int(previous_count * 0.60))
        if len(works) < minimum_acceptable:
            raise RuntimeError(
                f"Scholar returned only {len(works)} publications, while the "
                f"previous successful cache contained {previous_count}. "
                "The response looks incomplete."
            )

    author_name = (
        author.get("name")
        or author.get("bib", {}).get("name")
        or "Manuel F. Ferrer-Garcia"
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scholar_id": SCHOLAR_ID,
        "scholar_url": (
            "https://scholar.google.com/citations?"
            f"user={SCHOLAR_ID}&hl=en"
        ),
        "author_name": author_name,
        "sources": ["Google Scholar"],
        "works": works,
    }


def main() -> int:
    try:
        payload = retrieve_scholar_payload()
        write_payload_if_changed(SCHOLAR_CACHE_PATH, payload)
        print(
            f"Google Scholar refresh succeeded with "
            f"{len(payload['works'])} publications."
        )
        return 0

    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        action_warning(message)
        print(
            "Google Scholar refresh was not applied. "
            "The previous publications_scholar.json file remains unchanged.",
            file=sys.stderr,
        )
        # This is intentionally zero. Scholar is supplementary, and a block
        # must not break the reliable publication process or erase the cache.
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
