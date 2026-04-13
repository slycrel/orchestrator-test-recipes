"""Test SQLite FTS5 search by ingredient."""
import json
import os
import tempfile
import pytest
from sqlalchemy.orm import Session
from sqlalchemy import text

# Use a dedicated temp DB so this file is isolated from test_api.py
_fts_db = tempfile.NamedTemporaryFile(delete=False, suffix="_fts.db")
_fts_db_path = _fts_db.name
_fts_db.close()

from src.models import Base, Recipe, create_db_engine, init_db


@pytest.fixture(scope="module")
def fts_engine():
    engine = create_db_engine(f"sqlite:///{_fts_db_path}", echo=False)
    Base.metadata.drop_all(engine)
    init_db(engine)
    yield engine
    Base.metadata.drop_all(engine)
    os.unlink(_fts_db_path)


@pytest.fixture()
def fts_db(fts_engine):
    session = Session(fts_engine)
    # Clean slate for each test
    session.query(Recipe).delete()
    session.execute(text("DELETE FROM recipes_fts"))
    session.commit()
    yield session
    session.close()


def _add_recipe(db: Session, name: str, ingredients: list[str], tags: str = "") -> Recipe:
    r = Recipe(
        name=name,
        ingredients=json.dumps(ingredients),
        steps=json.dumps(["step1"]),
        tags=tags,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_fts5_search_by_ingredient(fts_db: Session):
    """Insert 3 recipes; FTS5 search by a unique ingredient returns only the matching recipe."""
    _add_recipe(fts_db, "Pasta Carbonara", ["spaghetti", "eggs", "pancetta", "parmesan"])
    _add_recipe(fts_db, "Chicken Tikka", ["chicken", "yogurt", "garam masala", "tomato"])
    _add_recipe(fts_db, "Avocado Toast", ["avocado", "sourdough bread", "lemon juice", "chili flakes"])

    rows = fts_db.execute(
        text("SELECT recipe_id FROM recipes_fts WHERE recipes_fts MATCH :q ORDER BY rank"),
        {"q": "pancetta"},
    ).fetchall()

    assert len(rows) == 1, f"Expected 1 match for 'pancetta', got {len(rows)}"

    recipe = fts_db.get(Recipe, rows[0][0])
    assert recipe is not None
    assert recipe.name == "Pasta Carbonara"
    assert "pancetta" in json.loads(recipe.ingredients)
