#!/usr/bin/env python3
"""Seed the recipe database with sample data.

Usage:
    python scripts/seed.py [--db DATABASE_URL]

Idempotent: skips recipes that already exist by name.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models import Recipe, Review, init_db, create_db_engine, get_session

RECIPES = [
    {
        "name": "Spaghetti Carbonara",
        "ingredients": ["400g spaghetti", "200g guanciale", "4 egg yolks", "100g Pecorino Romano", "black pepper"],
        "steps": [
            "Boil pasta in salted water until al dente.",
            "Fry guanciale until crispy.",
            "Whisk egg yolks with grated cheese and pepper.",
            "Toss hot pasta off heat with guanciale and egg mixture.",
            "Add pasta water gradually to achieve creamy sauce.",
        ],
        "photo_url": None,
        "tags": "italian,pasta,dinner",
        "reviews": [{"rating": 5, "text": "Perfect carbonara!"}, {"rating": 4, "text": "Great recipe."}],
    },
    {
        "name": "Chicken Tikka Masala",
        "ingredients": ["700g chicken breast", "200ml yogurt", "400ml coconut cream", "2 tsp garam masala", "1 can crushed tomatoes", "garlic", "ginger", "cilantro"],
        "steps": [
            "Marinate chicken in yogurt and spices for 1 hour.",
            "Grill or broil chicken until charred.",
            "Sauté garlic and ginger, add tomatoes and spices.",
            "Add grilled chicken and coconut cream, simmer 15 min.",
            "Garnish with cilantro and serve with rice.",
        ],
        "photo_url": None,
        "tags": "indian,chicken,dinner,spicy",
        "reviews": [{"rating": 5, "text": "Restaurant quality!"}, {"rating": 5, "text": "Family favorite."}],
    },
    {
        "name": "Avocado Toast",
        "ingredients": ["2 slices sourdough", "1 ripe avocado", "lemon juice", "red pepper flakes", "sea salt", "2 eggs"],
        "steps": [
            "Toast sourdough until golden.",
            "Mash avocado with lemon juice and salt.",
            "Spread avocado on toast.",
            "Top with a poached egg and red pepper flakes.",
        ],
        "photo_url": None,
        "tags": "breakfast,vegetarian,quick",
        "reviews": [{"rating": 4, "text": "Simple and delicious."}],
    },
    {
        "name": "Beef Tacos",
        "ingredients": ["500g ground beef", "8 corn tortillas", "1 onion", "2 cloves garlic", "cumin", "chili powder", "lime", "cilantro", "salsa"],
        "steps": [
            "Brown ground beef with onion and garlic.",
            "Season with cumin and chili powder.",
            "Warm tortillas on a dry pan.",
            "Fill tortillas and top with salsa, lime, and cilantro.",
        ],
        "photo_url": None,
        "tags": "mexican,beef,dinner,quick",
        "reviews": [{"rating": 5, "text": "Taco night staple."}],
    },
    {
        "name": "Greek Salad",
        "ingredients": ["3 tomatoes", "1 cucumber", "1 red onion", "200g feta cheese", "kalamata olives", "olive oil", "oregano", "lemon"],
        "steps": [
            "Chop tomatoes, cucumber, and onion into chunks.",
            "Combine in a bowl with olives and feta.",
            "Dress with olive oil, lemon, and oregano.",
        ],
        "photo_url": None,
        "tags": "greek,vegetarian,salad,lunch",
        "reviews": [{"rating": 4, "text": "Fresh and light."}, {"rating": 5, "text": "Perfect summer salad."}],
    },
    {
        "name": "Banana Pancakes",
        "ingredients": ["2 ripe bananas", "2 eggs", "1 cup flour", "1 tsp baking powder", "milk", "butter", "maple syrup"],
        "steps": [
            "Mash bananas and whisk with eggs.",
            "Mix in flour, baking powder, and enough milk for thick batter.",
            "Cook on buttered griddle over medium heat until golden.",
            "Serve with maple syrup.",
        ],
        "photo_url": None,
        "tags": "breakfast,vegetarian,sweet",
        "reviews": [{"rating": 5, "text": "Kids love them!"}],
    },
    {
        "name": "Vegetable Stir Fry",
        "ingredients": ["2 cups broccoli", "1 bell pepper", "2 carrots", "snap peas", "garlic", "ginger", "soy sauce", "sesame oil", "rice"],
        "steps": [
            "Cook rice per package instructions.",
            "Heat wok on high, add oil.",
            "Stir-fry vegetables 5-7 min until tender-crisp.",
            "Add garlic, ginger, soy sauce, and sesame oil.",
            "Serve over rice.",
        ],
        "photo_url": None,
        "tags": "asian,vegetarian,vegan,dinner,quick",
        "reviews": [],
    },
    {
        "name": "Chocolate Chip Cookies",
        "ingredients": ["225g butter", "200g brown sugar", "100g white sugar", "2 eggs", "1 tsp vanilla", "300g flour", "1 tsp baking soda", "300g chocolate chips"],
        "steps": [
            "Preheat oven to 375°F (190°C).",
            "Cream butter and sugars until fluffy.",
            "Beat in eggs and vanilla.",
            "Mix in flour and baking soda, fold in chocolate chips.",
            "Drop by spoonfuls onto baking sheet, bake 10-12 min.",
        ],
        "photo_url": None,
        "tags": "dessert,baking,sweet",
        "reviews": [{"rating": 5, "text": "Best cookies ever!"}, {"rating": 5, "text": "Crispy edges, chewy center."}],
    },
    {
        "name": "Tomato Basil Soup",
        "ingredients": ["6 ripe tomatoes", "1 onion", "4 cloves garlic", "basil", "vegetable broth", "heavy cream", "olive oil"],
        "steps": [
            "Roast tomatoes with garlic and olive oil at 400°F for 30 min.",
            "Sauté onion until softened.",
            "Blend roasted tomatoes, onion, and broth until smooth.",
            "Simmer with basil, finish with a splash of cream.",
        ],
        "photo_url": None,
        "tags": "soup,vegetarian,lunch,comfort",
        "reviews": [{"rating": 4, "text": "Warming and satisfying."}],
    },
    {
        "name": "Salmon with Lemon Dill",
        "ingredients": ["4 salmon fillets", "2 lemons", "fresh dill", "garlic", "butter", "capers"],
        "steps": [
            "Pat salmon dry and season with salt and pepper.",
            "Pan-sear in butter 4 min per side.",
            "Add garlic, lemon juice, dill, and capers to pan.",
            "Baste salmon with sauce and serve immediately.",
        ],
        "photo_url": None,
        "tags": "seafood,dinner,healthy,quick",
        "reviews": [{"rating": 5, "text": "Elegant and easy."}, {"rating": 4, "text": "Great weeknight dinner."}],
    },
]


def seed(db_url: str) -> None:
    engine = create_db_engine(db_url)
    init_db(engine)
    session = get_session(engine)

    existing_names = {r.name for r in session.query(Recipe.name).all()}
    added = 0

    for data in RECIPES:
        if data["name"] in existing_names:
            continue
        recipe = Recipe(
            name=data["name"],
            ingredients=json.dumps(data["ingredients"]),
            steps=json.dumps(data["steps"]),
            photo_url=data.get("photo_url"),
            tags=data.get("tags"),
        )
        session.add(recipe)
        session.flush()
        for rv in data.get("reviews", []):
            session.add(Review(recipe_id=recipe.id, rating=rv["rating"], text=rv.get("text", "")))
        added += 1

    session.commit()
    session.close()
    print(f"Seed complete: {added} recipes added ({len(existing_names)} already existed).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the recipe database.")
    parser.add_argument("--db", default=os.environ.get("DATABASE_URL", "sqlite:///recipes.db"))
    args = parser.parse_args()
    seed(args.db)
