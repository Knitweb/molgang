# MOLGANG backend — the always-on Python bar (serves the API; the static web/ UI
# can be served from here too, or hosted separately at e.g. https://5mart.ml/molgang/).
#
#   docker build -t molgang .
#   docker run -p 8080:8080 -v molgang-data:/data molgang
#
FROM python:3.12-slim

# git is needed to pull the knitweb engine (pulse); build tools for any wheels.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git build-essential \
 && rm -rf /var/lib/apt/lists/*

# The knitweb engine that MOLGANG runs on (the `knitweb` package).
RUN git clone --depth 1 https://github.com/knitweb/pulse /pulse

# MOLGANG itself.
WORKDIR /app
COPY . /app

# Install the engine + MOLGANG (editable so both stay importable).
RUN pip install --no-cache-dir -e /pulse -e .

# Persistent state lives in /data — mount a volume here (Fly volume / Render disk).
RUN mkdir -p /data
ENV MOLGANG_PORT=8080
EXPOSE 8080

# `serve` keeps a live Bar + the JSON API. CORS defaults to '*' so the static UI
# at a different origin can call it; tighten with `--cors https://5mart.ml` if wanted.
CMD ["sh", "-c", "molgang serve --port ${MOLGANG_PORT:-8080} --world /data/world.json --db /data/reg.db"]
