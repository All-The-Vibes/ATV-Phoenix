# Project Inspection Reference

This reference defines how the `evidence-investigator` lane collects facts for each source
type. The lane is a read-only researcher: it RETURNS findings to the orchestrator and
writes nothing. The orchestrator writes the reconciled facts into `evidence-dossier.md`,
with every claim citing a source path or URL. The format below describes the shape the lane
returns and the orchestrator persists.

## General Rules

- Only record facts that appear verbatim in a source file or HTTP response.
- Do not infer, extrapolate, or editorialize. Record the raw text; let the narrator
  interpret it.
- Every claim the lane returns must carry a `source:` annotation on the same line or the
  following line (indented). The orchestrator preserves these annotations in
  `evidence-dossier.md`.
- Flag any claim without a verifiable source with `[UNVERIFIED]` -- the proof-auditor
  and narrator will exclude it.
- Do not read private credential files (`.env`, `.env.*`, `*secret*`, `*credential*`,
  `*.pem`, `*.key`). Skip them silently.

## Evidence Dossier Format

```markdown
# Evidence Dossier

<!-- project: <inferred title> -->
<!-- collected: <ISO-8601 timestamp> -->
<!-- source root: <project root path> -->

## Project Identity
- name: <value>
  source: package.json#name
- description: <value>
  source: package.json#description

## Key Capabilities
- <capability statement>
  source: README.md:L42-L45

## Metrics and Numbers
- <metric statement>
  source: README.md:L88  [UNVERIFIED if no source]

## Visual Evidence
- <file path> (<file type>, <approximate size>)
  source: <glob match>

## Recent Changes
- <commit message or PR title>
  source: git log / PR body
```

## By Project Type

### Node.js / npm

1. Read `package.json` -- extract `name`, `description`, `version`, `keywords`.
2. Read `README.md` (or `readme.md`) -- extract the first paragraph and any feature
   bullet lists.
3. Read `CHANGELOG.md` or `CHANGELOG` if present -- extract the most recent version
   entry (first H2 section).
4. Glob `src/**/*.{js,ts,jsx,tsx}` -- read up to 3 files that have the longest names
   (likely the core modules). Extract the first JSDoc or block comment from each.
5. Check for `screenshots/`, `docs/`, `assets/` directories -- list any `.png`, `.gif`,
   `.mp4` files found.

### Python

1. Read `pyproject.toml` -- extract `[project] name`, `description`, `version`.
2. Fall back to `setup.py` or `setup.cfg` if `pyproject.toml` absent.
3. Read `README.md` or `README.rst` -- first paragraph and feature lists.
4. Read `CHANGELOG.md` if present.
5. Glob `src/**/*.py` or `<package>/**/*.py` -- read up to 3 core module docstrings.

### Rust

1. Read `Cargo.toml` -- extract `[package] name`, `description`, `version`.
2. Read `README.md` -- first paragraph and feature lists.
3. Read `CHANGELOG.md` if present.
4. Read `src/lib.rs` or `src/main.rs` -- module-level doc comment.

### Go

1. Read `go.mod` -- extract module name.
2. Read `README.md` -- first paragraph and feature lists.
3. Read main package doc comment from `main.go` or `doc.go`.

### Other / Generic

1. Look for any of: `README.md`, `README.rst`, `README.txt`, `index.html`, `docs/index.md`.
2. Read the first 100 lines of the first file found.
3. Glob for any manifest-like file (`*.toml`, `*.yaml`, `*.json` in root).
4. List any screenshot or recording files in root or `assets/`, `docs/`, `screenshots/`.

## PR URL Inspection

When the positional argument is a GitHub PR URL (`github.com/*/pull/*`):

1. Fetch the PR page or API (`https://api.github.com/repos/<owner>/<repo>/pulls/<n>`).
2. Extract: `title`, `body` (first 500 chars), `base.ref`, `head.ref`.
3. Fetch the diff summary from the PR files endpoint; record file paths changed (first 20).
4. Check the PR body for "Fixes #N" references; if found, record linked issue titles.
5. All claims sourced to the PR URL.

Note: do not invent code behavior from diff line counts. Only record what is stated
explicitly in the PR title or body.

## App URL Inspection

When the positional argument is an HTTP/HTTPS URL that is not a GitHub PR:

1. Fetch the page with the host's web-fetch tool or shell HTTP client.
2. Extract: `<title>` tag content, `<meta name="description">` content, and the text
   of the first `<h1>` through `<h3>` tags (up to 5 headings).
3. Look for Open Graph tags (`og:title`, `og:description`, `og:image`).
4. Record all extracted values with the URL as source.
5. Do not invent features from page styling or images; only text content.

## Git History (when available)

When `project-context.mjs` reports `git.available: true`:

1. Run: `git log --oneline -10` (or PowerShell equivalent on Windows).
2. Record the 10 most recent commit messages as "recent changes".
3. Source each commit message to the git log.
4. Do not interpret commits -- record the message text verbatim.

## Asset Scoring Quick Reference

Used by both evidence-investigator and visual-curator:

| Score | Category | Examples |
|-------|----------|---------|
| 1 | Icon / logo | `logo.png`, `favicon.ico`, `icon-*.svg` |
| 2 | Static screenshot | Any `.png`/`.jpg` under `screenshots/`, `docs/`, `assets/` |
| 3 | Demo recording | `.mp4`, `.mov`, `.webm`, `.gif` showing the app running |
| 4 | Annotated demo | Recording with callouts, captions, or highlights visible |

When scoring is ambiguous, prefer the lower score to avoid overstating asset quality.
