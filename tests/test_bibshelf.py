"""Characterisation tests: these pin down what bibshelf does today, so the
refactor can be judged by whether they all still pass untouched."""

import os

import pytest


# --- pure string helpers ----------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Géron", "Geron"),
        ("Côté", "Cote"),
        ("Kästner", "Kastner"),
        ("Holmström", "Holmstrom"),
        ("Erdős", "Erdos"),
        ("Straße", "Strasse"),
        ("Łukasz", "Lukasz"),
        ("Ægir Ø. Sørensen", "AEgir O. Sorensen"),
        ("機械学習", "機械学習"),  # not an accent, must survive
    ],
)
def test_deaccent(bs, text, expected):
    assert bs.deaccent(text) == expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("“Quoted title”: with subtitle", "Quoted title with subtitle"),
        ('A "straight quoted" title', "A straight quoted title"),
        ("Refactoring: Improving the Design", "Refactoring Improving the Design"),
        ("The Startup Owner's Manual", "The Startup Owner's Manual"),
        ("Scikit-Learn, Keras, and TensorFlow", "Scikit-Learn, Keras, and TensorFlow"),
        ("Foo : spaced colon", "Foo spaced colon"),  # no double space left behind
        ("Trailing colon:", "Trailing colon"),
        ("A {Braced} title", "A Braced title"),
    ],
)
def test_clean(bs, title, expected):
    assert bs.clean(title) == expected


def test_truncate_caps_bytes_not_characters(bs):
    name = bs.truncate("Ä" * 400)
    assert len(name.encode()) <= bs.MAX_FILENAME_BYTES
    assert name.encode().decode() == name  # cut landed on a character boundary


def test_truncate_leaves_short_names_alone(bs):
    assert bs.truncate("a short name") == "a short name"


@pytest.mark.parametrize(
    "authors,expected",
    [
        ([], ""),
        ([{"family": "Fowler"}], "Fowler"),
        ([{"family": "Aldiabat"}, {"family": "Le Navenec"}], "Aldiabat and Le Navenec"),
        ([{"family": "Nahar"}, {"family": "Zhang"}, {"family": "Lewis"}], "Nahar et al"),
        ([{"literal": "Promovendi Netwerk"}], "Promovendi Netwerk"),
    ],
)
def test_first_creator(bs, authors, expected):
    assert bs.first_creator(authors) == expected


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Aurélien Géron", {"given": "Aurélien", "family": "Géron"}),
        ("Carole-Lynne Le Navenec", {"given": "Carole-Lynne", "family": "Le Navenec"}),
        ("Jan van der Meer", {"given": "Jan", "family": "van der Meer"}),
        ("Plato", {"literal": "Plato"}),
    ],
)
def test_split_name(bs, name, expected):
    assert bs.split_name(name) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9780262035613", "9780262035613"),
        ("978-0-262-03561-3", "9780262035613"),
        ("0262035618", "0262035618"),
        ("0-262-03561-8", "0262035618"),
        ("10.1109/CAIN58948.2023.00034", None),
        ("2211.09545", None),
        ("math/0309136", None),
    ],
)
def test_normalise_isbn(bs, raw, expected):
    assert bs.normalise_isbn(raw) == expected


def test_normalise_isbn_rejects_a_bad_checksum(bs):
    with pytest.raises(SystemExit) as exit:
        bs.normalise_isbn("9780262035614")
    assert exit.value.code == 1


@pytest.mark.parametrize(
    "bibkey,expected",
    [
        ("sambasivan2021“everyone", "sambasivan2021everyone"),
        ('smith2020"smart', "smith2020smart"),
        ("o'brien2022shades", "obrien2022shades"),
        ("côté2024quality", "cote2024quality"),
        ("nahar2023meta-summary", "nahar2023meta-summary"),  # hyphen survives
        ("-lead-trail-", "lead-trail"),
        ("王2021研究", "王2021研究"),  # digits only, so left for ascii_bibkey
    ],
)
def test_sanitise_bibkey(bs, bibkey, expected):
    assert bs.sanitise_bibkey(bibkey) == expected


# --- identifier scanning ----------------------------------------------------


def test_scan_finds_a_doi(bs):
    text = "published in ACM, doi 10.1145/3290605.3300500, see also"
    assert bs.scan_identifiers(text) == ["10.1145/3290605.3300500"]


