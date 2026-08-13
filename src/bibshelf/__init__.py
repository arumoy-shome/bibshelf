"""bibshelf: shelve a paper or a book, bibtex and all."""

import os
import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import metadata
from urllib import request, error

try:
    __version__ = metadata.version("bibshelf")
except metadata.PackageNotFoundError:  # a source tree that was never installed
    __version__ = "unknown"

# Where the library lives, unless --library or $BIBSHELF_LIBRARY says otherwise.
DEFAULT_LIBRARY = "~/Documents/references"
LIBRARY_VARIABLE = "BIBSHELF_LIBRARY"

# APFS caps a filename at 255 bytes; leave room for the ".pdf"/".bib" suffix
MAX_FILENAME_BYTES = 255 - len(".pdf")

# Characters kept out of a filename. The apostrophe is deliberately kept, being
# legal on APFS and present in the hand named files in the library.
ILLEGAL = str.maketrans(
    {
        "/": None,
        "\x00": None,
        ":": None,
        '"': None,
        "“": None,
        "”": None,
        "„": None,
        "«": None,
        "»": None,
    }
)

# Letters whose accent is a stroke or a ligature rather than a combining mark,
# so unicode normalisation cannot take them apart.
STROKES = str.maketrans(
    {
        "ß": "ss",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ø": "o",
        "Ø": "O",
        "đ": "d",
        "Đ": "D",
        "ł": "l",
        "Ł": "L",
        "ð": "d",
        "Ð": "D",
        "þ": "th",
        "Þ": "Th",
        "ı": "i",
    }
)

# Lowercase name particles that belong to the surname ("van der Meer" -> "van
# der Meer"). Only needed for Open Library, which hands back a flat name; doi.org
# gives family and given separately.
PARTICLES = {
    "van",
    "von",
    "der",
    "den",
    "de",
    "del",
    "della",
    "di",
    "da",
    "dos",
    "du",
    "la",
    "le",
    "ter",
    "ten",
}

# NOTE: regex for crossref doi: https://www.crossref.org/blog/dois-and-matching-regular-expressions/
# I modified it to also accept any lowercase letters
DOI = r"^10.\d{4,9}/[-._;()/:a-zA-Z0-9]+$"

# CSL type -> bibtex entry type. Anything unlisted becomes @misc, which is also
# where arxiv preprints land.
BIBTEX_TYPES = {
    "article-journal": "article",
    "book": "book",
    "chapter": "incollection",
    "entry": "misc",
    "paper-conference": "inproceedings",
    "report": "techreport",
    "thesis": "phdthesis",
}

# CSL variable -> bibtex field, for the ones that map straight across
BIBTEX_FIELDS = {
    "DOI": "doi",
    "ISBN": "isbn",
    "URL": "url",
    # NOTE: no abstract. It is long, it is already in the pdf sitting next to the
    # entry, and escaping it mangles whatever maths the author wrote.
    "collection-title": "series",
    "edition": "edition",
    "issue": "number",
    "number": "number",
    "page": "pages",
    "publisher": "publisher",
    "publisher-place": "address",
    "title": "title",
    "volume": "volume",
}

# what the containing work is called depends on what kind of thing it is
CONTAINERS = {
    "article": "journal",
    "incollection": "booktitle",
    "inproceedings": "booktitle",
}

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun",
          "jul", "aug", "sep", "oct", "nov", "dec")

# escaping these would break \url{} and the identifiers are latex-safe already
VERBATIM = {"doi", "url", "isbn"}

# the order a bibtex entry is conventionally read in; anything else follows
FIELD_ORDER = (
    "author", "editor", "title", "booktitle", "journal", "howpublished",
    "series", "edition", "volume", "number", "pages", "publisher", "address",
    "year", "month", "doi", "url", "isbn", "abstract",
)

