FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0

COPY kalitehat ./kalitehat
RUN useradd --create-home kalitehat && mkdir veri && chown kalitehat veri
USER kalitehat

EXPOSE 5050
# Veritabanı yoksa demo verisini kurar. Tek süreç + iş parçacıkları: SQLite tek yazıcıyla çalışır.
CMD ["sh", "-c", "[ -f veri/kalitehat.db ] || python -m kalitehat.ornek_veri; exec gunicorn -b 0.0.0.0:5050 -w 1 --threads 4 'kalitehat:create_app()'"]