def test_scan_finds_new_and_old_style_arxiv_ids(bs):
    assert bs.scan_identifiers("arXiv:2211.09545v1 [cs.LG]") == ["2211.09545"]
    assert bs.scan_identifiers("arXiv:math/0309136v2") == ["math/0309136"]


def test_scan_puts_arxiv_ids_before_dois(bs):
    text = "10.1145/3290605 ... arXiv:2211.09545v1"
    assert bs.scan_identifiers(text)[0] == "2211.09545"


def test_scan_drops_unfilled_latex_placeholders(bs):
    assert bs.scan_identifiers("doi 10.1145/nnnnnnn.nnnnnnn") == []


def test_scan_deduplicates(bs):
    text = "10.1145/3290605 and again 10.1145/3290605"
    assert bs.scan_identifiers(text) == ["10.1145/3290605"]


def test_scan_returns_nothing_for_a_scanned_pdf(bs):
    assert bs.scan_identifiers("") == []


# --- csl normalising --------------------------------------------------------


def test_doi_source_maps_crossref_types_to_csl(bs, offline):
    item = bs.Doi().fetch("10.1109/CAIN58948.2023.00034")
    assert item["type"] == "paper-conference"  # crossref said proceedings-article


def test_doi_source_drops_non_csl_bulk(bs, offline, recorded):
    raw = recorded("doi-crossref")
    item = bs.Doi().fetch("10.1109/CAIN58948.2023.00034")
    assert "reference" in raw and "reference" not in item
    assert "license" in raw and "license" not in item
    # the empty arrays that make pandoc's csljson reader give up
    assert not any(value == [] for value in item.values())


def test_doi_source_keeps_what_the_entry_needs(bs, offline):
    item = bs.Doi().fetch("10.1109/CAIN58948.2023.00034")
    assert item["title"].startswith("A Meta-Summary")
    assert item["author"][0]["family"] == "Nahar"
    assert item["issued"]["date-parts"][0][0] == 2023
    assert item["id"] == "10.1109/CAIN58948.2023.00034"


def test_doi_source_turns_a_bare_arxiv_id_into_a_doi(bs, offline):
    item = bs.Doi().fetch("2211.09545")
    assert item["id"] == "10.48550/arXiv.2211.09545"
    assert item["author"][0]["family"] == "Dharmadhikari"


def test_isbn_source_joins_the_subtitle(bs, offline):
    item = bs.Isbn().fetch("9781492032649")
    assert item["title"] == (
        "Hands-On Machine Learning with Scikit-Learn, Keras, and TensorFlow: "
        "Concepts, Tools, and Techniques to Build Intelligent Systems"
    )


def test_isbn_source_pulls_the_year_out_of_free_text(bs, offline):
    # open library dates look like "2018", "Oct 15, 2019", "3 January 2017"
    item = bs.Isbn().fetch("9780262035613")
    assert item["issued"]["date-parts"] == [[2017]]
    assert item["type"] == "book"
    assert item["ISBN"] == "9780262035613"


def test_isbn_source_splits_flat_names(bs, offline):
    item = bs.Isbn().fetch("9781492032649")
    assert item["author"][0] == {"given": "Aurélien", "family": "Géron"}


# --- source dispatch --------------------------------------------------------


def test_isbn_is_matched_before_doi(bs):
    """Otherwise an ISBN would be taken for an arxiv id."""
    assert bs.SOURCES == (bs.Isbn, bs.Doi)
    assert bs.Isbn.matches("9780262035613") == "9780262035613"
    assert bs.Isbn.matches("10.1145/3290605") is None
    assert bs.Doi.matches("10.1145/3290605") == "10.1145/3290605"


def test_resolve_routes_a_book_to_books(bs, offline):
    assert bs.resolve("9780262035613").directory == "books"


def test_resolve_routes_a_paper_to_files(bs, offline):
    assert bs.resolve("10.1109/CAIN58948.2023.00034").directory == "files"


def test_resolve_gives_back_a_reference(bs, offline):
    reference = bs.resolve("2211.09545")
    assert isinstance(reference, bs.Reference)
    assert reference.bibtex.startswith("@misc")
    assert reference.bibkey == "dharmadhikari2022reinforcement"
    assert reference.item["author"][0]["family"] == "Dharmadhikari"


# --- bibtex generation (really shells out to pandoc and bibtool) ------------


def test_to_bibtex_deaccents_the_key_but_not_the_author(bs, offline):
    bibtex = bs.to_bibtex(bs.Isbn().fetch("9781492032649"))
    assert "geron2019hands-on" in bibtex
    assert "Géron" in bibtex


