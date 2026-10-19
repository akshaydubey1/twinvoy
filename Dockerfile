# Runs the meeting-join server (no camera needed once you have enrolled).
#   docker build -t twinvoy .
#   docker run -e RECALL_API_KEY -e ANTHROPIC_API_KEY -v ~/.twinvoy:/root/.twinvoy \
#     -p 8765:8765 twinvoy join <meeting-url> --public-url https://<tunnel>
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY twinvoy ./twinvoy
RUN pip install --no-cache-dir ".[brain]"
EXPOSE 8765
ENTRYPOINT ["twinvoy"]
