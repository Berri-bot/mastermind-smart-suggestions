FROM python:3.9-slim-bullseye

# Install prerequisites and Oracle JDK 17
RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    wget \
    tar \
    && curl -fsSL https://download.oracle.com/java/17/archive/jdk-17.0.11_linux-x64_bin.tar.gz -o /tmp/jdk-17.tar.gz \
    && mkdir -p /usr/lib/jvm \
    && tar -xzf /tmp/jdk-17.tar.gz -C /usr/lib/jvm \
    && rm /tmp/jdk-17.tar.gz \
    && ln -s /usr/lib/jvm/jdk-17.0.11/bin/java /usr/bin/java \
    && ln -s /usr/lib/jvm/jdk-17.0.11/bin/javac /usr/bin/javac \
    && java -version \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/jdk-17.0.11
ENV PATH="${JAVA_HOME}/bin:${PATH}"

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download and extract JDT LS explicitly
RUN mkdir -p /app/jdtls \
    && wget https://download.eclipse.org/jdtls/milestones/1.36.0/jdt-language-server-1.36.0-202405301306.tar.gz -O /tmp/jdtls.tar.gz \
    && tar -xzf /tmp/jdtls.tar.gz -C /app/jdtls \
    && rm /tmp/jdtls.tar.gz \
    && ls -l /app/jdtls/plugins/org.eclipse.equinox.launcher_*.jar \
    && ls -l /app/jdtls/config_linux

# Copy application source code
COPY src/ .

ENV PYTHONPATH=/app
ENV WORKSPACE_DIR=/workspaces

# Create workspace directory with permissive permissions
RUN mkdir -p /workspaces && chmod 777 /workspaces

# Install tini for proper signal handling
RUN apt-get update && apt-get install -y tini \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8001

ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--ws-ping-interval", "20", "--ws-ping-timeout", "60"]