# Crossref labels entries with its own vocabulary rather than CSL's. Anything
# unmapped is passed through, and BIBTEX_TYPES turns whatever it cannot place
# into @misc.
CSL_TYPES = {
    "book-chapter": "chapter",
    "book-part": "chapter",
    "book-section": "chapter",
    "dissertation": "thesis",
    "journal-article": "article-journal",
    "monograph": "book",
    "posted-content": "article",
    "proceedings-article": "paper-conference",
    "reference-book": "book",
    "reference-entry": "entry",
    "report-component": "report",
}

# CSL variables worth keeping. Everything else is dropped, which also throws
# away the reference list and the licence blocks Crossref pads its records with.
CSL_NAMES = {"author", "editor", "translator"}
CSL_DATES = {"issued"}
CSL_STRINGS = {
    "DOI",
    "ISBN",
    "URL",
    "abstract",
    "collection-title",
    "container-title",
    "edition",
    "event-title",
    "issue",
    "number",
    "page",
    "publisher",
    "publisher-place",
    "title",
    "type",
    "volume",
}


def fetch(url: str, headers: dict[str, str] | None = None) -> dict | None:
    try:
        with request.urlopen(request.Request(url, headers=headers or {})) as response:
            return json.load(response)
    except error.HTTPError as e:
        print(f"bs: HTTP Error {e.code}")
    except error.URLError as e:
        print(f"bs: URL Error {e.reason}")
    except json.JSONDecodeError:
        print("bs: the response was not json")
    return None


def read_pdf(pdf: str) -> str:
    """The first two pages carry the identifier; later ones only hold the
    references, whose dois would be mistaken for this paper's own."""
    try:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "2", pdf, "-"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("bs: pdftotext is not installed, cannot read the pdf")
        return ""

    return result.stdout


def scan_identifiers(text: str) -> list[str]:
    """Arxiv ids first: a stamped preprint is the paper, whatever else it cites."""
    found = [
        f"{prefix}{number}"
        for prefix, number in re.findall(
            r"arxiv[:\s]*(?:([a-z-]+/))?(\d{7}|\d{4}\.\d{4,5})", text, re.I
        )
    ]

    for doi in re.findall(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text):
        doi = doi.rstrip(".,;)")
        # an unfilled latex template leaves 10.1145/nnnnnnn.nnnnnnn behind
        if not re.search(r"([nx])\1{4,}", doi, re.I):
            found.append(doi)

    seen = {}
    for identifier in found:
        seen.setdefault(identifier.lower(), identifier)

    return list(seen.values())


@dataclass
class Reference:
    """One entry and everything that follows from it."""

    item: dict  # the normalised CSL item
    bibtex: str  # the formatted entry
    directory: str  # which of the library's directories it belongs in
    bibkey: str  # how the entry is cited


def resolve(identifier: str) -> Reference | None:
    """An identifier that resolves is an identifier that exists, so this doubles
    as the check that we read the right one off the pdf."""
    for source in SOURCES:
        matched = source.matches(identifier)
        if matched is None:
            continue

        item = source().fetch(matched)
        if not item:
            return None

        key = bibkey(item)
        return Reference(item, to_bibtex(item, key), source.directory, key)

    return None


def choose(candidates: list[str], name: str, force: bool) -> str:
    if not candidates:
        return input("Please enter the identifier: ").strip()

    if len(candidates) == 1:
        print(f"bs: {name} says {candidates[0]}")
        return candidates[0]

    print(f"bs: {name} mentions several identifiers:")
    for number, candidate in enumerate(candidates, 1):
        print(f"  {number}. {candidate}")

    if force:
        return candidates[0]

    answer = input("Please choose one, or enter another identifier: ").strip()
    if answer.isdigit() and 1 <= int(answer) <= len(candidates):
        return candidates[int(answer) - 1]
    return answer


