#!/usr/bin/env python3
"""
Update the Jekyll publication database for Manuel F. Ferrer-Garcia.

Primary source:
    Crossref, filtered using the author's ORCID iD. This works without an API key.

Optional enrichment:
    OpenAlex, when the OPENALEX_API_KEY environment variable is available.
    OpenAlex generally provides broader coverage, open-access links, and citation
    counts, but its current API requires a free API key.

Output:
    _data/publications.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


ORCID_ID = os.getenv("ORCID_ID", "0000-0003-1358-2049").strip()
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "").strip()
CROSSREF_MAILTO = os.getenv("CROSSREF_MAILTO", "").strip()

OUTPUT_PATH = Path("_data/publications.json")
REQUEST_TIMEOUT = 30
MAX_ATTEMPTS = 4

# OpenAlex document types that normally should not appear on an academic
# publication page. Add more types here later if needed.
EXCLUDED_OPENALEX_TYPES = {"paratext"}


def request_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Request JSON with a small exponential-backoff retry policy."""
    request_headers = {
        "Accept": "application/json",
        "User-Agent": (
            "mffg1993.github.io-publication-updater/"
            "1.0 (https://github.com/mffg1993/mffg1993.github.io)"
        ),
    }
    if headers:
        request_headers.update(headers)

    last_error: Exception | None = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            response = requests.get(
                url,
                params=params,
                headers=request_headers,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 429 or response.status_code >= 500:
                wait_seconds = 2**attempt
                print(
                    f"Temporary API response {response.status_code}; "
                    f"retrying in {wait_seconds} s..."
                )
                time.sleep(wait_seconds)
                continue

            response.raise_for_status()
            return response.json()

        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt == MAX_ATTEMPTS - 1:
                break
            wait_seconds = 2**attempt
            print(f"Request failed; retrying in {wait_seconds} s: {exc}")
            time.sleep(wait_seconds)

    raise RuntimeError(f"Could not retrieve {url}: {last_error}")


def normalize_orcid(value: str | None) -> str:
    """Return only the four ORCID number groups."""
    if not value:
        return ""
    match = re.search(r"\d{4}-\d{4}-\d{4}-[\dX]{4}", value, flags=re.I)
    return match.group(0).upper() if match else ""


def normalize_doi(value: str | None) -> str:
    """Return a bare DOI without a doi.org prefix."""
    if not value:
        return ""
    doi = value.strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    return doi.strip()


def normalize_title(value: str) -> str:
    """Normalize a title for cross-database duplicate detection."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(character for character in value if not unicodedata.combining(character))
    value = value.casefold()
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def first_nonempty(values: list[Any], default: Any = "") -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return default


def date_parts_to_iso(date_parts: Any) -> tuple[str, int | None]:
    """
    Convert Crossref date-parts to an ISO-like string and year.

    Crossref uses forms such as [[2023, 11, 24]].
    """
    try:
        parts = date_parts[0]
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return f"{year:04d}-{month:02d}-{day:02d}", year
    except (TypeError, ValueError, IndexError):
        return "", None


def crossref_authors(item: dict[str, Any]) -> list[dict[str, Any]]:
    authors: list[dict[str, Any]] = []

    for author in item.get("author", []):
        name = " ".join(
            part.strip()
            for part in [author.get("given", ""), author.get("family", "")]
            if part and part.strip()
        )
        if not name:
            name = author.get("name", "").strip()
        if not name:
            continue

        author_orcid = normalize_orcid(author.get("ORCID"))
        authors.append(
            {
                "name": name,
                "orcid": author_orcid or None,
                "is_me": author_orcid == ORCID_ID,
            }
        )

    return authors


def fetch_crossref_works() -> list[dict[str, Any]]:
    """Fetch Crossref works whose deposited metadata contains this ORCID iD."""
    params: dict[str, Any] = {
        "filter": f"orcid:{ORCID_ID}",
        "rows": 1000,
        "sort": "published",
        "order": "desc",
    }
    if CROSSREF_MAILTO:
        params["mailto"] = CROSSREF_MAILTO

    data = request_json("https://api.crossref.org/works", params=params)
    items = data.get("message", {}).get("items", [])

    works: list[dict[str, Any]] = []

    for item in items:
        titles = item.get("title") or []
        title = titles[0].strip() if titles else ""
        if not title:
            continue

        date_object = first_nonempty(
            [
                item.get("published-online"),
                item.get("published-print"),
                item.get("published"),
                item.get("issued"),
                item.get("created"),
            ],
            {},
        )
        publication_date, year = date_parts_to_iso(date_object.get("date-parts", []))

        doi = normalize_doi(item.get("DOI"))
        container_titles = item.get("container-title") or []
        venue = container_titles[0].strip() if container_titles else ""

        pages = first_nonempty(
            [
                item.get("page", ""),
                item.get("article-number", ""),
            ]
        )

        works.append(
            {
                "title": title,
                "authors": crossref_authors(item),
                "venue": venue,
                "year": year,
                "publication_date": publication_date,
                "type": item.get("type", ""),
                "doi": doi or None,
                "url": f"https://doi.org/{quote(doi, safe='/()')}" if doi else item.get("URL"),
                "open_access_url": None,
                "volume": item.get("volume") or None,
                "issue": item.get("issue") or None,
                "pages": pages or None,
                "cited_by_count": int(item.get("is-referenced-by-count", 0) or 0),
                "citation_source": "Crossref",
                "data_source": "Crossref",
                "openalex_id": None,
            }
        )

    print(f"Crossref returned {len(works)} works.")
    return works


def openalex_authors(item: dict[str, Any]) -> list[dict[str, Any]]:
    authors: list[dict[str, Any]] = []

    for authorship in item.get("authorships", []):
        author = authorship.get("author") or {}
        name = (author.get("display_name") or "").strip()
        if not name:
            continue

        author_orcid = normalize_orcid(author.get("orcid"))
        authors.append(
            {
                "name": name,
                "orcid": author_orcid or None,
                "is_me": author_orcid == ORCID_ID,
            }
        )

    return authors


def choose_openalex_url(item: dict[str, Any], doi: str) -> tuple[str | None, str | None]:
    best_oa = item.get("best_oa_location") or {}
    primary = item.get("primary_location") or {}
    open_access = item.get("open_access") or {}

    normal_url = first_nonempty(
        [
            f"https://doi.org/{quote(doi, safe='/()')}" if doi else "",
            primary.get("landing_page_url"),
            best_oa.get("landing_page_url"),
            item.get("id"),
        ],
        None,
    )

    oa_url = None
    if open_access.get("is_oa"):
        oa_url = first_nonempty(
            [
                best_oa.get("pdf_url"),
                best_oa.get("landing_page_url"),
                open_access.get("oa_url"),
            ],
            None,
        )

    return normal_url, oa_url


def fetch_openalex_works() -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """
    Fetch OpenAlex works.

    This step is optional because the current OpenAlex API requires a free API key.
    """
    if not OPENALEX_API_KEY:
        print(
            "OPENALEX_API_KEY is not set. Continuing with Crossref only. "
            "Add the key as a GitHub Actions secret for broader coverage."
        )
        return [], None

    encoded_orcid = quote(f"https://orcid.org/{ORCID_ID}", safe="")
    author_url = f"https://api.openalex.org/authors/{encoded_orcid}"
    author = request_json(
        author_url,
        params={"api_key": OPENALEX_API_KEY},
    )

    full_author_id = author.get("id", "")
    author_id = full_author_id.rsplit("/", 1)[-1]
    if not author_id:
        raise RuntimeError(f"OpenAlex could not resolve ORCID {ORCID_ID}.")

    works: list[dict[str, Any]] = []
    cursor = "*"

    while cursor:
        data = request_json(
            "https://api.openalex.org/works",
            params={
                "api_key": OPENALEX_API_KEY,
                "filter": f"author.id:{author_id}",
                "sort": "-publication_date",
                "per_page": 100,
                "cursor": cursor,
            },
        )

        for item in data.get("results", []):
            if item.get("is_retracted"):
                continue
            if item.get("type") in EXCLUDED_OPENALEX_TYPES:
                continue

            title = (item.get("display_name") or item.get("title") or "").strip()
            if not title:
                continue

            ids = item.get("ids") or {}
            doi = normalize_doi(ids.get("doi") or item.get("doi"))
            normal_url, oa_url = choose_openalex_url(item, doi)

            primary_location = item.get("primary_location") or {}
            source = primary_location.get("source") or {}
            venue = (source.get("display_name") or "").strip()

            biblio = item.get("biblio") or {}
            first_page = biblio.get("first_page")
            last_page = biblio.get("last_page")
            pages = None
            if first_page and last_page and first_page != last_page:
                pages = f"{first_page}–{last_page}"
            elif first_page:
                pages = str(first_page)

            works.append(
                {
                    "title": title,
                    "authors": openalex_authors(item),
                    "venue": venue,
                    "year": item.get("publication_year"),
                    "publication_date": item.get("publication_date") or "",
                    "type": item.get("type") or "",
                    "doi": doi or None,
                    "url": normal_url,
                    "open_access_url": oa_url,
                    "volume": biblio.get("volume") or None,
                    "issue": biblio.get("issue") or None,
                    "pages": pages,
                    "cited_by_count": int(item.get("cited_by_count", 0) or 0),
                    "citation_source": "OpenAlex",
                    "data_source": "OpenAlex",
                    "openalex_id": item.get("id"),
                }
            )

        cursor = data.get("meta", {}).get("next_cursor")

    print(f"OpenAlex returned {len(works)} works.")
    return works, author


def work_key(work: dict[str, Any]) -> str:
    doi = normalize_doi(work.get("doi"))
    if doi:
        return f"doi:{doi.casefold()}"
    return f"title:{normalize_title(work.get('title', ''))}"


def merge_works(
    crossref_works: list[dict[str, Any]],
    openalex_works: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge records, preferring OpenAlex metadata while retaining useful
    Crossref values when OpenAlex leaves a field empty.
    """
    merged: dict[str, dict[str, Any]] = {}

    for work in crossref_works:
        merged[work_key(work)] = work

    for openalex_work in openalex_works:
        key = work_key(openalex_work)
        existing = merged.get(key)

        if not existing:
            merged[key] = openalex_work
            continue

        combined = existing.copy()
        for field, value in openalex_work.items():
            if value not in (None, "", [], {}):
                combined[field] = value

        # Preserve an OA URL from either source if one is available.
        combined["open_access_url"] = first_nonempty(
            [
                openalex_work.get("open_access_url"),
                existing.get("open_access_url"),
            ],
            None,
        )
        merged[key] = combined

    works = list(merged.values())

    # Remove malformed records and ensure consistent scalar values.
    cleaned: list[dict[str, Any]] = []
    for work in works:
        if not work.get("title"):
            continue
        if not work.get("year"):
            # Keep undated works at the bottom rather than discarding them.
            work["year"] = "Undated"
        cleaned.append(work)

    def sort_key(work: dict[str, Any]) -> tuple[int, str, str]:
        year = work.get("year")
        numeric_year = int(year) if str(year).isdigit() else 0
        return (
            numeric_year,
            work.get("publication_date") or "",
            normalize_title(work.get("title") or ""),
        )

    cleaned.sort(key=sort_key, reverse=True)
    return cleaned


def write_output(payload: dict[str, Any]) -> bool:
    """
    Write only when publication metadata has changed.

    This avoids creating a meaningless scheduled commit merely because the
    generated_at timestamp changed.
    """
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if OUTPUT_PATH.exists():
        try:
            old_payload = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
            old_comparable = {key: value for key, value in old_payload.items() if key != "generated_at"}
            new_comparable = {key: value for key, value in payload.items() if key != "generated_at"}

            if old_comparable == new_comparable:
                print("Publication data has not changed; no file was rewritten.")
                return False
        except (json.JSONDecodeError, OSError):
            pass

    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT_PATH} with {len(payload['works'])} works.")
    return True


def main() -> int:
    if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-[\dX]{4}", ORCID_ID, flags=re.I):
        print(f"Invalid ORCID iD: {ORCID_ID}", file=sys.stderr)
        return 2

    try:
        crossref_works = fetch_crossref_works()
        openalex_works, openalex_author = fetch_openalex_works()
        works = merge_works(crossref_works, openalex_works)

        author_name = None
        openalex_author_id = None
        if openalex_author:
            author_name = openalex_author.get("display_name")
            openalex_author_id = openalex_author.get("id")

        sources = ["Crossref"]
        if openalex_works:
            sources.append("OpenAlex")

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "orcid": ORCID_ID,
            "orcid_url": f"https://orcid.org/{ORCID_ID}",
            "author_name": author_name or "Manuel F. Ferrer-Garcia",
            "openalex_author_id": openalex_author_id,
            "sources": sources,
            "works": works,
        }

        write_output(payload)
        return 0

    except Exception as exc:
        print(f"Publication update failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
