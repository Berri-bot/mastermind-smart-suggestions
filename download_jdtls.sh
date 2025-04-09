#!/bin/bash
set -e

JDTLS_VERSION="1.36.0"
JDTLS_TIMESTAMP="202405301306"
URL="https://www.eclipse.org/downloads/download.php?file=/jdtls/milestones/$JDTLS_VERSION/jdt-language-server-$JDTLS_VERSION-$JDTLS_TIMESTAMP.tar.gz"

echo "Downloading JDT LS version $JDTLS_VERSION from Eclipse"
wget --quiet "$URL" -O jdtls.tar.gz || { echo "Download failed"; exit 1; }

echo "Extracting JDT LS to /app/jdtls"
mkdir -p /app/jdtls
tar -xzf jdtls.tar.gz -C /app/jdtls || { echo "Extraction failed"; exit 1; }

echo "Cleaning up downloaded tar file"
rm jdtls.tar.gz

echo "JDT LS setup complete"