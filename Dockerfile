FROM python:3.13.11-slim 
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

WORKDIR /code 
ENV PATH="/code/.venv/bin:$PATH"

COPY pyproject.toml .python-version uv.lock ./
RUN uv sync --locked

COPY a_ingest_data.py .
COPY b_silver_layer.py .
COPY c_gold_layer.py .
COPY d_run_all.py .
COPY data/ ./data/

ENTRYPOINT ["python", "d_run_all.py" ]