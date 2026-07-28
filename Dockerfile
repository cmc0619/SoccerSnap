FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --create-home --uid 10001 --shell /usr/sbin/nologin soccersnap

WORKDIR /app
COPY pyproject.toml README.md PROTOCOL.md ./
COPY src ./src
COPY docs ./docs

RUN pip install --no-cache-dir . \
  && mkdir -p /data \
  && chown -R soccersnap:soccersnap /app /data

ENV SOCCERSNAP_DATA_DIR=/data
ENV SOCCERSNAP_DATABASE_URL=sqlite:////data/soccersnap.db
ENV SOCCERSNAP_HOST=0.0.0.0
ENV SOCCERSNAP_PORT=7420

VOLUME ["/data"]
EXPOSE 7420

USER soccersnap
CMD ["soccersnap", "demo", "--host", "0.0.0.0", "--port", "7420"]
