import json
import os
from typing import Optional

from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from models import Recipe, Review, init_db, get_engine, get_session, get_db, _get_shared_engine
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


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)


@app.middleware("http")
async def _recipe_body_size_guard(request: Request, call_next):
    # Reject oversized POST /recipes payloads before FastAPI parses form data.
    if request.method == "POST" and request.url.path == "/recipes":
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

def recipe_to_dict(recipe: Recipe) -> dict:
    return {
        "id": recipe.id,
        "name": recipe.name,
        "ingredients": json.loads(recipe.ingredients) if recipe.ingredients else [],
        "steps": json.loads(recipe.steps) if recipe.steps else [],
        "photo_url": recipe.photo_url or "",
        "tags": [t.strip() for t in (recipe.tags or "").split(",") if t.strip()],
        "avg_rating": (
            round(sum(r.rating for r in recipe.reviews) / len(recipe.reviews), 1)
            if recipe.reviews else None
        ),
        "review_count": len(recipe.reviews),
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
    items = [recipe_to_dict(r) for r in recipes]
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
        {"request": request, "recipe": recipe_to_dict(recipe), "reviews": recipe.reviews}
    )


@app.get("/recipes/{recipe_id}/edit", response_class=HTMLResponse)
def edit_recipe_form(recipe_id: int, request: Request, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return templates.TemplateResponse("form.html", {"request": request, "recipe": recipe_to_dict(recipe), "error": None})


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
    return [recipe_to_dict(r) for r in recipes]


@app.get("/api/recipes/{recipe_id}")
def api_get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe_to_dict(recipe)


@app.post("/api/recipes", status_code=201)
def api_create_recipe(payload: dict, db: Session = Depends(get_db)):
    recipe = Recipe(
        name=payload["name"],
        ingredients=json.dumps(payload.get("ingredients", [])),
        steps=json.dumps(payload.get("steps", [])),
        photo_url=payload.get("photo_url"),
        tags=",".join(payload.get("tags", [])) if payload.get("tags") else None,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe_to_dict(recipe)


@app.put("/api/recipes/{recipe_id}")
def api_update_recipe(recipe_id: int, payload: dict, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    if "name" in payload:
        recipe.name = payload["name"]
    if "ingredients" in payload:
        recipe.ingredients = json.dumps(payload["ingredients"])
    if "steps" in payload:
        recipe.steps = json.dumps(payload["steps"])
    if "photo_url" in payload:
        recipe.photo_url = payload["photo_url"]
    if "tags" in payload:
        recipe.tags = ",".join(payload["tags"]) if payload["tags"] else None
    db.commit()
    return recipe_to_dict(recipe)


@app.delete("/api/recipes/{recipe_id}", status_code=204)
def api_delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    db.delete(recipe)
    db.commit()


# Review endpoints are handled by reviews_router (src/reviews.py)
