FROM python:3.10-slim

# RUN apt-get update && \
#     apt-get install -y --no-install-recommends \
#     git \
#     maven \
#     && rm -rf /var/lib/apt/lists/*

# RUN apt-get update && apt-get install -y curl 

RUN apt-get update && apt-get install -y wget && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install wget and other dependencies

RUN wget --no-check-certificate -O jdk-21.tar.gz "https://download.oracle.com/java/21/archive/jdk-21_linux-x64_bin.tar.gz" && \
    tar -xzf jdk-21.tar.gz && \
    rm jdk-21.tar.gz && \
    mv jdk-21 /app/lsp/java/jdk-21.0.2 && \
    # Ensure /usr/bin/java and /usr/bin/javac point to the correct location
    ln -sf /app/lsp/java/jdk-21.0.2/bin/java /usr/bin/java && \
    ln -sf /app/lsp/java/jdk-21.0.2/bin/javac /usr/bin/javac

# Download the JDT Language Server 1.36
RUN wget --content-disposition -O jdtls.tar.gz "https://www.eclipse.org/downloads/download.php?file=/jdtls/milestones/1.36.0/jdt-language-server-1.36.0-202405301306.tar.gz" && \
    mkdir -p /app/lsp/java/jdt-language-server-1.36.0 && \
    tar -xzf jdtls.tar.gz -C /app/lsp/java/jdt-language-server-1.36.0 && \
    rm jdtls.tar.gz && \
    chmod -R 755 /app/lsp/java/jdt-language-server-1.36.0

# Set JAVA_HOME environment variable
ENV JAVA_HOME=/app/lsp/java/jdk-21.0.2
ENV JDT_HOME=/app/lsp/java/jdt-language-server-1.36.0
ENV PATH="${JAVA_HOME}/bin:${PATH}"

COPY . .

#Expose port
EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
