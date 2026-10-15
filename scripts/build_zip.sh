#!/usr/bin/env bash
# Gera dist/shc_nd.zip com o conteúdo de custom_components/shc_nd na raiz do
# ZIP: o formato da instalação manual (extrair em custom_components/shc_nd/).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist
rm -f dist/shc_nd.zip
(cd custom_components/shc_nd && zip -qr ../../dist/shc_nd.zip . -x '__pycache__/*' '*.pyc')
echo "dist/shc_nd.zip"