def identify(pdf: str, library: "Library") -> Reference:
    """Read the identifier off the pdf, so it cannot be paired with the wrong
    entry in the first place, then show what it resolved to for confirmation."""
    if not os.path.isfile(pdf):
        print(f"bs: {pdf} does not exist.")
        exit(1)

    candidates = scan_identifiers(read_pdf(pdf))
    if not candidates:
        print(f"bs: found no doi or arxiv id in {os.path.basename(pdf)}")

    while True:
        identifier = choose(candidates, os.path.basename(pdf), library.force)
        if not identifier:
            print("bs: no identifier given")
            exit(1)

        reference = resolve(identifier)
        if not reference:
            # it did not resolve, so it was not the identifier we wanted
            if library.force:
                exit(1)
            candidates = [entry for entry in candidates if entry != identifier]
            continue

        if library.force:
            return reference

        print(f"\n{reference.bibtex}\n")
        if input("bs: does this match the pdf? [Y/n]: ").strip().lower() in (
            "",
            "y",
            "yes",
        ):
            return reference

        candidates = [entry for entry in candidates if entry != identifier]


def normalise_isbn(identifier: str) -> str | None:
    """Return the bare digits if the identifier is an ISBN, otherwise None. A
    typo that survives the shape check is caught by the checksum."""
    candidate = re.sub(r"[\s-]", "", identifier).upper()

    if re.fullmatch(r"\d{9}[\dX]", candidate):
        total = sum(
            (10 - position) * (10 if digit == "X" else int(digit))
            for position, digit in enumerate(candidate)
        )
        valid = total % 11 == 0
    elif re.fullmatch(r"\d{13}", candidate):
        total = sum(
            (3 if position % 2 else 1) * int(digit)
            for position, digit in enumerate(candidate)
        )
        valid = total % 10 == 0
    else:
        return None

    if not valid:
        print(f"bs: {identifier} looks like an ISBN but the checksum fails")
        exit(1)

    return candidate


class Source(ABC):
    """Somewhere an identifier can be looked up. Add one by writing a subclass
    and putting it in SOURCES."""

    directory: str  # which of the library's directories its pdfs belong in

    @staticmethod
    @abstractmethod
    def matches(identifier: str) -> str | None:
        """The identifier in this source's own terms, or None if it is not ours."""

    @abstractmethod
    def fetch(self, identifier: str) -> dict | None:
        """Look the identifier up and return a CSL item."""


class Isbn(Source):
    directory = "books"

    matches = staticmethod(normalise_isbn)

    def fetch(self, isbn: str) -> dict | None:
        return csl_from_isbn(isbn)


class Doi(Source):
    directory = "files"

    @staticmethod
    def matches(identifier: str) -> str | None:
        # anything that is not an ISBN is treated as a doi or an arxiv id
        return identifier

    def fetch(self, identifier: str) -> dict | None:
        return csl_from_doi(identifier)


# order matters: an ISBN would otherwise be mistaken for an arxiv id
SOURCES = (Isbn, Doi)


def csl_from_doi(identifier: str) -> dict | None:
    """Every paper resolves through doi.org, which content negotiates CSL JSON
    for Crossref and Datacite alike. Arxiv ids get the doi arxiv minted them."""
    doi = identifier if re.search(DOI, identifier) else f"10.48550/arXiv.{identifier}"

    record = fetch(
        f"https://doi.org/{doi}",
        {"Accept": "application/vnd.citationstyles.csl+json"},
    )
    if not record:
        return None

    item = {"id": doi}
    for field, value in record.items():
        # crossref returns a few of these wrapped in a list of one
        if field in CSL_STRINGS and isinstance(value, list):
            value = value[0] if value else ""
        if field in CSL_STRINGS | CSL_NAMES | CSL_DATES and value:
            item[field] = value

    item["type"] = CSL_TYPES.get(record.get("type"), record.get("type", "document"))
    return item


