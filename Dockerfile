FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && python -m pip install --no-cache-dir -r /app/requirements.txt \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin nova

COPY backend /app/backend
COPY scripts/cloud_entrypoint.sh /app/cloud_entrypoint.sh

RUN chown -R nova:nova /app \
    && chmod 0555 /app/cloud_entrypoint.sh

USER nova

WORKDIR /app/backend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.environ.get('PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health/live', timeout=3)"

CMD ["/app/cloud_entrypoint.sh"]
