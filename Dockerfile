# Bước 1: build giao diện web
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Bước 2: máy chủ Python + TeX Live (XeLaTeX)
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends texlive-xetex texlive-latex-extra latexmk lmodern fonts-lmodern \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=web /src/nganhangde/web ./src/nganhangde/web
RUN pip install --no-cache-dir '.[postgres]'
COPY examples ./examples
EXPOSE 8000
CMD ["nhd", "serve", "--host", "0.0.0.0", "--port", "8000"]
