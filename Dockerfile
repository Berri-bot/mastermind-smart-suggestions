FROM python:3.9-slim-bullseye

# Install prerequisites and Oracle JDK 21
RUN apt-get update && apt-get install -y ca-certificates curl wget tar && \
    curl -fsSL https://download.oracle.com/java/21/archive/jdk-21_linux-x64_bin.tar.gz -o /tmp/jdk-21.tar.gz && \
    mkdir -p /usr/lib/jvm && \
    tar -xzf /tmp/jdk-21.tar.gz -C /usr/lib/jvm && \
    rm /tmp/jdk-21.tar.gz && \
    ln -s /usr/lib/jvm/jdk-21/bin/java /usr/bin/java && \
    ln -s /usr/lib/jvm/jdk-21/bin/javac /usr/bin/javac && \
    java -version && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy and run the JDT LS download script
COPY download_jdtls.sh .
RUN chmod +x download_jdtls.sh && ./download_jdtls.sh && \
    rm download_jdtls.sh

# Copy application source code
COPY src/ .

# Set environment variables 
ENV PYTHONPATH=/app
ENV WORKSPACE_DIR=/workspaces
ENV JAVA_HOME=/usr/lib/jvm/jdk-21
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Ensure /workspaces is writable
RUN mkdir -p /workspaces && chmod 777 /workspaces

# Install tini for proper signal handling
RUN apt-get update && apt-get install -y tini && \
    rm -rf /var/lib/apt/lists/*

# Health check to verify Java and JDT LS
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD java -version && test -f /app/jdtls/plugins/org.eclipse.equinox.launcher_*.jar || exit 1

# Use tini as entrypoint
ENTRYPOINT ["tini", "--"]

# Run the application with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--ws-ping-interval", "20", "--ws-ping-timeout", "60"]