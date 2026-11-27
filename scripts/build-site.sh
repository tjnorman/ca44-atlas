#!/usr/bin/env bash
# Assemble the published site: the static page in site/ plus the data files it reads.
# Cloudflare Pages runs this on every commit to main (output folder: _site).
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf _site
mkdir -p _site
cp -R site/. _site/
rm -rf _site/data
cp -R data/ca-44 _site/data
echo "Built _site with $(find _site -type f | wc -l) files."
