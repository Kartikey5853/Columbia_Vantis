FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get install -y --no-install-recommends xvfb xauth && rm -rf /var/lib/apt/lists/*

RUN playwright install --with-deps chromium

COPY . .

CMD ["xvfb-run", "-a", "-s", "-screen 0 1024x768x16", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "10000", "--timeout-graceful-shutdown", "120"]