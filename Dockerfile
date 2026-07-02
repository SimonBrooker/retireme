FROM python:3.12-alpine

RUN apk update && apk upgrade && rm -rf /var/cache/apk/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data
VOLUME ["/data"]

ENV DATABASE_PATH=/data/retirement.db
ENV FLASK_APP=run.py
# UPDATE APP_VERSION in app/__init__.py before building a new release
ENV APP_VERSION=2.5.0
EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "run:app"]