def test_to_bibtex_puts_back_the_isbn_pandoc_drops(bs, offline):
    bibtex = bs.to_bibtex(bs.Isbn().fetch("9780262035613"))
    assert "9780262035613" in bibtex


def test_to_bibtex_keeps_the_entry_type(bs, offline):
    bibtex = bs.to_bibtex(bs.Doi().fetch("10.1109/CAIN58948.2023.00034"))
    assert bibtex.startswith("@inproceedings")
    assert "booktitle" in bibtex


def test_to_bibtex_strips_quotes_from_the_key(bs, offline):
    bibtex = bs.to_bibtex(bs.Doi().fetch("10.1145/3411764.3445518"))
    assert "sambasivan2021everyone" in bibtex


@pytest.mark.parametrize(
    "identifier,expected",
    [
        # the keys bibtool used to generate, pinned so the replacement matches
        ("10.1109/CAIN58948.2023.00034", "nahar2023meta-summary"),
        ("2211.09545", "dharmadhikari2022reinforcement"),
        ("10.1145/3411764.3445518", "sambasivan2021everyone"),
        ("9780262035613", "goodfellow2017deep"),
        ("9781492032649", "geron2019hands-on"),
    ],
)
def test_bibkey_matches_what_bibtool_produced(bs, offline, identifier, expected):
    assert bs.resolve(identifier).bibkey == expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("A Meta-Summary of Challenges", "meta-summary"),  # articles are skipped
        ("The Large N Limit", "large"),
        ("We Have No Idea How Models", "we"),  # "we" is not a stopword
        ("Hands-On Machine Learning", "hands-on"),  # compounds keep their hyphen
        ("Refactoring: Improving the Design", "refactoring"),
        ("“Everyone wants to do the work”", "everyone"),
    ],
)
def test_bibkey_picks_the_first_meaningful_title_word(bs, title, expected):
    item = {"title": title, "author": [{"family": "Doe"}]}
    assert bs.bibkey(item) == f"doe{expected}"


def test_to_bibtex_leaves_a_straight_apostrophe_alone(bs, offline):
    """pandoc turned O'Reilly into O’Reilly and could not be told not to."""
    assert "O'Reilly Media" in bs.to_bibtex(bs.Isbn().fetch("9781492032649"))


def test_to_bibtex_writes_a_bibtex_page_range(bs, offline):
    bibtex = bs.to_bibtex(bs.Doi().fetch("10.1109/CAIN58948.2023.00034"))
    assert "pages = {171--183}" in bibtex


def test_to_bibtex_does_not_escape_the_url(bs, offline):
    """Escaping the underscores would break \\url{}."""
    bibtex = bs.to_bibtex(bs.Isbn().fetch("9781492032649"))
    assert "Hands-On_Machine_Learning" in bibtex


def test_to_bibtex_escapes_latex_specials(bs):
    item = {"title": "Tools & Techniques for R&D at 50% cost", "author": []}
    assert r"Tools \& Techniques for R\&D at 50\% cost" in bs.to_bibtex(item)


def test_to_bibtex_braces_an_organisation(bs):
    item = {"title": "A Report", "author": [{"literal": "Promovendi Netwerk Nederland"}]}
    assert "author = {{Promovendi Netwerk Nederland}}" in bs.to_bibtex(item)


# --- filenames --------------------------------------------------------------


def reference(bs, title="A title", authors=None, year=2020):
    item = {"title": title, "author": authors if authors is not None else []}
    if year:
        item["issued"] = {"date-parts": [[year]]}
    key = bs.bibkey(item)
    return bs.Reference(item, bs.to_bibtex(item, key), "files", key)


def test_filename(bs, library):
    assert library.filename(
        reference(
            bs,
            "Deep Learning",
            [{"family": "Goodfellow"}, {"family": "Bengio"}, {"family": "Courville"}],
            2017,
        )
    ) == "Goodfellow et al - 2017 - Deep Learning"


def test_filename_drops_a_missing_year(bs, library):
    assert library.filename(
        reference(bs, "Fairness and Machine Learning", [{"family": "Barocas"}], None)
    ) == "Barocas - Fairness and Machine Learning"


def test_filename_drops_a_missing_author(bs, library):
    assert library.filename(reference(bs, "Anonymous report", [], 2020)) == (
        "2020 - Anonymous report"
    )


