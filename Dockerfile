FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NARYADAI_DATA_DIR=/data NARYADAI_HOST=0.0.0.0 NARYADAI_PORT=8765
WORKDIR /app
COPY requirements-api.txt ./requirements-api.txt
RUN pip install --no-cache-dir -r requirements-api.txt && mkdir -p /data && chown -R 10001:10001 /app /data
COPY --chown=10001:10001 server.py ./server.py
COPY --chown=10001:10001 static ./static
USER 10001:10001
EXPOSE 8765
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8765/api/health\",timeout=2)"
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8765", "--db", "/data/naryadai.sqlite3"]
