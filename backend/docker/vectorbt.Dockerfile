# Runs the backtest tests where vectorbt can be installed (Linux), pinned by uv.lock.
# On an Intel Mac the `backtest` extra is skipped, so the vectorbt engine is only tested here:
#   make test-vectorbt
FROM python:3.12-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/opt/venv NUMBA_CACHE_DIR=/tmp/numba
RUN uv sync --frozen --extra backtest --no-install-project
ENV PATH="/opt/venv/bin:$PATH"
CMD ["python", "-m", "pytest", "tests/backtest", "-q", "-p", "no:cacheprovider"]
