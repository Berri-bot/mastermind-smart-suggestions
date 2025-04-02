FROM python:3.10-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN curl -L -o jdk.tar.gz "https://download.oracle.com/java/21/archive/jdk-21_linux-x64_bin.tar.gz" \
    && mkdir -p /app/lsp/java/jdk-21 \
    && tar -xzf jdk.tar.gz -C /app/lsp/java/jdk-21 --strip-components=1 \
    && rm jdk.tar.gz \
    && chmod +x /app/lsp/java/jdk-21/bin/java

RUN curl -L -o jdtls.tar.gz "https://www.eclipse.org/downloads/download.php?file=/jdtls/milestones/1.36.0/jdt-language-server-1.36.0-202405301306.tar.gz" \
    && mkdir -p /app/lsp/java/jdt-language-server-1.36.0 \
    && tar -xzf jdtls.tar.gz -C /app/lsp/java/jdt-language-server-1.36.0 \
    && rm jdtls.tar.gz

COPY . /app

ENV JAVA_HOME=/app/lsp/java/jdk-21
ENV PATH=$JAVA_HOME/bin:$PATH

RUN mkdir -p /app/workspace

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]