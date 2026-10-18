# Cloud / server image: the CRM web app. Run it with docker-compose.yml (adds PostgreSQL + HTTPS).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY crm ./crm
COPY haz_crm.py .
RUN useradd --system --uid 1000 crm && mkdir -p /data /backups && chown crm /data /backups
USER crm
EXPOSE 8080
CMD ["python", "haz_crm.py", "--server", "--no-browser", "--host", "0.0.0.0", "--port", "8080", \
     "--data", "/data", "--backup-dir", "/backups"]