def csl_from_isbn(isbn: str) -> dict | None:
    """Books have no doi to resolve, so assemble the item from Open Library."""
    records = fetch(
        "https://openlibrary.org/api/books"
        f"?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
    )
    if records is None:
        return None
    if not records:
        print(f"bs: Open Library has no record for ISBN {isbn}")
        return None

    book = next(iter(records.values()))

    title = book.get("title", "")
    if subtitle := book.get("subtitle"):
        title = f"{title}: {subtitle}"

    item = {
        "id": f"isbn{isbn}",
        "type": "book",
        "title": title,
        "ISBN": isbn,
        "author": [
            split_name(author["name"])
            for author in book.get("authors", [])
            if author.get("name")
        ],
        "publisher": ", ".join(
            publisher["name"]
            for publisher in book.get("publishers", [])
            if publisher.get("name")
        ),
        "URL": book.get("url", ""),
    }

    # publish_date is free text: "2018", "Oct 15, 2019", "3 January 2017"
    if published := re.search(r"\b(\d{4})\b", book.get("publish_date", "")):
        item["issued"] = {"date-parts": [[int(published.group(1))]]}

    return {field: value for field, value in item.items() if value}


def split_name(name: str) -> dict[str, str]:
    """Open Library hands back "Aurélien Géron", CSL wants the parts named."""
    words = name.split()
    if len(words) < 2:
        return {"literal": name}

    start = len(words) - 1
    while start > 0 and words[start - 1].lower() in PARTICLES:
        start -= 1

    return {"given": " ".join(words[:start]), "family": " ".join(words[start:])}


def bibkey(item: dict) -> str:
    """Surname, year and the first word of the title that carries any meaning."""
    authors = item.get("author", [])
    surname = ""
    if authors:
        surname = authors[0].get("family") or authors[0].get("literal", "")

    parts = item.get("issued", {}).get("date-parts", [[]])[0]
    year = str(parts[0]) if parts else ""

    word = ""
    for candidate in item.get("title", "").split():
        # only the articles are skipped; "We Have No Idea" keys on "we"
        if sanitise_bibkey(candidate).lower() not in ("", "a", "an", "the"):
            word = candidate
            break

    return sanitise_bibkey(f"{surname}{year}{word}").lower()


def sanitise_bibkey(key: str) -> str:
    """Latex tolerates a modest character set in a key, so keep to letters,
    digits and the hyphen that holds a compound title word together."""
    candidate = re.sub(r"[^A-Za-z0-9-]", "", deaccent(key)).strip("-")

    # a key of nothing but digits is no use, so hand those to ascii_bibkey to
    # ask about along with anything else we could not salvage
    return candidate if re.search(r"[A-Za-z]", candidate) else key


def to_bibtex(item: dict, key: str | None = None) -> str:
    """Render a CSL item as a bibtex entry."""
    kind = BIBTEX_TYPES.get(item.get("type", ""), "misc")
    fields = {}

    for csl, field in BIBTEX_FIELDS.items():
        if value := item.get(csl):
            fields[field] = str(value) if field in VERBATIM else escape(str(value))

    if container := item.get("container-title"):
        fields[CONTAINERS.get(kind, "howpublished")] = escape(container)

    for csl, field in (("author", "author"), ("editor", "editor")):
        if names := item.get(csl):
            fields[field] = " and ".join(escape(name) for name in map(bibtex_name, names))

    parts = item.get("issued", {}).get("date-parts", [[]])[0]
    if parts:
        fields["year"] = str(parts[0])
    if len(parts) > 1 and 1 <= parts[1] <= 12:
        fields["month"] = MONTHS[parts[1] - 1]

    if pages := fields.get("pages"):
        # a bibtex page range is held together by a double hyphen
        fields["pages"] = re.sub(r"\s*[-–—]+\s*", "--", pages)

    rank = {field: position for position, field in enumerate(FIELD_ORDER)}
    body = "".join(
        f"  {field} = {{{fields[field]}}},\n"
        for field in sorted(fields, key=lambda field: rank.get(field, len(rank)))
    )

    return f"@{kind}{{{key or bibkey(item)},\n{body}}}"


