# Test runner image for system tests: API tests (pytest, requests/httpx/websockets) and web UI tests
# (selenium with headless chromium). Runs as a pod in the test namespace and reaches molior at http://web:8000.
# Kept separate from tests/system/test.Dockerfile, so the molior test image does not carry chromium.
#
# Built by tests/system/system-tests.sh. By hand (from the repo root):
#   docker build -f tests/system/test-web.Dockerfile -t molior-test-web:dev .
#
# Chromium and its driver come from Debian (chromium, chromium-driver): /usr/bin/chromium, /usr/bin/chromedriver.
FROM debian:trixie-slim

RUN export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get full-upgrade -y && \
    apt-get install -y --no-install-recommends \
        chromium chromium-driver fonts-dejavu-core \
        python3 python3-selenium \
        python3-pytest python3-pytest-xdist python3-pytest-timeout python3-junit.xml \
        python3-requests python3-httpx python3-websockets \
        ca-certificates curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 7778 -m --shell /bin/sh --home-dir /home/tester tester

COPY tests/system /tests/system

ENV CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER=/usr/bin/chromedriver \
    MOLIOR_URL=http://web:8000

USER tester
WORKDIR /tests/system
CMD ["sleep", "infinity"]
