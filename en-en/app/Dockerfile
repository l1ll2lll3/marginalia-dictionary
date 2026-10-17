FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dict.db.gz .
COPY server.py .
COPY start.sh .
COPY static/ static/
RUN chmod +x start.sh

EXPOSE 8080
CMD ["./start.sh"]
