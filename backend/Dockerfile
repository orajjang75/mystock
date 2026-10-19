# The API and the scheduler (one process, one worker: the jobs live inside it).
FROM python:3.12-slim
RUN pip install --no-cache-dir uv
WORKDIR /srv/backend
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Seoul
COPY pyproject.toml uv.lock ./
# pykrx supplies the listings and market-cap ranking the KIS adapter does not (docs/real-data.md).
RUN uv sync --frozen --no-dev --extra pykrx --no-install-project
ENV PATH="/opt/venv/bin:$PATH"
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
# /data holds the KIS token cache (KIS_TOKEN_FILE), which survives restarts through a volume.
RUN useradd --create-home --uid 1000 mystock && mkdir /data && chown mystock /data
USER mystock
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1"]
