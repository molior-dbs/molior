# Test runner image for system tests: API tests (pytest, requests, websockets) and web UI tests
# (selenium with headless chromium). Runs as a pod in the test namespace and reaches molior at http://web:8000.
# Kept separate from tests/system/test.Dockerfile, so the molior test image does not carry chromium.
#
# Built by tests/system/system-tests.sh. By hand (from the repo root):
#   docker build -f tests/system/test-web.Dockerfile -t molior-test-web:dev .
#
# Chromium and its driver come from Debian (chromium, chromium-driver): /usr/bin/chromium, /usr/bin/chromedriver.
# kubectl comes from Debian (kubernetes-client): the 1.4 validation tests read build logs in the molior container
# with kubectl exec, using the service account of the test runner pod (system-tests.sh).
FROM debian:trixie-slim

RUN export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get full-upgrade -y && \
    apt-get install -y --no-install-recommends \
        chromium chromium-driver fonts-dejavu-core \
        python3 python3-selenium \
        python3-pytest python3-pytest-timeout \
        python3-requests python3-websockets \
        ca-certificates curl kubernetes-client && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 7778 -m --shell /bin/sh --home-dir /home/tester tester

# only the test code: tests/system/molior-testing (1.4 input, contains secrets) stays out of the image
COPY tests/system/conftest.py tests/system/moliortest.py /tests/system/
COPY tests/system/smoke /tests/system/smoke
COPY tests/system/valid-1.4 /tests/system/valid-1.4

ENV CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER=/usr/bin/chromedriver \
    MOLIOR_URL=http://web:8000

USER tester
WORKDIR /tests/system
CMD ["sleep", "infinity"]
