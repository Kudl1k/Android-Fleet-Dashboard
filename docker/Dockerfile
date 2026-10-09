FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ADB_MDNS_AUTO_CONNECT=0
RUN apt-get update && apt-get install -y --no-install-recommends adb && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/src ./src
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 fleet \
    && install -d -m 700 -o fleet -g fleet /home/fleet/.android /var/lib/android-fleet
USER fleet
EXPOSE 8000
CMD ["uvicorn", "android_fleet.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
