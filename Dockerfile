FROM python:3.9-slim

RUN apt-get update && \
    apt-get install -y openjdk-17-jdk wget && \
    rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
# Clear any potential client.port to force stdin/stdout
ENV client_port=""

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY download_jdtls.sh .
RUN chmod +x download_jdtls.sh && ./download_jdtls.sh && \
    rm download_jdtls.sh

COPY src/ .

ENV PYTHONPATH=/app
ENV WORKSPACE_DIR=/workspaces

RUN apt-get update && apt-get install -y tini
ENTRYPOINT ["tini", "--"]

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--ws-ping-interval", "20", "--ws-ping-timeout", "60", "--timeout-keep-alive", "120"]