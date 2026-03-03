FROM python:3.12-slim

WORKDIR /app

COPY common/ /tmp/common/
RUN pip install --no-cache-dir /tmp/common/

COPY scout/pyproject.toml .
RUN pip install --no-cache-dir .

COPY scout/src/ src/

CMD ["python", "-m", "scout.main"]
