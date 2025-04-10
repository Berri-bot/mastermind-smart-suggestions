#!/bin/bash
set -e

JDTLS_VERSION="1.36.0"
JDTLS_TIMESTAMP="202405301306"
URL="https://download.eclipse.org/jdtls/milestones/$JDTLS_VERSION/jdt-language-server-$JDTLS_VERSION-$JDTLS_TIMESTAMP.tar.gz"

echo "Downloading JDT LS from $URL"
wget "$URL" -O jdtls.tar.gz || { echo "Download failed"; exit 1; }

mkdir -p /app/jdtls
tar -xzf jdtls.tar.gz -C /app/jdtls || { echo "Extraction failed"; exit 1; }

rm jdtls.tar.gz
echo "JDT LS setup complete"