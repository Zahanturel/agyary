FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# From the lockfile, so the image runs exactly the versions the tests ran
# against. Without uv.lock every build re-resolved from scratch, and one came
# out without greenlet - which SQLAlchemy's async engine cannot start without -
# so the migration failed at deploy time.
RUN uv sync --frozen --no-dev
# Fail the BUILD, not the deploy, if a dependency the app cannot run without is
# missing.
RUN /app/.venv/bin/python -c "import greenlet, asyncpg, sqlalchemy.ext.asyncio, fastapi, alembic"

COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "agyary.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
