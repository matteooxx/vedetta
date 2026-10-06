FROM python:3.12-slim

# A small base image on purpose: image pulls on the target platform are cancelled
# after 1200 seconds, and a large base has exceeded that on a slow day.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY vedetta ./vedetta
RUN pip install --no-cache-dir .

COPY config ./config

# Runs as a non-root user with a read-only root filesystem; only /data/runtime is
# writable. Keep every write inside it.
USER 1000:1000
ENV VEDETTA_ROOT=/data

ENTRYPOINT ["vedetta", "--root", "/data", "--config-dir", "/app/config"]
CMD ["run"]
