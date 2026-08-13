# bibshelf

Shelve a paper or a book: fetch its bibtex, file its pdf, name it something you
can find again.

```console
$ bs 10.1145/3411764.3445518 --pdf ~/Downloads/paper.pdf
bs: ~/Downloads/paper.pdf --> .../files/Sambasivan et al - 2021 - Everyone wants to do the model work, not the data work Data Cascades in High-Stakes AI.pdf
bs: proceed? [y/N]:
```

You get the renamed pdf, a `.bib` beside it, and the bibkey on your clipboard.

## Install

```console
uv tool install bibshelf     # or: pipx install bibshelf
```

The only optional dependency is `pdftotext` (from poppler), used to read an
identifier off a pdf. Without it that one feature asks you to type the
identifier instead; everything else works.

## Use

Give it a **DOI**, an **arXiv id**, or an **ISBN**:

```console
$ bs 10.1109/CAIN58948.2023.00034     # doi
$ bs 2211.09545                       # arxiv, new style
$ bs hep-th/9711200                   # arxiv, pre-2007
$ bs 978-0-262-03561-3                # isbn, hyphens optional
```

With `--pdf` it also files the pdf. Papers go to `files/`, books (anything with
an ISBN) go to `books/`, both under `~/Documents/references`.

Leave the identifier out and it reads one off the pdf itself, then shows you the
entry it resolved before committing to anything:

```console
$ bs --pdf paper.pdf
bs: paper.pdf says 10.1007/s10664-023-10291-1

@article{morovati2023bugs,
  author = {Morovati, Mohammad Mehdi and Nikanjam, Amin and Khomh, Foutse},
  title = {Bugs in Machine Learning-Based Systems: A Faultload Benchmark},
  ...
}

bs: does this match the pdf? [Y/n]:
```

If the pdf mentions several identifiers — conference papers often carry both
their own doi and their proceedings' — it lists them and lets you pick. Say no
to one and it offers the next.

| flag | |
| --- | --- |
| `-p, --pdf PATH` | file this pdf alongside the entry |
| `-f, --force` | don't ask before moving anything |
| `-x, --to-clipboard` | copy the whole entry rather than just the bibkey |

## How files are named

```
Sambasivan et al - 2021 - Everyone wants to do the model work Data Cascades in High-Stakes AI.pdf
[  first creator  ] [year] [                     title                                       ]
```

One author is `Fowler`, two are `Aldiabat and Le Navenec`, three or more are
`Nahar et al`. Missing pieces drop out, so an undated book is just
`Barocas - Fairness and Machine Learning.pdf`.

Colons and double quotes are removed, accents are folded (`Géron` becomes
`Geron`), and the whole name is capped at the 255 bytes a filename allows,
cut on a character boundary. Accents survive in the bibtex `author` field —
they are only stripped from filenames and bibkeys, which latex is fussy about.

## Where the metadata comes from

DOIs and arXiv ids both resolve through `doi.org` content negotiation, which
returns CSL-JSON for Crossref and DataCite alike; an arXiv id becomes the doi
arXiv minted for it (`10.48550/arXiv.<id>`). ISBNs go to Open Library, whose
coverage is thinner — expect to eyeball book entries more than paper ones.

Entries are rendered directly from CSL. Titles are emitted verbatim, without
brace protection or title-casing, which means a style like `plain.bst` may
re-case them.

## Licence

MIT.
