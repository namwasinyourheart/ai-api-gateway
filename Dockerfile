FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 13101

CMD ["uvicorn", "ai_gateway:app", "--host", "0.0.0.0", "--port", "13101"]
