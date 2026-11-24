#!/bin/sh
# Package everything in extension/ into ./new-tab-first-position-<version>.xpi
set -e
cd "$(dirname "$0")/extension"
version=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' manifest.json)
out="$(cd .. && pwd)/new-tab-first-position-$version.xpi"
rm -f "$out"
zip -q -r -X "$out" .
echo "$out"
