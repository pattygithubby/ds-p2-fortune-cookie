FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8 \
    PIP_NO_CACHE_DIR=1

# Install dependencies first so this layer is cached between code changes
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-deps .

# 8080: website (TCP), 9000: Bully election (UDP)
EXPOSE 8080 9000/udp

CMD ["python", "-m", "fortune"]
