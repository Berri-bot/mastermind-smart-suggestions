FROM python:3.10-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    maven \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY lsp /app/lsp
COPY . .
RUN pip install --no-cache-dir -r requirements.txt "uvicorn[standard]" "python-lsp-server[all]"
RUN chmod +x /app/lsp/java/jdk-21.0.2/bin/java && \
    chmod +x /app/lsp/java/jdk-21.0.2/bin/javac

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
