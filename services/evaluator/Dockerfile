FROM python:3.12-slim

WORKDIR /app

COPY common/ /tmp/common/
RUN pip install --no-cache-dir /tmp/common/

COPY evaluator/pyproject.toml .
RUN pip install --no-cache-dir .

COPY evaluator/src/ src/

CMD ["python", "-m", "evaluator.main"]