def test_filename_needs_a_title(bs, library):
    with pytest.raises(SystemExit) as exit:
        library.filename(reference(bs, "", [{"family": "Doe"}]))
    assert exit.value.code == 1


def test_filename_strips_accents_quotes_and_colons(bs, offline, library):
    name = library.filename(bs.resolve("10.1145/3411764.3445518"))
    assert name == (
        "Sambasivan et al - 2021 - Everyone wants to do the model work, "
        "not the data work Data Cascades in High-Stakes AI"
    )


# --- choosing between candidates --------------------------------------------

CROSSREF = "10.1109/CAIN58948.2023.00034"
QUOTED = "10.1145/3411764.3445518"


def test_choose_asks_when_the_pdf_yielded_nothing(bs, answers):
    queue = answers("10.1145/3290605")
    assert bs.choose([], "paper.pdf", False) == "10.1145/3290605"
    assert queue == []


def test_choose_does_not_ask_about_a_lone_candidate(bs, answers):
    answers()  # any prompt at all would fail the test
    assert bs.choose([CROSSREF], "paper.pdf", False) == CROSSREF


def test_choose_takes_a_number(bs, answers):
    answers("2")
    assert bs.choose([CROSSREF, QUOTED], "paper.pdf", False) == QUOTED


def test_choose_takes_a_typed_identifier_instead(bs, answers):
    answers("2211.09545")
    assert bs.choose([CROSSREF, QUOTED], "paper.pdf", False) == "2211.09545"


def test_choose_treats_an_out_of_range_number_as_typed_input(bs, answers):
    answers("9")
    assert bs.choose([CROSSREF, QUOTED], "paper.pdf", False) == "9"


def test_choose_takes_the_first_when_forced(bs, answers):
    answers()
    assert bs.choose([CROSSREF, QUOTED], "paper.pdf", True) == CROSSREF


# --- reading the identifier off the pdf --------------------------------------


def test_identify_confirms_what_it_resolved(bs, offline, asking, answers, pdf, pdf_says):
    pdf_says(f"see doi {CROSSREF} for details")
    queue = answers("")  # empty accepts

    reference = bs.identify(pdf(), asking)

    assert reference.item["author"][0]["family"] == "Nahar"
    assert queue == []


def test_identify_offers_the_others_when_one_is_rejected(
    bs, offline, asking, answers, pdf, pdf_says
):
    """The Head et al. case: a paper carrying both its own doi and its
    proceedings' doi, where the wrong pick files it under the wrong title."""
    pdf_says(f"{CROSSREF} and also {QUOTED}")
    queue = answers("2", "n", "")  # pick the second, reject it, accept the other

    reference = bs.identify(pdf(), asking)

    assert reference.item["author"][0]["family"] == "Nahar"  # the one left
    assert queue == []


def test_identify_falls_back_to_asking_when_all_are_rejected(
    bs, offline, asking, answers, pdf, pdf_says
):
    pdf_says(f"doi {QUOTED}")
    queue = answers("n", CROSSREF, "")  # reject, type another, accept it

    reference = bs.identify(pdf(), asking)

    assert reference.item["author"][0]["family"] == "Nahar"
    assert queue == []


def test_identify_asks_again_when_an_identifier_does_not_resolve(
    bs, offline, asking, answers, pdf, pdf_says
):
    pdf_says("")  # a scanned pdf yields nothing
    queue = answers("10.9999/bogus", CROSSREF, "")

    reference = bs.identify(pdf(), asking)

    assert reference.item["author"][0]["family"] == "Nahar"
    assert queue == []


def test_identify_gives_up_on_an_empty_answer(bs, offline, asking, answers, pdf, pdf_says):
    pdf_says("")
    answers("")
    with pytest.raises(SystemExit) as exit:
        bs.identify(pdf(), asking)
    assert exit.value.code == 1


def test_identify_asks_nothing_when_forced(bs, offline, library, answers, pdf, pdf_says):
    pdf_says(f"doi {CROSSREF}")
    answers()  # a prompt would fail the test

    assert bs.identify(pdf(), library).item["author"][0]["family"] == "Nahar"


def test_identify_refuses_to_guess_when_forced_and_nothing_resolves(
    bs, offline, library, answers, pdf, pdf_says
):
    pdf_says("doi 10.9999/bogus")
    answers()
    with pytest.raises(SystemExit) as exit:
        bs.identify(pdf(), library)
    assert exit.value.code == 1


