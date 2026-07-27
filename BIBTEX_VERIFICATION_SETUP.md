# Verified BibTeX publication add-on

This add-on keeps the existing automatic publication system and adds the
uploaded BibTeX file as a verified third source.

## Source priority

```text
Verified BibTeX
    ↓
Crossref / OpenAlex
    ↓
Google Scholar
```

The priority applies to stable bibliographic fields such as title, authors,
journal, year, volume, issue, and pages. Citation counts and database-specific
identifiers are preserved from their original sources.

## Files in this package

### Replace

```text
_scripts/merge_publications.py
.github/workflows/update-publications.yml
.github/workflows/update-scholar-publications.yml
```

### Add

```text
_data/publications_verified.bib
.github/workflows/merge-publications.yml
BIBTEX_VERIFICATION_SETUP.md
```

The supplied BibTeX file contains 12 entries. One extra standalone closing
brace after `aguilar2025tailoring` was removed because it made the original
BibTeX malformed.

## Installation

1. Extract the ZIP.
2. Upload all contents to the root of the `gh-pages` branch.
3. Preserve the folder structure.
4. Commit directly to `gh-pages`.

The new `Merge verified BibTeX publications` workflow starts automatically
when either of these files changes:

```text
_data/publications_verified.bib
_scripts/merge_publications.py
```

It can also be run manually from the Actions tab.

## Generated audit

Every merge creates:

```text
_data/publications_audit.json
```

The audit reports:

- automatic records found;
- Scholar records available;
- BibTeX records parsed;
- BibTeX records matched to existing publications;
- BibTeX-only publications added;
- final publication count;
- BibTeX parsing warnings;
- titles added from BibTeX.

## Future updates

To add or correct a publication, edit:

```text
_data/publications_verified.bib
```

Commit the edit. The merge workflow will automatically rebuild
`_data/publications.json`.

The BibTeX list is additive. A publication found automatically but not present
in the BibTeX file is not deleted.
