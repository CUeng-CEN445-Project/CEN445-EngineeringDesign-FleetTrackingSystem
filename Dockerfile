# syntax=docker/dockerfile:1
#
# FiloTrack container image.
#   docker build -t filotrack .
#   docker run -p 8000:8000 -v filotrack-data:/data filotrack
#
# The application uses the Python standard library only, so no `pip install`.

FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FT_HOST=0.0.0.0 \
    FT_PORT=8000 \
    FT_DATA_DIR=/data

WORKDIR /app

# Run as an unprivileged user; /data holds the SQLite time-series database
RUN useradd --create-home --uid 10001 filotrack \
    && mkdir -p /data \
    && chown filotrack:filotrack /data

COPY app.py ./
COPY backend ./backend
COPY web ./web

USER filotrack
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"

CMD ["python", "app.py", "--no-open"]
