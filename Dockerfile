FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --create-home --uid 10001 --shell /usr/sbin/nologin soccersnap

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# Install locked runtime dependencies first so this layer is cached
# independently of application source changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY README.md PROTOCOL.md ./
COPY src ./src
COPY docs ./docs

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable \
  && mkdir -p /data \
  && chown -R soccersnap:soccersnap /app /data

ENV PATH="/app/.venv/bin:$PATH"
ENV SOCCERSNAP_DATA_DIR=/data
ENV SOCCERSNAP_DATABASE_URL=sqlite:////data/soccersnap.db
ENV SOCCERSNAP_HOST=0.0.0.0
ENV SOCCERSNAP_PORT=7420

VOLUME ["/data"]
EXPOSE 7420

USER soccersnap
CMD ["soccersnap", "demo", "--host", "0.0.0.0", "--port", "7420"]
