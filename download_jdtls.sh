#!/bin/bash
set -e

JDTLS_VERSION="1.36.0"
JDTLS_TIMESTAMP="202405301306"
URL="https://download.eclipse.org/jdtls/milestones/$JDTLS_VERSION/jdt-language-server-$JDTLS_VERSION-$JDTLS_TIMESTAMP.tar.gz"
TARGET_DIR="/app/jdtls"

echo "Downloading JDT LS from $URL"
if ! wget "$URL" -O jdtls.tar.gz; then
    echo "Download failed"
    exit 1
fi

echo "Verifying download integrity..."
if ! tar -tzf jdtls.tar.gz >/dev/null; then
    echo "Downloaded file is corrupt or invalid"
    exit 1
fi

echo "Extracting to $TARGET_DIR"
mkdir -p "$TARGET_DIR"
if ! tar -xzf jdtls.tar.gz -C "$TARGET_DIR"; then
    echo "Extraction failed"
    exit 1
fi

echo "Verifying extracted files..."
REQUIRED_FILES=(
    "$TARGET_DIR/plugins/org.eclipse.equinox.launcher_*.jar"
    "$TARGET_DIR/config_linux"
    "$TARGET_DIR/features"
)

for file in "${REQUIRED_FILES[@]}"; do
    if ! ls $file >/dev/null 2>&1; then
        echo "Missing required file/directory: $file"
        exit 1
    fi
done

rm jdtls.tar.gz
echo "JDT LS setup completed successfully"
ls -lR "$TARGET_DIR"