import json
import pathlib

import pytest

import bibshelf

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def bs():
    """The module under test, named after the command it installs as."""
    return bibshelf


@pytest.fixture
def recorded():
    """The raw api responses, so the normalising code is what gets tested."""

    def load(name):
        return json.loads((FIXTURES / f"{name}.json").read_text())

    return load


@pytest.fixture
def offline(bs, monkeypatch, recorded):
    """Serve recorded responses instead of reaching for the network."""
    responses = {
        "10.1109/cain58948.2023.00034": recorded("doi-crossref"),
        "10.48550/arxiv.2211.09545": recorded("doi-arxiv"),
        "10.1145/3411764.3445518": recorded("doi-quoted"),
        "9781492032649": recorded("isbn-subtitle"),
        "9780262035613": recorded("isbn-plain"),
    }

    def fake_fetch(url, headers=None):
        for key, response in responses.items():
            if key in url.lower():
                return response
        return None

    monkeypatch.setattr(bs, "fetch", fake_fetch)
    return responses


@pytest.fixture
def make_library(bs, tmp_path):
    """A throwaway library. Before Library existed this had to monkeypatch the
    module's PAPERS and BOOKS constants."""

    def make(force=True):
        (tmp_path / "files").mkdir(exist_ok=True)
        (tmp_path / "books").mkdir(exist_ok=True)
        return bs.Library(str(tmp_path), force=force)

    return make


@pytest.fixture
def library(make_library):
    return make_library(force=True)


@pytest.fixture
def asking(make_library):
    """A library that stops to ask, for exercising the prompts."""
    return make_library(force=False)


@pytest.fixture
def answers(monkeypatch):
    """Queue up replies to input(). Asking for more than were queued is a
    failure, so a test cannot silently drift into the wrong prompt."""

    def feed(*replies):
        queue = list(replies)

        def fake_input(prompt=""):
            if not queue:
                raise AssertionError(f"unexpected prompt: {prompt!r}")
            return queue.pop(0)

        monkeypatch.setattr("builtins.input", fake_input)
        return queue

    return feed


@pytest.fixture
def pdf_says(bs, monkeypatch):
    """Stub out pdftotext with the text a pdf would have yielded."""

    def stub(text):
        monkeypatch.setattr(bs, "read_pdf", lambda path: text)

    return stub


@pytest.fixture
def pdf(tmp_path):
    """A file that passes the %PDF- magic byte check."""

    def make(name="paper.pdf"):
        path = tmp_path / name
        path.write_bytes(b"%PDF-1.4\n% not a real pdf\n")
        return str(path)

    return make