def test_identify_rejects_a_missing_pdf(bs, offline, asking, tmp_path):
    with pytest.raises(SystemExit) as exit:
        bs.identify(str(tmp_path / "nope.pdf"), asking)
    assert exit.value.code == 1


# --- bibkeys latex can stomach ----------------------------------------------


def keyed(bs, key):
    """A reference carrying a key sanitising could not rescue."""
    item = {
        "title": "A Title",
        "author": [{"family": "Doe"}],
        "issued": {"date-parts": [[2020]]},
    }
    return bs.Reference(item, bs.to_bibtex(item, key), "files", key)


def test_ascii_bibkey_leaves_an_ascii_key_alone(bs, answers):
    answers()  # any prompt would fail the test
    reference = keyed(bs, "fowler2018refactoring")
    assert bs.ascii_bibkey(reference, False) is reference


def test_ascii_bibkey_transliterates_when_forced(bs, answers):
    answers()
    rebuilt = bs.ascii_bibkey(keyed(bs, "géron2019hands"), True)
    assert rebuilt.bibkey == "geron2019hands"
    assert "géron" not in rebuilt.bibtex


def test_ascii_bibkey_suggests_a_replacement(bs, answers):
    answers("")  # empty accepts the suggestion
    rebuilt = bs.ascii_bibkey(keyed(bs, "côté2024quality"), False)
    assert rebuilt.bibkey == "cote2024quality"


def test_ascii_bibkey_takes_a_typed_replacement(bs, answers):
    answers("cote2024")
    rebuilt = bs.ascii_bibkey(keyed(bs, "côté2024quality"), False)
    assert rebuilt.bibkey == "cote2024"
    assert rebuilt.bibtex.startswith("@misc{cote2024,")


def test_ascii_bibkey_rejects_a_replacement_that_is_still_unicode(bs, answers):
    answers("côté")
    with pytest.raises(SystemExit) as exit:
        bs.ascii_bibkey(keyed(bs, "côté2024quality"), False)
    assert exit.value.code == 1


# --- archiving --------------------------------------------------------------


def archive(bs, library, pdf_path, identifier="10.1109/CAIN58948.2023.00034"):
    return library.archive(pdf_path, bs.resolve(identifier))


def papers(library):
    return os.path.join(library.root, "files")


def test_archive_moves_and_renames_the_pdf(bs, offline, library, pdf):
    source = pdf()
    archive(bs, library, source)
    assert not os.path.exists(source)
    assert sorted(os.listdir(papers(library))) == [
        "Nahar et al - 2023 - A Meta-Summary of Challenges in Building Products with ML Components – Collecting Experiences from 4758+ Practitioners.bib",
        "Nahar et al - 2023 - A Meta-Summary of Challenges in Building Products with ML Components – Collecting Experiences from 4758+ Practitioners.pdf",
    ]


def test_archive_returns_the_bibkey(bs, offline, library, pdf):
    assert archive(bs, library, pdf()) == "nahar2023meta-summary"


def test_archive_sends_a_book_to_books(bs, offline, library, pdf):
    archive(bs, library, pdf(), "9780262035613")
    assert sorted(os.listdir(os.path.join(library.root, "books"))) == [
        "Goodfellow et al - 2017 - Deep Learning.bib",
        "Goodfellow et al - 2017 - Deep Learning.pdf",
    ]
    assert os.listdir(papers(library)) == []


def test_archive_refuses_to_overwrite(bs, offline, library, pdf):
    archive(bs, library, pdf("first.pdf"))
    second = pdf("second.pdf")
    with pytest.raises(SystemExit) as exit:
        archive(bs, library, second)
    assert exit.value.code == 1
    assert os.path.exists(second)  # the loser is left where it was


def test_archive_rejects_a_file_that_is_not_a_pdf(bs, offline, library, tmp_path):
    impostor = tmp_path / "fake.pdf"
    impostor.write_text("definitely not a pdf")
    with pytest.raises(SystemExit) as exit:
        archive(bs, library, str(impostor))
    assert exit.value.code == 1
    assert impostor.exists()


def test_archive_rejects_a_missing_file(bs, offline, library, tmp_path):
    with pytest.raises(SystemExit) as exit:
        archive(bs, library, str(tmp_path / "nope.pdf"))
    assert exit.value.code == 1


