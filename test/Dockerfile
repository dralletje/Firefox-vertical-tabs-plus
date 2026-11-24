FROM debian:trixie-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends firefox-esr python3 python3-selenium curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ARG GECKODRIVER=v0.37.1
RUN arch="$(dpkg --print-architecture)"; \
    case "$arch" in arm64) a=linux-aarch64 ;; amd64) a=linux64 ;; *) echo "unsupported $arch"; exit 1 ;; esac; \
    curl -fsSL "https://github.com/mozilla/geckodriver/releases/download/${GECKODRIVER}/geckodriver-${GECKODRIVER}-${a}.tar.gz" \
      | tar xz -C /usr/local/bin

WORKDIR /work
CMD ["python3", "test/run_tests.py"]
