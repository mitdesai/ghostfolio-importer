FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

RUN groupadd --system --gid 1000 app \
 && useradd  --system --uid 1000 --gid app --home /srv --shell /sbin/nologin app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

RUN mkdir -p /data /state && chown -R app:app /srv /data /state

USER app

ENV HTTP_PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,os,sys; \
port=os.environ.get('HTTP_PORT','8080'); \
sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2).status==200 else 1)"

CMD ["python", "-m", "app.main"]