def test_archive_rejects_a_missing_directory(bs, offline, tmp_path, pdf):
    empty = bs.Library(str(tmp_path / "nowhere"), force=True)
    source = pdf()
    with pytest.raises(SystemExit) as exit:
        archive(bs, empty, source)
    assert exit.value.code == 1
    assert os.path.exists(source)


def test_archive_renames_a_pdf_already_in_the_library(bs, offline, library):
    """The workflow for tidying files that are already filed."""
    stale = os.path.join(papers(library), "Nahar et al. - 2023 - old name.pdf")
    with open(stale, "wb") as f:
        f.write(b"%PDF-1.4\n")

    archive(bs, library, stale)

    assert not os.path.exists(stale)
    assert len(os.listdir(papers(library))) == 2  # renamed pdf plus its sidecar


# --- where the library lives ------------------------------------------------


def test_library_root_defaults_to_the_documented_path(bs, monkeypatch):
    monkeypatch.delenv(bs.LIBRARY_VARIABLE, raising=False)
    assert bs.library_root() == os.path.expanduser(bs.DEFAULT_LIBRARY)


def test_library_root_reads_the_environment(bs, monkeypatch, tmp_path):
    monkeypatch.setenv(bs.LIBRARY_VARIABLE, str(tmp_path))
    assert bs.library_root() == str(tmp_path)


def test_library_root_expands_a_tilde_from_the_environment(bs, monkeypatch):
    """A path written by hand in a shell profile is likely to have one."""
    monkeypatch.setenv(bs.LIBRARY_VARIABLE, "~/papers")
    assert bs.library_root() == os.path.expanduser("~/papers")


def test_library_root_prefers_the_argument(bs, monkeypatch, tmp_path):
    monkeypatch.setenv(bs.LIBRARY_VARIABLE, str(tmp_path / "environment"))
    assert bs.library_root(str(tmp_path / "flag")) == str(tmp_path / "flag")


def test_library_root_ignores_an_empty_environment_variable(bs, monkeypatch):
    monkeypatch.setenv(bs.LIBRARY_VARIABLE, "")
    assert bs.library_root() == os.path.expanduser(bs.DEFAULT_LIBRARY)


# --- clipboard --------------------------------------------------------------


def test_clipboards_offers_pbcopy_on_macos(bs, monkeypatch):
    monkeypatch.setattr(bs.sys, "platform", "darwin")
    assert bs.clipboards() == (["pbcopy"],)


def test_clipboards_offers_several_on_linux(bs, monkeypatch):
    """No single one of these is installed everywhere, hence the list."""
    monkeypatch.setattr(bs.sys, "platform", "linux")
    assert [command[0] for command in bs.clipboards()] == [
        "wl-copy",
        "xclip",
        "xsel",
        "clip.exe",
    ]


def test_to_clipboard_uses_the_first_that_works(bs, monkeypatch):
    monkeypatch.setattr(bs, "clipboards", lambda: (["wl-copy"], ["xclip"]))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["input"]))

    monkeypatch.setattr(bs.subprocess, "run", fake_run)

    assert bs.to_clipboard("hello") is True
    assert calls == [(["wl-copy"], "hello")]


def test_to_clipboard_moves_on_when_one_is_missing(bs, monkeypatch):
    monkeypatch.setattr(bs, "clipboards", lambda: (["wl-copy"], ["xclip"]))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command == ["wl-copy"]:
            raise FileNotFoundError(command)

    monkeypatch.setattr(bs.subprocess, "run", fake_run)

    assert bs.to_clipboard("hello") is True
    assert calls == [["wl-copy"], ["xclip"]]


def test_to_clipboard_moves_on_when_one_fails(bs, monkeypatch):
    """wl-copy is installed but there is no wayland session to copy into."""
    monkeypatch.setattr(bs, "clipboards", lambda: (["wl-copy"], ["xclip"]))

    def fake_run(command, **kwargs):
        if command == ["wl-copy"]:
            raise bs.subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(bs.subprocess, "run", fake_run)

    assert bs.to_clipboard("hello") is True


def test_to_clipboard_reports_when_nothing_can_take_it(bs, monkeypatch, capsys):
    """The caller prints the entry instead, rather than losing it."""
    monkeypatch.setattr(bs, "clipboards", lambda: (["wl-copy"],))

    def fake_run(command, **kwargs):
        raise FileNotFoundError(command)

    monkeypatch.setattr(bs.subprocess, "run", fake_run)

    assert bs.to_clipboard("hello") is False
    assert "no clipboard command found" in capsys.readouterr().out
