# Recipe Site

A recipe management web application built as a real-world test subject for [openclaw-orchestration](https://github.com/slycrel/openclaw-orchestration).

## What This Is

This repo is actively maintained by two autonomous AI agents running on Poe (openclaw-orchestration):

- **Product Manager agent** — reviews code, opens issues, suggests features, reviews PRs
- **Developer agent** — implements changes from issues, opens PRs, manages deployment

The humans set the direction; the agents do the work. This is a live experiment in autonomous multi-agent software development.

## Project Goals

A recipe website with:
- Python backend (FastAPI) with SQLite + full-text search
- CRUD for recipes: ingredients, steps, photos, tags
- Review system: 1-5 star ratings + text reviews
- Server-rendered HTML frontend (Jinja2, no JS frameworks)
- Docker deployment (docker-compose up)
- pytest test coverage for API endpoints

## Running Locally

```bash
# With Docker
docker-compose up

# Without Docker
pip install -r requirements.txt
python -m app.main
```

## Development

See open issues for what's being worked on. PRs are opened by the developer agent and reviewed by the product manager agent.

## License

MIT
