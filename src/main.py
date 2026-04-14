import json
import os
from typing import Optional

from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from models import Recipe, Review, RecipeCreate, RecipeUpdate, init_db, get_engine, get_session, get_db, _get_shared_engine
from reviews import router as reviews_router

# Abuse limits for POST /recipes.
MAX_RECIPE_BODY_BYTES = 32768
RECIPE_CREATE_RATE = "10/minute"


def _client_ip(request: Request) -> str:
    # Prefer X-Forwarded-For (enables per-IP tests and real deployments behind proxies);
    # fall back to the direct peer.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_client_ip)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

app = FastAPI(title="Recipe Site")
app.state.limiter = limiter


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> PlainTextResponse:
    return PlainTextResponse("Too Many Requests", status_code=429)


def _integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse({"detail": "Constraint violation: invalid data"}, status_code=422)


def _sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    import logging
    logging.getLogger(__name__).error("Database error: %s", exc)
    return JSONResponse({"detail": "Database error"}, status_code=500)


def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Flatten Pydantic validation errors into a single human-readable string
    messages = [e.get("msg", str(e)) for e in exc.errors()]
    detail = "; ".join(messages)
    return JSONResponse({"detail": detail}, status_code=422)


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_exception_handler(IntegrityError, _integrity_error_handler)
app.add_exception_handler(SQLAlchemyError, _sqlalchemy_error_handler)
app.add_exception_handler(RequestValidationError, _validation_error_handler)


@app.middleware("http")
async def _recipe_body_size_guard(request: Request, call_next):
    # Reject oversized POST /recipes payloads before FastAPI parses form data.
    if request.method == "POST" and request.url.path in ("/recipes", "/api/recipes"):
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > MAX_RECIPE_BODY_BYTES:
                    return PlainTextResponse("Payload Too Large", status_code=413)
            except ValueError:
                pass
        else:
            # No Content-Length: buffer body to measure, then replay via receive.
            body = await request.body()
            if len(body) > MAX_RECIPE_BODY_BYTES:
                return PlainTextResponse("Payload Too Large", status_code=413)

            async def _replay_receive():
                return {"type": "http.request", "body": body, "more_body": False}

            request._receive = _replay_receive
    return await call_next(request)


app.include_router(reviews_router)


@app.on_event("startup")
def startup():
    _get_shared_engine()


# ── helpers ──────────────────────────────────────────────────────────────────


def _safe_json_load(value: str, fallback, recipe_id=None, field: str = ""):
    """Parse JSON string; return fallback and log on decode error."""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        import logging
        logging.getLogger(__name__).error(
            "json decode error in recipe %s field %r: %s", recipe_id, field, exc
        )
        return fallback


def recipe_to_dict(recipe: Recipe, db: Optional[Session] = None) -> dict:
    # Use SQL aggregates when a session is available to avoid N+1 lazy loading.
    if db is not None:
        from models import Review as _Review
        row = db.query(
            func.avg(_Review.rating), func.count(_Review.id)
        ).filter(_Review.recipe_id == recipe.id).one()
        avg_raw, review_count = row
        avg_rating = round(float(avg_raw), 1) if avg_raw is not None else None
    else:
        # Fallback: use already-loaded relationship (single-recipe detail calls).
        reviews = recipe.reviews
        avg_rating = (
            round(sum(r.rating for r in reviews) / len(reviews), 1)
            if reviews else None
        )
        review_count = len(reviews)
    return {
        "id": recipe.id,
        "name": recipe.name,
        "ingredients": _safe_json_load(recipe.ingredients, [], recipe.id, "ingredients") if recipe.ingredients else [],
        "steps": _safe_json_load(recipe.steps, [], recipe.id, "steps") if recipe.steps else [],
        "photo_url": recipe.photo_url or "",
        "tags": [t.strip() for t in (recipe.tags or "").split(",") if t.strip()],
        "avg_rating": avg_rating,
        "review_count": review_count,
        "created_at": recipe.created_at.isoformat() if recipe.created_at else None,
    }


def fts_search(db: Session, term: str) -> list[int]:
    safe = term.replace('"', '""')
    rows = db.execute(
        text('SELECT recipe_id FROM recipes_fts WHERE recipes_fts MATCH :q'),
        {"q": f'"{safe}"'}
    ).fetchall()
    return [r[0] for r in rows]


# ── HTML pages ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: Optional[str] = None, db: Session = Depends(get_db)):
    if q and q.strip():
        ids = fts_search(db, q.strip())
        recipes = db.query(Recipe).filter(Recipe.id.in_(ids)).all() if ids else []
    else:
        recipes = db.query(Recipe).all()
    items = [recipe_to_dict(r, db) for r in recipes]
    return templates.TemplateResponse("index.html", {"request": request, "recipes": items, "q": q or ""})


