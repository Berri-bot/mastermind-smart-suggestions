FROM python:3.9-slim

# Install system dependencies
# For process monitoring
RUN apt-get update && \
    apt-get install -y \
    openjdk-17-jre-headless \
    wget \
    procps && \
    rm -rf /var/lib/apt/lists/*

# Create workspace directory
RUN mkdir -p /workspaces && chmod 777 /workspaces

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY download_jdtls.sh .
RUN chmod +x download_jdtls.sh && ./download_jdtls.sh && \
    rm download_jdtls.sh

COPY src/ .

ENV PYTHONPATH=/app
ENV WORKSPACE_DIR=/workspaces

# Install tini for proper signal handling
RUN apt-get update && apt-get install -y tini
ENTRYPOINT ["tini", "--"]

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--lifespan", "on"]