FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY req.txt .
RUN uv pip install --system --no-cache -r req.txt

# Create non-root user FIRST
RUN useradd -m -s /bin/bash appuser \
    && mkdir -p /app/browser_data \
    && chown -R appuser:appuser /app

# Install Chromium system deps as root
RUN playwright install --with-deps chromium

# Set Playwright browser path for appuser
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN mkdir -p /ms-playwright \
    && playwright install chromium \
    && chmod -R 777 /ms-playwright

COPY app.py core.py llm_parser.py ranker.py session_manager.py ./
COPY templates/ ./templates/

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 5000

CMD ["python", "app.py"]