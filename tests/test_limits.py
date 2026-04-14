"""Tests for POST /recipes body-size cap and per-IP rate limit."""
import os
import pytest
from fastapi.testclient import TestClient

# DATABASE_URL is set by conftest.py before this module is loaded.
from src.main import app, get_db, limiter, MAX_RECIPE_BODY_BYTES
from src.models import Base, init_db, create_db_engine, get_session


# db_engine fixture provided by conftest.py.


@pytest.fixture(scope="function")
def client(db_engine):
    def override_get_db():
        db = get_session(db_engine)
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # Reset rate-limit storage so tests are hermetic.
    limiter.reset()
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()
    limiter.reset()


def _form_payload_of_size(target_bytes: int) -> dict:
    """Return a form-data dict whose urlencoded wire size is approximately target_bytes.

    Fields name/ingredients/steps are required; we pad `ingredients` to hit the size.
    """
    # Overhead of other fields + keys + separators ~ a few hundred bytes; subtract a margin.
    fixed = {
        "name": "x",
        "steps": "s",
        "photo_url": "",
        "tags": "",
    }
    # urlencoded approx length of fixed portion when concatenated by httpx:
    # name=x&ingredients=<pad>&steps=s&photo_url=&tags=
    overhead = len("name=x&ingredients=&steps=s&photo_url=&tags=")
    pad_len = max(1, target_bytes - overhead)
    fixed["ingredients"] = "a" * pad_len
    return fixed


class TestBodySizeLimit:
    def test_just_under_limit_passes(self, client):
        # Aim for ~32000 bytes, comfortably under 32768.
        form = _form_payload_of_size(32000)
        resp = client.post(
            "/recipes",
            data=form,
            follow_redirects=False,
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        assert resp.status_code == 303, f"expected 303, got {resp.status_code}"

    def test_just_over_limit_returns_413(self, client):
        # Construct a body that will urlencode to > 32768 bytes.
        form = _form_payload_of_size(40000)
        resp = client.post(
            "/recipes",
            data=form,
            follow_redirects=False,
            headers={"X-Forwarded-For": "10.0.0.2"},
        )
        assert resp.status_code == 413

    def test_over_limit_without_content_length_returns_413(self, client):
        # Force chunked (no Content-Length) via a generator body.
        big = b"name=x&ingredients=" + (b"a" * (MAX_RECIPE_BODY_BYTES + 100)) + b"&steps=s"

        def gen():
            yield big

        resp = client.post(
            "/recipes",
            content=gen(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Forwarded-For": "10.0.0.3",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 413


class TestRateLimit:
    def test_ten_requests_in_a_minute_pass_eleventh_blocks(self, client):
        form = _form_payload_of_size(500)
        headers = {"X-Forwarded-For": "192.0.2.10"}
        for i in range(10):
            resp = client.post("/recipes", data=form, headers=headers, follow_redirects=False)
            assert resp.status_code == 303, f"request {i + 1} expected 303, got {resp.status_code}"
        resp = client.post("/recipes", data=form, headers=headers, follow_redirects=False)
        assert resp.status_code == 429

    def test_different_ips_tracked_independently(self, client):
        form = _form_payload_of_size(500)
        # Exhaust IP A.
        headers_a = {"X-Forwarded-For": "192.0.2.20"}
        for i in range(10):
            resp = client.post("/recipes", data=form, headers=headers_a, follow_redirects=False)
            assert resp.status_code == 303
        resp = client.post("/recipes", data=form, headers=headers_a, follow_redirects=False)
        assert resp.status_code == 429

        # IP B should still be allowed (independent bucket).
        headers_b = {"X-Forwarded-For": "192.0.2.21"}
        resp = client.post("/recipes", data=form, headers=headers_b, follow_redirects=False)
        assert resp.status_code == 303


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
