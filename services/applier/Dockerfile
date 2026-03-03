FROM python:3.12-slim

WORKDIR /app

# Playwright system dependencies + LaTeX
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libxcb1 libxkbcommon0 \
    libatspi2.0-0 libx11-6 libxcomposite1 libxdamage1 libxext6 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    texlive-latex-base texlive-latex-recommended texlive-latex-extra \
    && rm -rf /var/lib/apt/lists/*

COPY common/ /tmp/common/
RUN pip install --no-cache-dir /tmp/common/

COPY applier/pyproject.toml .
RUN pip install --no-cache-dir . && \
    playwright install chromium

COPY applier/src/ src/

CMD ["python", "-m", "applier.main"]
