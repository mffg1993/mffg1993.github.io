# Monthly Google Scholar add-on

This add-on is configured for:

- ORCID: `0000-0003-1358-2049`
- Google Scholar ID: `FzMu3LkAAAAJ`
- Website repository: `mffg1993/mffg1993.github.io`

It preserves the existing Crossref/OpenAlex process and adds a separate,
best-effort Google Scholar process.

## Resulting data flow

```text
Crossref + OpenAlex
        ↓
_data/publications_regular.json
        +
last successful Google Scholar result
        ↓
_data/publications_scholar.json
        ↓
DOI/title duplicate checking
        ↓
_data/publications.json
```

The website continues reading `_data/publications.json`; the publication page
and Jekyll include do not need to change.

## Files to upload

Upload the contents of this package to the root of the `gh-pages` branch,
preserving the folder structure.

### Replace these existing files

```text
.github/workflows/update-publications.yml
_scripts/update_publications.py
requirements-publications.txt
```

### Add these new files

```text
.github/workflows/update-scholar-publications.yml
_scripts/merge_publications.py
_scripts/update_scholar_publications.py
requirements-scholar.txt
```

Do **not** delete or replace the current `_data/publications.json`.

The following files will be generated automatically by the workflows:

```text
_data/publications_regular.json
_data/publications_scholar.json
```

## First run after installation

Run the reliable workflow first:

```text
Actions → Update publications → Run workflow
```

It should:

1. create `_data/publications_regular.json`;
2. merge it with any Scholar cache;
3. update `_data/publications.json`;
4. commit both generated files.

Then run the Scholar workflow:

```text
Actions → Update publications from Google Scholar → Run workflow
```

A successful Scholar run creates `_data/publications_scholar.json` and adds
Scholar-only papers to `_data/publications.json`.

## Scholar failure behavior

Google Scholar may block a GitHub Actions runner or return a CAPTCHA.

When that happens:

- the workflow prints a warning;
- the previous `_data/publications_scholar.json` remains untouched;
- the merger uses that previous successful cache;
- the reliable Crossref/OpenAlex process continues normally;
- the website does not lose publications.

If Scholar has never succeeded, the merger simply uses the reliable data.

## Duplicate rules

Records are considered duplicates in this order:

1. same normalized DOI;
2. same normalized title and year;
3. same normalized title.

For duplicates, Crossref/OpenAlex remains authoritative. Scholar only fills
empty fields and stores supplementary fields such as:

```json
"scholar_id": "...",
"scholar_url": "...",
"scholar_citations": 12
```

A work found only in Scholar is added as a normal publication with:

```json
"data_source": "Google Scholar"
```

## Schedule

- Crossref/OpenAlex: every Monday, as before.
- Google Scholar: first day of every month.
- Both workflows also retain a manual **Run workflow** button.

## Workflow permissions

The repository must allow workflows to commit generated JSON files:

```text
Settings → Actions → General → Workflow permissions
→ Read and write permissions
```

## Files that should not be edited manually

These are generated caches:

```text
_data/publications_regular.json
_data/publications_scholar.json
_data/publications.json
```

When a paper is missing from Crossref/OpenAlex but appears on your Google
Scholar profile, the monthly Scholar workflow should add it automatically.
