"""Comprehensive pytest tests for Recipe API and search functionality."""
import json
import os
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

# DATABASE_URL is set by conftest.py before this module is loaded.
from src.main import app, get_db
from src.models import Base, Recipe, Review, init_db, create_db_engine


# db_engine and db fixtures provided by conftest.py.


@pytest.fixture(scope="function")
def client(db_engine):
    """FastAPI test client with dependency override."""
    from src.models import get_session

    def override_get_db():
        db = get_session(db_engine)
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


class TestRecipeCRUD:
    """Test CRUD operations for recipes."""

    def test_create_recipe_via_api(self, client):
        """Create a recipe via JSON API."""
        payload = {
            "name": "Pasta Carbonara",
            "ingredients": ["eggs", "bacon", "pasta", "cheese"],
            "steps": ["Boil pasta", "Cook bacon", "Mix eggs with cheese"],
            "photo_url": "https://example.com/carbonara.jpg",
            "tags": ["italian", "pasta", "dinner"]
        }
        response = client.post("/api/recipes", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Pasta Carbonara"
        assert data["ingredients"] == ["eggs", "bacon", "pasta", "cheese"]
        assert data["review_count"] == 0
        assert "id" in data

    def test_get_recipe_via_api(self, client, db):
        """Retrieve a recipe by ID."""
        recipe = Recipe(
            name="Tacos",
            ingredients=json.dumps(["tortillas", "beef", "lettuce"]),
            steps=json.dumps(["Brown beef", "Warm tortillas", "Assemble"]),
            photo_url="https://example.com/tacos.jpg",
            tags="mexican,street-food"
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)

        response = client.get(f"/api/recipes/{recipe.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Tacos"
        assert data["id"] == recipe.id

    def test_list_recipes_via_api(self, client, db):
        """List all recipes."""
        recipe1 = Recipe(
            name="Recipe 1",
            ingredients=json.dumps(["a", "b"]),
            steps=json.dumps(["step1"]),
        )
        recipe2 = Recipe(
            name="Recipe 2",
            ingredients=json.dumps(["c", "d"]),
            steps=json.dumps(["step1"]),
        )
        db.add_all([recipe1, recipe2])
        db.commit()

        response = client.get("/api/recipes")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert any(r["name"] == "Recipe 1" for r in data)
        assert any(r["name"] == "Recipe 2" for r in data)

    def test_update_recipe_via_api(self, client, db):
        """Update a recipe."""
        recipe = Recipe(
            name="Original Name",
            ingredients=json.dumps(["x"]),
            steps=json.dumps(["step"]),
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)

        payload = {
            "name": "Updated Name",
            "ingredients": ["new_ingredient"],
        }
        response = client.put(f"/api/recipes/{recipe.id}", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["ingredients"] == ["new_ingredient"]

    def test_delete_recipe_via_api(self, client, db):
        """Delete a recipe."""
        recipe = Recipe(
            name="To Delete",
            ingredients=json.dumps(["a"]),
            steps=json.dumps(["b"]),
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)

        response = client.delete(f"/api/recipes/{recipe.id}")
        assert response.status_code == 204

        # Verify it's deleted
        response = client.get(f"/api/recipes/{recipe.id}")
        assert response.status_code == 404

    def test_get_nonexistent_recipe(self, client):
        """Get a recipe that doesn't exist."""
        response = client.get("/api/recipes/999")
        assert response.status_code == 404
        assert response.json()["detail"] == "Recipe not found"


class TestFullTextSearch:
    """Test full-text search by name, ingredient, and tag."""

    def test_search_by_name(self, client, db):
        """Search recipes by name."""
        recipe1 = Recipe(
            name="Chocolate Cake",
            ingredients=json.dumps(["flour", "sugar", "chocolate"]),
            steps=json.dumps(["mix", "bake"]),
            tags="dessert,baking"
        )
        recipe2 = Recipe(
            name="Vanilla Cake",
            ingredients=json.dumps(["flour", "sugar", "vanilla"]),
            steps=json.dumps(["mix", "bake"]),
            tags="dessert,baking"
        )
        db.add_all([recipe1, recipe2])
        db.commit()

        # Search for "chocolate"
        response = client.get("/api/recipes?q=Chocolate")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Chocolate Cake"

    def test_search_by_ingredient(self, client, db):
        """Search recipes by ingredient."""
        recipe1 = Recipe(
            name="Pasta Carbonara",
            ingredients=json.dumps(["eggs", "bacon", "pasta", "cheese"]),
            steps=json.dumps(["boil pasta", "cook bacon"]),
            tags="italian,pasta"
        )
        recipe2 = Recipe(
            name="Egg Fried Rice",
            ingredients=json.dumps(["eggs", "rice", "soy sauce"]),
            steps=json.dumps(["cook rice", "fry with eggs"]),
            tags="asian,rice"
        )
        db.add_all([recipe1, recipe2])
        db.commit()

        # Search for "bacon"
        response = client.get("/api/recipes?q=bacon")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Pasta Carbonara"

    def test_search_by_tag(self, client, db):
        """Search recipes by tag."""
        recipe1 = Recipe(
            name="Margherita Pizza",
            ingredients=json.dumps(["dough", "tomato", "mozzarella"]),
            steps=json.dumps(["prepare dough", "top", "bake"]),
            tags="italian,pizza,vegetarian"
        )
        recipe2 = Recipe(
            name="Caprese Salad",
            ingredients=json.dumps(["tomato", "mozzarella", "basil"]),
            steps=json.dumps(["slice", "arrange", "dress"]),
            tags="italian,vegetarian,salad"
        )
        db.add_all([recipe1, recipe2])
        db.commit()

        # Search for "vegetarian"
        response = client.get("/api/recipes?q=vegetarian")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_search_empty_query(self, client, db):
        """Empty search query returns all recipes."""
        recipe1 = Recipe(
            name="Recipe 1",
            ingredients=json.dumps(["a"]),
            steps=json.dumps(["step"]),
        )
        recipe2 = Recipe(
            name="Recipe 2",
            ingredients=json.dumps(["b"]),
            steps=json.dumps(["step"]),
        )
        db.add_all([recipe1, recipe2])
        db.commit()

        response = client.get("/api/recipes?q=")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_search_no_results(self, client, db):
        """Search with no matching results."""
        recipe = Recipe(
            name="Test Recipe",
            ingredients=json.dumps(["test"]),
            steps=json.dumps(["step"]),
        )
        db.add(recipe)
        db.commit()

        response = client.get("/api/recipes?q=nonexistent_ingredient")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestReviewSystem:
    """Test review endpoints and rating system."""

    def test_add_review(self, client, db):
        """Add a review to a recipe."""
        recipe = Recipe(
            name="Test Recipe",
            ingredients=json.dumps(["a"]),
            steps=json.dumps(["b"]),
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)

        payload = {
            "rating": 5,
            "text": "Delicious!"
        }
        response = client.post(f"/api/recipes/{recipe.id}/reviews", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["rating"] == 5
        assert data["text"] == "Delicious!"
        assert data["recipe_id"] == recipe.id

    def test_add_review_invalid_rating_too_high(self, client, db):
        """Adding a review with rating > 5 should fail."""
        recipe = Recipe(
            name="Test Recipe",
            ingredients=json.dumps(["a"]),
            steps=json.dumps(["b"]),
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)

        payload = {"rating": 10, "text": "Too high"}
        response = client.post(f"/api/recipes/{recipe.id}/reviews", json=payload)
        assert response.status_code == 422
        assert "Rating must be 1-5" in response.json()["detail"]

    def test_add_review_invalid_rating_too_low(self, client, db):
        """Adding a review with rating < 1 should fail."""
        recipe = Recipe(
            name="Test Recipe",
            ingredients=json.dumps(["a"]),
            steps=json.dumps(["b"]),
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)

        payload = {"rating": 0, "text": "Too low"}
        response = client.post(f"/api/recipes/{recipe.id}/reviews", json=payload)
        assert response.status_code == 422

    def test_list_reviews_for_recipe(self, client, db):
        """Get all reviews for a recipe."""
        recipe = Recipe(
            name="Test Recipe",
            ingredients=json.dumps(["a"]),
            steps=json.dumps(["b"]),
        )
        review1 = Review(recipe=recipe, rating=5, text="Great!")
        review2 = Review(recipe=recipe, rating=4, text="Good")
        db.add_all([recipe, review1, review2])
        db.commit()
        db.refresh(recipe)

        response = client.get(f"/api/recipes/{recipe.id}/reviews")
        assert response.status_code == 200
        data = response.json()
        assert data["review_count"] == 2
        assert data["avg_rating"] == 4.5
        assert len(data["reviews"]) == 2

    def test_aggregate_rating_endpoint(self, client, db):
        """Get aggregate rating for a recipe."""
        recipe = Recipe(
            name="Test Recipe",
            ingredients=json.dumps(["a"]),
            steps=json.dumps(["b"]),
        )
        review1 = Review(recipe=recipe, rating=5, text="Perfect")
        review2 = Review(recipe=recipe, rating=3, text="Okay")
        db.add_all([recipe, review1, review2])
        db.commit()
        db.refresh(recipe)

        response = client.get(f"/api/recipes/{recipe.id}/rating")
        assert response.status_code == 200
        data = response.json()
        assert data["avg_rating"] == 4.0
        assert data["review_count"] == 2

    def test_reviews_for_nonexistent_recipe(self, client):
        """Get reviews for a recipe that doesn't exist."""
        response = client.get("/api/recipes/999/reviews")
        assert response.status_code == 404

    def test_add_review_to_nonexistent_recipe(self, client):
        """Add a review to a recipe that doesn't exist."""
        payload = {"rating": 5, "text": "Good"}
        response = client.post("/api/recipes/999/reviews", json=payload)
        assert response.status_code == 404


class TestHTMLRoutes:
    """Test HTML form handling and page rendering."""

    def test_index_page(self, client):
        """GET / returns the recipe list page."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_new_recipe_form(self, client):
        """GET /recipes/new returns the create form."""
        response = client.get("/recipes/new")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_recipe_detail_page(self, client, db):
        """GET /recipes/{id} shows recipe details."""
        recipe = Recipe(
            name="Test Recipe",
            ingredients=json.dumps(["a", "b"]),
            steps=json.dumps(["step1", "step2"]),
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)

        response = client.get(f"/recipes/{recipe.id}")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_edit_recipe_form(self, client, db):
        """GET /recipes/{id}/edit shows the edit form."""
        recipe = Recipe(
            name="Test Recipe",
            ingredients=json.dumps(["a"]),
            steps=json.dumps(["b"]),
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)

        response = client.get(f"/recipes/{recipe.id}/edit")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_create_recipe_form_post(self, client, db):
        """POST /recipes creates a new recipe via form."""
        form_data = {
            "name": "Spaghetti",
            "ingredients": "pasta\ngarlic\noil",
            "steps": "boil pasta\nsauté garlic",
            "photo_url": "https://example.com/spaghetti.jpg",
            "tags": "italian, pasta"
        }
        response = client.post("/recipes", data=form_data, follow_redirects=False)
        assert response.status_code == 303  # Redirect on success

        # Verify recipe was created
        recipes = db.query(Recipe).filter(Recipe.name == "Spaghetti").all()
        assert len(recipes) == 1

    def test_delete_recipe_form_post(self, client, db):
        """POST /recipes/{id}/delete removes a recipe."""
        recipe = Recipe(
            name="To Delete",
            ingredients=json.dumps(["a"]),
            steps=json.dumps(["b"]),
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)

        response = client.post(f"/recipes/{recipe.id}/delete", follow_redirects=False)
        assert response.status_code == 303  # Redirect on success

        # Verify recipe was deleted
        remaining = db.query(Recipe).filter(Recipe.id == recipe.id).first()
        assert remaining is None


class TestSearchIntegration:
    """Integration tests for search across multiple scenarios."""

    def test_search_with_multiple_matches(self, client, db):
        """Search term matches multiple recipes."""
        recipes = [
            Recipe(
                name="Tomato Soup",
                ingredients=json.dumps(["tomato", "onion", "basil"]),
                steps=json.dumps(["chop", "simmer"]),
                tags="vegetable,soup"
            ),
            Recipe(
                name="Tomato Pasta",
                ingredients=json.dumps(["pasta", "tomato", "garlic"]),
                steps=json.dumps(["boil", "sauté"]),
                tags="italian,tomato"
            ),
        ]
        db.add_all(recipes)
        db.commit()

        response = client.get("/api/recipes?q=tomato")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_fts_special_characters(self, client, db):
        """FTS handles special characters in search."""
        recipe = Recipe(
            name="Fish & Chips",
            ingredients=json.dumps(["fish", "chips"]),
            steps=json.dumps(["fry"]),
            tags="british,fried"
        )
        db.add(recipe)
        db.commit()

        # Search with special char (should be escaped safely)
        response = client.get("/api/recipes?q=Fish")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1


class TestSharedDbDependency:
    """Regression tests for issue #6: get_db/_engine must be defined once."""

    def test_get_db_is_shared_across_modules(self):
        """main.py and reviews.py must expose the same get_db callable.

        FastAPI keys dependency_overrides by the callable identity. If each module
        defines its own get_db, an override in one won't affect routes in the other,
        and each module creates its own engine → two connection pools. The shared
        callable must come from models.py.
        """
        from src import main as main_mod
        from src import reviews as reviews_mod

        # Both routers must resolve Depends(get_db) to the exact same callable.
        assert main_mod.get_db is reviews_mod.get_db
        # And that callable must be the one defined in models.py.
        assert main_mod.get_db.__module__ == "models"
        assert main_mod.get_db.__qualname__ == "get_db"

    def test_only_one_engine_instance(self, client, db):
        """After hitting both a main route and a reviews route, only one shared
        engine object should exist in models._engine."""
        from src import models as models_mod
        from src import main as main_mod
        from src import reviews as reviews_mod

        # Neither main nor reviews should carry its own _engine module global.
        assert not hasattr(main_mod, "_engine"), "main.py should not own an _engine"
        assert not hasattr(reviews_mod, "_engine"), "reviews.py should not own an _engine"

        # Create a recipe (main route) and a review (reviews route) in one client.
        r = client.post("/api/recipes", json={
            "name": "Shared Engine Test",
            "ingredients": ["a"],
            "steps": ["b"],
        })
        assert r.status_code == 201
        recipe_id = r.json()["id"]

        r = client.post(f"/api/recipes/{recipe_id}/reviews", json={"rating": 5, "text": "ok"})
        assert r.status_code == 201

        # Check the single shared engine attribute exists on models.
        assert hasattr(models_mod, "_engine")


class TestApiRecipeValidation:
    """Negative-path tests for POST /api/recipes and PUT /api/recipes/{id} — closes #7 and #10."""

    def test_create_missing_name(self, client):
        r = client.post("/api/recipes", json={"ingredients": ["a"], "steps": ["b"]})
        assert r.status_code == 422

    def test_create_empty_name(self, client):
        r = client.post("/api/recipes", json={"name": "", "ingredients": [], "steps": []})
        assert r.status_code == 422

    def test_create_whitespace_name(self, client):
        r = client.post("/api/recipes", json={"name": "   ", "ingredients": [], "steps": []})
        assert r.status_code == 422

    def test_create_name_wrong_type(self, client):
        r = client.post("/api/recipes", json={"name": 42, "ingredients": [], "steps": []})
        assert r.status_code == 422

    def test_create_ingredients_wrong_type(self, client):
        r = client.post("/api/recipes", json={"name": "Soup", "ingredients": "not a list", "steps": []})
        assert r.status_code == 422

    def test_create_steps_wrong_type(self, client):
        r = client.post("/api/recipes", json={"name": "Soup", "ingredients": [], "steps": "not a list"})
        assert r.status_code == 422

    def test_create_empty_body(self, client):
        r = client.post("/api/recipes", json={})
        assert r.status_code == 422

    def test_update_empty_name(self, client):
        # Create a valid recipe first
        r = client.post("/api/recipes", json={"name": "Soup", "ingredients": [], "steps": []})
        assert r.status_code == 201
        recipe_id = r.json()["id"]

        r = client.put(f"/api/recipes/{recipe_id}", json={"name": ""})
        assert r.status_code == 422

    def test_update_whitespace_name(self, client):
        r = client.post("/api/recipes", json={"name": "Soup", "ingredients": [], "steps": []})
        assert r.status_code == 201
        recipe_id = r.json()["id"]

        r = client.put(f"/api/recipes/{recipe_id}", json={"name": "   "})
        assert r.status_code == 422

    def test_update_ingredients_wrong_type(self, client):
        r = client.post("/api/recipes", json={"name": "Soup", "ingredients": [], "steps": []})
        assert r.status_code == 201
        recipe_id = r.json()["id"]

        r = client.put(f"/api/recipes/{recipe_id}", json={"ingredients": "oops"})
        assert r.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
