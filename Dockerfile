FROM python:3.12-slim

# A small base image on purpose: image pulls on the target platform are cancelled
# after 1200 seconds, and a large base has exceeded that on a slow day.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY vedetta ./vedetta
# One image serves both roles: the scheduled run and the long-running interface.
# Two images would drift.
RUN pip install --no-cache-dir ".[ui]" waitress

# Shipped examples. The real configuration is bind-mounted at /data/config, which is
# also where the interface writes - so it must live outside the git worktree and be
# writable by this uid.
COPY config /app/config.defaults

USER 1000:1000
ENV VEDETTA_ROOT=/data VEDETTA_CONFIG_DIR=/data/config

ENTRYPOINT ["vedetta", "--root", "/data", "--config-dir", "/data/config"]
CMD ["run"]
