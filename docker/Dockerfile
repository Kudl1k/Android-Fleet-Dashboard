FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ADB_MDNS_AUTO_CONNECT=0
RUN apt-get update && apt-get install -y --no-install-recommends adb && rm -rf /var/lib/apt/lists/*
# Official architecture-independent Android server; no desktop renderer or transcoder.
ADD https://github.com/Genymobile/scrcpy/releases/download/v3.3.4/scrcpy-server-v3.3.4 /opt/scrcpy/scrcpy-server
RUN echo '8588238c9a5a00aa542906b6ec7e6d5541d9ffb9b5d0f6e1bc0e365e2303079e  /opt/scrcpy/scrcpy-server' | sha256sum -c - \
    && chmod 644 /opt/scrcpy/scrcpy-server
COPY docker/licenses/scrcpy-LICENSE /opt/scrcpy/LICENSE
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/src ./src
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 fleet \
    && install -d -m 700 -o fleet -g fleet /home/fleet/.android /var/lib/android-fleet
USER fleet
EXPOSE 8000
CMD ["uvicorn", "android_fleet.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--ws-max-size", "4096", "--ws-max-queue", "8"]
