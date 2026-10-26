# Bước 1: build giao diện web
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Bước 2: máy chủ Python + TeX Live (XeLaTeX), cùng bản TeX Live 2023 đã dùng để kiểm thử
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv texlive-xetex texlive-latex-extra latexmk lmodern fonts-lmodern \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=web /src/nganhangde/web ./src/nganhangde/web
RUN pip install --no-cache-dir '.[postgres,ai]'
COPY examples ./examples
EXPOSE 8000
CMD ["nhd", "serve", "--host", "0.0.0.0", "--port", "8000"]
