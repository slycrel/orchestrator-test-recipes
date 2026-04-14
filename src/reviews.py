"""Review endpoints: POST review, GET reviews per recipe, aggregate rating."""
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import Recipe, Review, ReviewCreate, get_db

router = APIRouter()


def _review_dict(r: Review) -> dict:
    return {"id": r.id, "recipe_id": r.recipe_id, "rating": r.rating, "text": r.text or ""}


def _sql_aggregate(db: Session, recipe_id: int):
    """Return (avg_rating, review_count) via SQL — no lazy loading."""
    row = db.query(func.avg(Review.rating), func.count(Review.id)).filter(
        Review.recipe_id == recipe_id
    ).one()
    avg_raw, count = row
    avg_rating = round(float(avg_raw), 1) if avg_raw is not None else None
    return avg_rating, count


# ── JSON API ──────────────────────────────────────────────────────────────────

@router.get("/api/recipes/{recipe_id}/reviews")
def api_list_reviews(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    avg_rating, review_count = _sql_aggregate(db, recipe_id)
    reviews = db.query(Review).filter(Review.recipe_id == recipe_id).all()
    return {
        "recipe_id": recipe_id,
        "avg_rating": avg_rating,
        "review_count": review_count,
        "reviews": [_review_dict(r) for r in reviews],
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
    avg_rating, review_count = _sql_aggregate(db, recipe_id)
    return {
        "recipe_id": recipe_id,
        "avg_rating": avg_rating,
        "review_count": review_count,
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
