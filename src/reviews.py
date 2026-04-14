"""Review endpoints: POST review, GET reviews per recipe, aggregate rating."""
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from models import Recipe, Review, ReviewCreate, get_db

router = APIRouter()


def _review_dict(r: Review) -> dict:
    return {"id": r.id, "recipe_id": r.recipe_id, "rating": r.rating, "text": r.text or ""}


def _aggregate(reviews) -> Optional[float]:
    if not reviews:
        return None
    return round(sum(r.rating for r in reviews) / len(reviews), 1)


# ── JSON API ──────────────────────────────────────────────────────────────────

@router.get("/api/recipes/{recipe_id}/reviews")
def api_list_reviews(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {
        "recipe_id": recipe_id,
        "avg_rating": _aggregate(recipe.reviews),
        "review_count": len(recipe.reviews),
        "reviews": [_review_dict(r) for r in recipe.reviews],
    }


@router.post("/api/recipes/{recipe_id}/reviews", status_code=201)
def api_create_review(recipe_id: int, payload: ReviewCreate, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    if not (1 <= payload.rating <= 5):
        raise HTTPException(status_code=422, detail="Rating must be 1-5")
    review = Review(recipe_id=recipe_id, rating=payload.rating, text=payload.text or "")
    db.add(review)
    db.commit()
    db.refresh(review)
    return _review_dict(review)


@router.get("/api/recipes/{recipe_id}/rating")
def api_aggregate_rating(recipe_id: int, db: Session = Depends(get_db)):
    """Return just the aggregate star rating + count for a recipe."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {
        "recipe_id": recipe_id,
        "avg_rating": _aggregate(recipe.reviews),
        "review_count": len(recipe.reviews),
    }


# ── HTML form POST ────────────────────────────────────────────────────────────

@router.post("/recipes/{recipe_id}/reviews")
def html_add_review(
    recipe_id: int,
    request: Request,
    rating: int = Form(...),
    text: str = Form(""),
    db: Session = Depends(get_db),
):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    if not (1 <= rating <= 5):
        raise HTTPException(status_code=422, detail="Rating must be 1-5")
    review = Review(recipe_id=recipe_id, rating=rating, text=text.strip() or None)
    db.add(review)
    db.commit()
    return RedirectResponse(url=f"/recipes/{recipe_id}", status_code=303)
