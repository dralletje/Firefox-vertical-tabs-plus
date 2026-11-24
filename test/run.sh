#!/bin/sh
# Build the test image and run the end-to-end tests in headless Firefox.
set -e
cd "$(dirname "$0")/.."
docker build -q -t new-tab-first-position-test test >/dev/null
exec docker run --rm -v "$PWD:/work:ro" new-tab-first-position-test