def bibtex_name(name: dict) -> str:
    """CSL keeps the parts of a name apart; bibtex wants "Family, Given"."""
    if family := name.get("family"):
        given = name.get("given", "")
        return f"{family}, {given}".rstrip(", ")

    # braces stop bibtex reading an organisation as a personal name
    return f"{{{name.get('literal', '')}}}"


def escape(value: str) -> str:
    """Protect the characters latex would otherwise read as markup."""
    for char in "&%$#_":
        value = value.replace(char, f"\\{char}")
    return value


def deaccent(text: str) -> str:
    """"Géron" -> "Geron". Accents belong in the author field of the bib entry,
    not in the filename or the bibkey."""
    text = text.translate(STROKES)
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )


def ascii_bibkey(reference: Reference, force: bool) -> Reference:
    """A key sanitising cannot rescue, a CJK surname say, has to be asked about:
    latex chokes on anything outside ascii."""
    if reference.bibkey.isascii():
        return reference

    # strip the accents off the offending characters for a starting suggestion
    suggestion = "".join(char for char in deaccent(reference.bibkey) if char.isascii())

    print(f"bs: the bibkey {reference.bibkey} contains unicode characters")
    if force:
        key = suggestion
        print(f"bs: using {key}")
    else:
        print("bs: Here is the bib entry for reference:")
        print(f"{reference.bibtex}")
        key = input(f"Please enter a bibkey [{suggestion}]: ").strip() or suggestion

    if not key.isascii():
        print("bs: that bibkey still contains unicode characters")
        exit(1)

    rebuilt = Reference(
        reference.item, to_bibtex(reference.item, key), reference.directory, key
    )

    print("bs: Here is the updated bib entry for reference:")
    print(f"{rebuilt.bibtex}")

    return rebuilt


def clipboards() -> tuple[list[str], ...]:
    """The clipboard is out of the standard library's reach. tkinter comes
    closest, but under X11 the clipboard belongs to the process that set it and
    empties the moment a command like this one exits, so shell out instead. The
    first of these that is installed wins; wayland and x11 are both offered
    because a session may run either, or xwayland on top of wayland."""
    if sys.platform == "darwin":
        return (["pbcopy"],)
    if sys.platform == "win32":
        return (["clip"],)
    return (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
        ["clip.exe"],  # wsl, where the windows clipboard is the real one
    )


def to_clipboard(text: str) -> bool:
    """False if nothing on this machine could take it, so the caller can fall
    back to printing rather than swallowing the entry."""
    for command in clipboards():
        try:
            subprocess.run(command, input=text, text=True, check=True)
            return True
        except (OSError, subprocess.SubprocessError):
            continue

    print(f"bs: no clipboard command found (tried {', '.join(c[0] for c in clipboards())})")
    return False


def first_creator(authors: list[dict]) -> str:
    """Render the author segment the way the files in the library do."""
    surnames = [
        author.get("family") or author.get("literal", "") for author in authors
    ]
    surnames = [name for name in surnames if name]

    match len(surnames):
        case 0:
            return ""
        case 1:
            return surnames[0]
        case 2:
            return f"{surnames[0]} and {surnames[1]}"
        case _:
            return f"{surnames[0]} et al"


def clean(value: str) -> str:
    value = html.unescape(value)
    value = deaccent(value)
    value = value.replace("{", "").replace("}", "")  # bibtex case protection
    value = re.sub(r"\\([&%$#_])", r"\1", value)  # escaped punctuation
    value = value.translate(ILLEGAL)
    return " ".join(value.split()).strip(" .")


def truncate(name: str) -> str:
    encoded = name.encode("utf-8")
    if len(encoded) <= MAX_FILENAME_BYTES:
        return name
    return encoded[:MAX_FILENAME_BYTES].decode("utf-8", errors="ignore").rstrip(" .")


