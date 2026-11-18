# Self-hosted alternative to Vercel: one container, in-memory run store.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY usecase_forge ./usecase_forge
COPY public ./public
RUN pip install --no-cache-dir ".[dev]"
EXPOSE 8000
CMD ["uvicorn", "usecase_forge.web:app", "--host", "0.0.0.0", "--port", "8000"]
