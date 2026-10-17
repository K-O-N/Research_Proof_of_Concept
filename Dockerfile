FROM python:3.13.11-slim 
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

WORKDIR /code 
ENV PATH="/code/.venv/bin:$PATH"

COPY pyproject.toml .python-version uv.lock ./
RUN uv sync --locked


COPY unit_tests/ ./unit_tests/
COPY src/ ./src/
COPY data/ ./data/

ENTRYPOINT ["python", "src/d_run_all.py" ]