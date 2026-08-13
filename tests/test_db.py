from src.cite.db import Db
import pytest
import shutil
from pathlib import Path


@pytest.fixture
def patch_db_store(monkeypatch, tmp_path):
    store = tmp_path / "cite"
    monkeypatch.setattr(Db, "_store", store)
    
    return store


@pytest.fixture
def populate_db(patch_db_store):
    store = patch_db_store
    store.mkdir()
    p = Path.cwd() / "tests/entries"
    for item in p.iterdir():
        shutil.copy(item, store)

    return Db()


def test_db_init(patch_db_store):
    assert Db._store.exists()

    db = Db()
    assert Db._store.exists()
    with pytest.raises(StopIteration):
        next(db.items)


def test_db_init_with_existing_items(populate_db):
    db = populate_db
    count = sum(1 for i in db.items)
    assert count == 1


def test_create_new_item(patch_db_store):
    db = Db()
    old_count = sum(1 for item in db.items)
    assert db.create("item1", "content for item1")
    new_count = sum(1 for item in db.items)
    assert new_count > old_count


def test_create_duplicate_item(patch_db_store):
    db = Db()
    db.create("item1", "content for item1")
    assert not db.create("item1", "content for item1")


@pytest.mark.skip
def test_read_returns_correct_item(populate_db):
    """
    GIVEN an id that exists in the Db
    WHEN the read method is called
    THEN the item is returned
    """
    pass
