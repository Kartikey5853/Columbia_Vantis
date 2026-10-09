FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN (sed -i 's/Components: main$/Components: main contrib non-free non-free-firmware/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true) \
    && (sed -i 's/main$/main contrib non-free non-free-firmware/g' /etc/apt/sources.list 2>/dev/null || true) \
    && apt-get update \
    && apt-get install -y --no-install-recommends xvfb xauth unrar rar unar p7zip-full \
    && rm -rf /var/lib/apt/lists/*

RUN playwright install --with-deps chromium

COPY . .

ENV PORT=10000

CMD ["sh", "-c", "xvfb-run -a -s '-screen 0 1024x768x16' uvicorn api:app --host 0.0.0.0 --port ${PORT:-10000} --timeout-graceful-shutdown 120"]