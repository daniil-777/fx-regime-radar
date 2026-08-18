# FX Regime Radar — the Streamlit app as one self-contained image (rule 8: it only READS artifacts).
# Build from the repo root:  docker build -f deploy/Dockerfile -t fxradar-app .
# Runs on amd64 and arm64 (Oracle Ampere A1): every dependency ships aarch64 wheels, nothing compiles.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 radar

WORKDIR /app

# dependencies first (cached layer); `-e .` in requirements.txt needs the package source present
COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install -r requirements.txt

# the app + the artifacts it reads. In production these three folders are ALSO bind-mounted from the
# git checkout on the host (deploy/docker-compose.yml) so a nightly `git pull` refreshes them
# without rebuilding; copying them here keeps a plain `docker run` self-contained too.
COPY .streamlit ./.streamlit
COPY app ./app
COPY data ./data
COPY models ./models
COPY reports ./reports

RUN chown -R radar:radar /app
USER radar
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fs http://127.0.0.1:8501/_stcore/health || exit 1
CMD ["streamlit", "run", "app/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
