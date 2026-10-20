FROM python:3.11-slim
RUN pip install --no-cache-dir uv==0.11.33
WORKDIR /app/services
COPY services/pyproject.toml services/uv.lock ./
RUN uv sync --frozen --no-install-project
COPY services/ ./
COPY data/ /app/data/
COPY prompts/ /app/prompts/
COPY evals/ /app/evals/
ENV PYTHONPATH=/app/services HF_HOME=/app/.cache/hf
