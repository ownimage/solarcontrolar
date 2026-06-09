FROM docker.io/python:3.11-bookworm

SHELL ["/bin/bash", "-c"]

COPY . /app
WORKDIR /app

RUN apt update \
    && apt --no-install-recommends install -y cron sudo \
    && apt clean \
    && python -m venv venv \
    && ./venv/bin/pip install --upgrade pip \
    && ./venv/bin/pip install -r requirements.txt \
    && crontab crontab_file




