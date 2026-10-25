FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 1000 appuser
COPY --chown=appuser:appuser . .
USER appuser
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=4)"
CMD ["gunicorn", "--workers", "2", "--threads", "2", "--timeout", "60", "--bind", "0.0.0.0:7860", "app:superkart_api"]
