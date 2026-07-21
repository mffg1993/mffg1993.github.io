# Automatic publication updates

This package is configured for:

- **Author:** Manuel F. Ferrer-Garcia
- **ORCID:** `0000-0003-1358-2049`
- **Repository:** `mffg1993/mffg1993.github.io`
- **Jekyll branch:** `gh-pages`

## Files to add or replace

Copy the package contents into the root of the website repository while
preserving the folder structure:

```text
.github/
└── workflows/
    └── update-publications.yml

_data/
└── publications.json

_includes/
└── publications.html

_scripts/
└── update_publications.py

publications.md
requirements-publications.txt
```

The new `_includes/publications.html` replaces the current publication
include. The old `_data/citations.csv` can remain temporarily; the new include
does not use it.

## First run

1. Commit the files to the `gh-pages` branch.
2. Open the repository's **Actions** tab.
3. Choose **Update publications**.
4. Select **Run workflow**.
5. Wait for the workflow to finish.

The workflow will create the first populated `_data/publications.json` and
commit it to the website automatically. Jekyll will then rebuild the site.

## How the sources work

### Crossref: enabled immediately

Crossref is queried using the ORCID iD. Its public REST API does not require an
account or API key.

For the Crossref polite pool, an optional repository variable can be added:

```text
Name:  CROSSREF_MAILTO
Value: your preferred contact email
```

Add it under:

```text
Repository Settings → Secrets and variables → Actions → Variables
```

### OpenAlex: optional but recommended

OpenAlex can provide broader coverage, open-access links, and OpenAlex citation
counts. The current OpenAlex API requires a free API key.

1. Create a free OpenAlex account and obtain an API key:
   `https://openalex.org/settings/api`
2. In the GitHub repository, open:
   **Settings → Secrets and variables → Actions → Secrets**
3. Add this repository secret:

```text
Name:  OPENALEX_API_KEY
Value: your OpenAlex API key
```

4. Run the workflow again.

The API key remains stored as a GitHub secret and is not written into the
website files.

## Schedule

The workflow runs every Monday and also has a manual **Run workflow** button.
It commits only when publication metadata or citation counts have actually
changed.

## If GitHub cannot push the update

Open:

```text
Repository Settings → Actions → General → Workflow permissions
```

Choose **Read and write permissions**, save the change, and rerun the workflow.

## Publication-page behavior

The generated page:

- sorts publications from newest to oldest;
- groups them by year;
- links titles and DOIs;
- displays open-access links when OpenAlex provides one;
- displays citation counts with the database name;
- bolds the author when the source includes the matching ORCID;
- supports the existing Jekyll include pattern with an optional limit.

For example, the homepage can show the five newest publications using:

```liquid
{% include publications.html limit=5 %}
```
