FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md PROTOCOL.md ./
COPY src ./src
COPY docs ./docs

RUN pip install --no-cache-dir .

ENV SOCCERSNAP_DATA_DIR=/data
ENV SOCCERSNAP_DATABASE_URL=sqlite:////data/soccersnap.db
ENV SOCCERSNAP_HOST=0.0.0.0
ENV SOCCERSNAP_PORT=7420

VOLUME ["/data"]
EXPOSE 7420

CMD ["soccersnap", "demo", "--host", "0.0.0.0", "--port", "7420"]
