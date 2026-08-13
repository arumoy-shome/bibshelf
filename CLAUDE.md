# bibshelf

Given a DOI, arXiv id or ISBN — or just a pdf — fetch the bibtex, file the pdf
under a canonical name, and drop the `.bib` beside it. Installs as `bs`.

It grew out of `bin/doi2bib` in `~/dotfiles`, which was a 113-line DOI-to-bibtex
converter. That copy still exists but is superseded; see "Open items".

## Running things

```console
uv run pytest            # 125 tests, ~0.06s, no network
uv run bs <identifier>   # from the repo
bs <identifier>          # installed via: uv tool install ~/code/bibshelf
```

Tests never touch the network: `tests/fixtures/*.json` hold recorded API
responses and the `offline` fixture monkeypatches `fetch`. The suite passes on
Python 3.11 and 3.13 (both verified, not assumed).

## Releasing

`__version__` is read off the installed distribution with
`importlib.metadata`, so `pyproject.toml` is the only place a version number is
written down and `bs --version` cannot drift from it.

Bump `version` in `pyproject.toml`, then tag: `.github/workflows/publish.yml`
fires on `v*`, runs the tests, refuses a tag that disagrees with the declared
version, and uploads. Its `workflow_dispatch` publishes to TestPyPI instead, for
rehearsing a release.

Uploads use **trusted publishing**, so there is no api token anywhere: PyPI
trades the workflow's OIDC token for a short lived one. It has to be registered
per index — the publisher is `arumoy-shome/bibshelf`, workflow `publish.yml`, on
both pypi.org and test.pypi.org.

A version on PyPI cannot be replaced, only yanked, so the rehearsal is worth it.

## Decisions worth not re-litigating

These were deliberate and mostly came from the author, who has a real library of
89 papers and 37 books at `~/Documents/references/{files,books}`. The filename
rules were reverse-engineered from those files and then amended by hand.

**Filenames: `[first creator] - [year] - [title]`**

- one author `Fowler`, two `Aldiabat and Le Navenec`, three or more `Nahar et al`
- **`et al` has no period.** The 86 Zotero-exported files use `et al.`; the
  author explicitly asked to drop it
- colons and double quotes are removed; **apostrophes and commas are kept**,
  because the library depends on them (`The Startup Owner's Manual`)
- missing segments drop out, so an undated book is `Barocas - Fairness and
  Machine Learning.pdf`
- capped at 255 bytes, cut on a character boundary

**Accents are folded in filenames and bibkeys, kept in the bibtex `author`
field.** `Géron` names the file `Geron - 2019 - ...` and keys it
`geron2019hands-on`, but the entry still says `{Géron, Aurélien}`. Latex is
fussy about keys; filenames are the author's preference. Non-Latin scripts pass
through untouched — CJK is not an accent, and stripping it would empty the name.

**Titles are emitted verbatim.** No brace protection, no title-casing. A style
like `plain.bst` may therefore re-case them. This was chosen over pandoc's
`{Meta-Summary}` style with the tradeoff understood.

**No `abstract` field.** It is long, it is already in the pdf sitting next to
the entry, and escaping it mangles the author's maths (`$P$` → `\$P\$`).

**pandoc and bibtool were removed on purpose.** They were being fought, not
used: Crossref's type vocabulary is not CSL's (hence `CSL_TYPES`), pandoc drops
ISBNs and force-smartens `O'Reilly` into `O’Reilly` with no way to disable it,
and bibtool emitted unicode and quote characters in keys that then had to be
scrubbed twice. Rendering bibtex directly cost ~100 lines and removed both
dependencies. `pdftotext` remains but degrades to a prompt when absent.

**Metadata sources.** DOIs and arXiv ids both go through `doi.org` content
negotiation for CSL-JSON, which serves Crossref and DataCite alike; a bare arXiv
id becomes `10.48550/arXiv.<id>`, verified working for pre-2007 slash ids like
`hep-th/9711200`. ISBNs go to Open Library, whose data is thinner and messier —
flat name strings (hence `split_name` and `PARTICLES`), free-text dates, and
duplicate authors.

**`SOURCES = (Isbn, Doi)` order is load-bearing.** `Doi.matches` accepts
anything, so an ISBN checked second would be mistaken for an arXiv id. A bad
ISBN checksum exits rather than falling through.

**The library is `--library`, then `$BIBSHELF_LIBRARY`, then
`~/Documents/references`.** `library_root()` resolves the three and expands the
`~` an environment variable is likely to be written with. The directories are
still not created: `archive` exits if `files/` or `books/` is missing, on the
grounds that a typo'd path should not quietly grow a new library.

**No stdlib clipboard exists.** `tkinter` is the only candidate and it is not
usable here — under X11 the clipboard belongs to the process that set it, so it
empties the moment `bs` exits. `to_clipboard` shells out to the first of
`pbcopy` / `clip` / `wl-copy` / `xclip` / `xsel` / `clip.exe` that works for the
platform, and returns False if none did so `main` can print the entry rather
than swallow it. Missing (`FileNotFoundError`) and present-but-failing
(`CalledProcessError`, e.g. `wl-copy` with no wayland session) both fall
through to the next candidate.

**Only pages 1–2 of a pdf are scanned** for identifiers. Going further picks up
dois from the reference list. Unfilled latex placeholders
(`10.1145/nnnnnnn.nnnnnnn`) are filtered.

**Resolving is the validation.** An identifier read off a pdf is resolved and
the resulting entry shown before anything moves — a conference paper often
carries both its own doi and its proceedings' doi, and picking the wrong one
silently files it as *Proceedings of the 2019 CHI Conference*. Rejecting a
candidate offers the next one.

## Shape of the code

`src/bibshelf/__init__.py`, one module. Three classes and a lot of small pure
functions, which was deliberate — most of the helpers are string transforms and
would gain nothing from being methods.

- `Reference` — dataclass: `item` (CSL), `bibtex`, `directory`, `bibkey`
- `Library` — the paths and the naming rules; `filename()` and `archive()`
- `Source` ABC with `Isbn` and `Doi` — `matches()` then `fetch()` → CSL item

## Open items

- **The clipboard dispatch is only proven on macOS.** The linux and windows
  branches are unit-tested with a stubbed `subprocess.run`, so the command names
  and arguments have never actually been run. CI will not catch it either. The
  classifiers claim macOS and Linux only, for that reason, though the code has a
  `win32` branch.
- **`~/dotfiles` still has the old copy** — `bin/doi2bib` plus untracked
  `tests/`, `pyproject.toml`, `uv.lock`. Remove once `bs` has proved itself.
- **Untested**: `read_pdf`, and all of `main()`'s argparse wiring bar
  `--version`. Both thin wrappers.
- The naming rules are one researcher's convention. Templating them would be
  the honest thing to do for a public tool.
