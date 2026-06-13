FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies (curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv --no-cache-dir

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies with uv to system Python
RUN uv pip install --system -r pyproject.toml

# The app code, skills, and context.
COPY main.py .
COPY app ./app
COPY scripts ./scripts
COPY .env.example .env.example

EXPOSE 8000 8501

# Default command runs the API; the worker overrides this in compose/railway.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