@app.get("/recipes/new", response_class=HTMLResponse)
def new_recipe_form(request: Request):
    return templates.TemplateResponse("form.html", {"request": request, "recipe": None, "error": None})


@app.get("/recipes/{recipe_id}", response_class=HTMLResponse)
def recipe_detail(recipe_id: int, request: Request, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return templates.TemplateResponse(
        "detail.html",
        {"request": request, "recipe": recipe_to_dict(recipe, db), "reviews": recipe.reviews}
    )


@app.get("/recipes/{recipe_id}/edit", response_class=HTMLResponse)
def edit_recipe_form(recipe_id: int, request: Request, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return templates.TemplateResponse("form.html", {"request": request, "recipe": recipe_to_dict(recipe, db), "error": None})


# ── form POST handlers ────────────────────────────────────────────────────────

@app.post("/recipes", response_class=HTMLResponse)
@limiter.limit(RECIPE_CREATE_RATE)
def create_recipe(
    request: Request,
    name: str = Form(...),
    ingredients: str = Form(...),
    steps: str = Form(...),
    photo_url: str = Form(""),
    tags: str = Form(""),
    db: Session = Depends(get_db),
):
    if not name.strip():
        return templates.TemplateResponse("form.html", {
            "request": request, "recipe": None, "error": "Name is required."
        })
    ingredients_list = [i.strip() for i in ingredients.splitlines() if i.strip()]
    steps_list = [s.strip() for s in steps.splitlines() if s.strip()]
    recipe = Recipe(
        name=name.strip(),
        ingredients=json.dumps(ingredients_list),
        steps=json.dumps(steps_list),
        photo_url=photo_url.strip() or None,
        tags=tags.strip() or None,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return RedirectResponse(url=f"/recipes/{recipe.id}", status_code=303)


@app.post("/recipes/{recipe_id}/edit", response_class=HTMLResponse)
def update_recipe(
    recipe_id: int,
    request: Request,
    name: str = Form(...),
    ingredients: str = Form(...),
    steps: str = Form(...),
    photo_url: str = Form(""),
    tags: str = Form(""),
    db: Session = Depends(get_db),
):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    if not name.strip():
        return templates.TemplateResponse("form.html", {
            "request": request, "recipe": recipe, "error": "Name is required."
        })
    recipe.name = name.strip()
    recipe.ingredients = json.dumps([i.strip() for i in ingredients.splitlines() if i.strip()])
    recipe.steps = json.dumps([s.strip() for s in steps.splitlines() if s.strip()])
    recipe.photo_url = photo_url.strip() or None
    recipe.tags = tags.strip() or None
    db.commit()
    return RedirectResponse(url=f"/recipes/{recipe_id}", status_code=303)


@app.post("/recipes/{recipe_id}/delete")
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    db.delete(recipe)
    db.commit()
    return RedirectResponse(url="/", status_code=303)


# ── JSON API ──────────────────────────────────────────────────────────────────

@app.get("/api/recipes")
def api_list_recipes(q: Optional[str] = None, db: Session = Depends(get_db)):
    if q and q.strip():
        ids = fts_search(db, q.strip())
        recipes = db.query(Recipe).filter(Recipe.id.in_(ids)).all() if ids else []
    else:
        recipes = db.query(Recipe).all()
    return [recipe_to_dict(r, db) for r in recipes]


@app.get("/api/recipes/{recipe_id}")
def api_get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe_to_dict(recipe, db)


@app.post("/api/recipes", status_code=201)
@limiter.limit(RECIPE_CREATE_RATE)
def api_create_recipe(request: Request, payload: RecipeCreate, db: Session = Depends(get_db)):
    recipe = Recipe(
        name=payload.name,
        ingredients=json.dumps(payload.ingredients),
        steps=json.dumps(payload.steps),
        photo_url=payload.photo_url,
        tags=",".join(payload.tags) if payload.tags else None,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe_to_dict(recipe, db)


@app.put("/api/recipes/{recipe_id}")
def api_update_recipe(recipe_id: int, payload: RecipeUpdate, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    if payload.name is not None:
        recipe.name = payload.name
    if payload.ingredients is not None:
        recipe.ingredients = json.dumps(payload.ingredients)
    if payload.steps is not None:
        recipe.steps = json.dumps(payload.steps)
    if payload.photo_url is not None:
        recipe.photo_url = payload.photo_url
    if payload.tags is not None:
        recipe.tags = ",".join(payload.tags) if payload.tags else None
    db.commit()
    return recipe_to_dict(recipe, db)


@app.delete("/api/recipes/{recipe_id}", status_code=204)
def api_delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    db.delete(recipe)
    db.commit()


# Review endpoints are handled by reviews_router (src/reviews.py)
