# real-PA duplex API. CPU only: STT/TTS/VAD run through sherpa-onnx on CPU;
# the LLM is a separate OpenAI-compatible server (deploy/docker-compose.yml: llm).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

WORKDIR /opt/real-pa
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --extra audio --no-dev --no-install-project
COPY src ./src
COPY scripts ./scripts
RUN uv sync --locked --extra audio --no-dev

# Models and configuration are mounted, never baked into the image.
RUN useradd --system --uid 10001 --home /opt/real-pa realpa
USER realpa
ENV PATH=/opt/real-pa/.venv/bin:$PATH
EXPOSE 18484
ENTRYPOINT ["real-pa"]
CMD ["api", "/workspace/real-pa/worker.toml", "--host", "0.0.0.0", "--port", "18484", "--origin", "http://localhost:18484"]
