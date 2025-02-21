FROM python:3.11.9-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN pip install poetry && poetry config virtualenvs.in-project true

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN poetry install --no-root
RUN poetry install --extras server

COPY . .

EXPOSE 8000

CMD ["poetry", "run", "python", "main.py", "--server", "--host", "0.0.0.0", "--port", "8000"]
