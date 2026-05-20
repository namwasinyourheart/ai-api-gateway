FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install ffmpeg for audio transcoding
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

EXPOSE 13102

CMD ["uvicorn", "ai_gateway:app", "--host", "0.0.0.0", "--port", "13102"]