def library_root(argument: str | None = None) -> str:
    """--library, then $BIBSHELF_LIBRARY, then the default. The environment
    variable is expanded too: it is likely to be written with a ~ in it."""
    root = argument or os.environ.get(LIBRARY_VARIABLE) or DEFAULT_LIBRARY
    return os.path.expanduser(root.strip())


class Library:
    """The directories the pdfs live in, and the rules for naming them."""

    def __init__(self, root: str, force: bool = False):
        self.root = root
        self.force = force

    def path(self, reference: "Reference") -> str:
        return os.path.join(self.root, reference.directory)

    def filename(self, reference: "Reference") -> str:
        """[first creator] - [year] - [title], skipping whatever is missing."""
        item = reference.item

        title = clean(item.get("title", ""))
        if not title:
            print("bs: the bib entry has no title, cannot name the file")
            exit(1)

        parts = item.get("issued", {}).get("date-parts", [[]])[0]
        segments = [
            clean(first_creator(item.get("author", []))),
            str(parts[0]) if parts else "",
        ]
        segments = [segment for segment in segments if segment]
        segments.append(title)

        return truncate(" - ".join(segments))

    def archive(self, pdf: str, reference: "Reference") -> str:
        if not os.path.isfile(pdf):
            print(f"bs: {pdf} does not exist.")
            exit(1)

        with open(pdf, "rb") as f:
            if f.read(5) != b"%PDF-":
                print(f"bs: {pdf} is not a pdf.")
                exit(1)

        directory = self.path(reference)
        if not os.path.isdir(directory):
            print(f"bs: {directory} does not exist.")
            exit(1)

        reference = ascii_bibkey(reference, self.force)
        stem = os.path.join(directory, self.filename(reference))
        destination, sidecar = f"{stem}.pdf", f"{stem}.bib"

        for path in (destination, sidecar):
            if os.path.exists(path) and not os.path.samefile(path, pdf):
                print(f"bs: {path} already exists.")
                exit(1)

        if not self.force:
            print(f"bs: {pdf} --> {destination}")
            if input("bs: proceed? [y/N]: ").strip().lower() not in ("y", "yes"):
                print("bs: aborted by user.")
                exit(0)

        shutil.move(pdf, destination)
        with open(sidecar, "w") as f:
            f.write(f"{reference.bibtex}\n")

        print(f"bs: {destination} successfully created.")
        print(f"bs: {sidecar} successfully created.")

        return reference.bibkey


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bs",
        description="Shelve a paper or a book: fetch its bibtex, file its pdf.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"bs {__version__}",
    )
    parser.add_argument(
        "identifier",
        nargs="?",
        help="DOI or Arxiv ID of a paper, ISBN of a book. Omit it to read the "
        "identifier off the pdf itself",
    )
    parser.add_argument(
        "-p",
        "--pdf",
        help="Move the pdf into the library, under files (or books for an "
        "ISBN), named after the bib entry, and write the bib entry beside it",
    )
    parser.add_argument(
        "-l",
        "--library",
        help="Where the library lives. Defaults to "
        f"${LIBRARY_VARIABLE} if it is set, otherwise {DEFAULT_LIBRARY}",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        default=False,
        help="Don't ask for confirmation before moving the pdf",
    )
    parser.add_argument(
        "-x",
        "--to-clipboard",
        action="store_true",
        default=False,
        help="Save to clipboard",
    )
    args = parser.parse_args()

    library = Library(library_root(args.library), args.force)

    if args.identifier:
        reference = resolve(args.identifier)
        not reference and exit(1)
    elif args.pdf:
        reference = identify(args.pdf, library)
    else:
        parser.error("give an identifier, or a pdf to read one from")

    bibkey = None
    if args.pdf:
        bibkey = library.archive(args.pdf, reference)

    if args.to_clipboard:
        to_clipboard(reference.bibtex) or print(reference.bibtex)
    elif bibkey:
        # bib2key expects the bibkey on the clipboard
        to_clipboard(bibkey) or print(bibkey)
    else:
        print(reference.bibtex)


if __name__ == "__main__":
    main()
