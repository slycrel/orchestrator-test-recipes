import os
import json
from sqlalchemy import Column, Integer, String, Float, ForeignKey, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship, Session
from sqlalchemy import text

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:////tmp/poe-recipe-site/recipes.db")


class Base(DeclarativeBase):
    pass


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    ingredients = Column(Text, nullable=False)  # JSON-encoded list
    steps = Column(Text, nullable=False)         # JSON-encoded list
    photo_url = Column(String(512), nullable=True)
    tags = Column(String(512), nullable=True)    # comma-separated

    reviews = relationship("Review", back_populates="recipe", cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    rating = Column(Integer, nullable=False)   # 1-5
    text = Column(Text, nullable=True)

    recipe = relationship("Recipe", back_populates="reviews")


def create_db_engine(url: str = DATABASE_URL, *, echo: bool = False):
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args, echo=echo)
    return engine


def init_db(engine=None):
    if engine is None:
        engine = create_db_engine()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        # Standalone FTS5 table — simpler, always consistent
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts
            USING fts5(recipe_id UNINDEXED, name, ingredients, tags)
        """))
        # Triggers to keep FTS in sync
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS recipes_ai AFTER INSERT ON recipes BEGIN
                INSERT INTO recipes_fts(recipe_id, name, ingredients, tags)
                VALUES (new.id, new.name, new.ingredients, COALESCE(new.tags, ''));
            END
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS recipes_ad AFTER DELETE ON recipes BEGIN
                DELETE FROM recipes_fts WHERE recipe_id = old.id;
            END
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS recipes_au AFTER UPDATE ON recipes BEGIN
                DELETE FROM recipes_fts WHERE recipe_id = old.id;
                INSERT INTO recipes_fts(recipe_id, name, ingredients, tags)
                VALUES (new.id, new.name, new.ingredients, COALESCE(new.tags, ''));
            END
        """))
        conn.commit()
    return engine


def get_engine():
    return create_db_engine()


def get_session(engine=None):
    if engine is None:
        engine = get_engine()
    return Session(engine)
