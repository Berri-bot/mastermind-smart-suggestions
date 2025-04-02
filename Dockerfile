FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install JDK 21
RUN curl -L -o jdk.tar.gz "https://download.oracle.com/java/21/archive/jdk-21_linux-x64_bin.tar.gz" \
    && mkdir -p /app/lsp/java/jdk-21 \
    && tar -xzf jdk.tar.gz -C /app/lsp/java/jdk-21 --strip-components=1 \
    && rm jdk.tar.gz \
    && chmod -R 755 /app/lsp/java/jdk-21

# Install JDT Language Server
RUN curl -L -o jdtls.tar.gz "https://download.eclipse.org/jdtls/milestones/1.36.0/jdt-language-server-1.36.0-202405301306.tar.gz" \
    && mkdir -p /app/lsp/java/jdt-language-server-1.36.0 \
    && tar -xzf jdtls.tar.gz -C /app/lsp/java/jdt-language-server-1.36.0 \
    && rm jdtls.tar.gz \
    && chmod -R 755 /app/lsp/java/jdt-language-server-1.36.0

COPY . /app

# Set environment variables
ENV JAVA_HOME=/app/lsp/java/jdk-21
ENV JDT_HOME=/app/lsp/java/jdt-language-server-1.36.0
ENV PATH=$JAVA_HOME/bin:$PATH
ENV WORKSPACE=/app/workspace

# Create workspace directory
RUN mkdir -p /app/workspace && chmod -R 755 /app/workspace

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]