FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NARYADAI_DATA_DIR=/data NARYADAI_HOST=0.0.0.0
WORKDIR /app
COPY requirements-api.txt ./requirements-api.txt
RUN pip install --no-cache-dir -r requirements-api.txt && mkdir -p /data && chown -R 10001:10001 /app /data
COPY --chown=10001:10001 server.py ./server.py
COPY --chown=10001:10001 static ./static
USER 10001:10001
EXPOSE 8765 10000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 CMD python -c 'import os,urllib.request; p=os.environ.get("NARYADAI_PORT") or os.environ.get("PORT") or "8765"; urllib.request.urlopen("http://127.0.0.1:"+p+"/api/health",timeout=2)'
CMD ["python", "server.py", "--host", "0.0.0.0", "--db", "/data/naryadai.sqlite3"]
