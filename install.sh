#!/usr/bin/env bash

sudo mkdir /app
sudo chown user /app

cp -r src /app
cp envfile_template /app/envfile
cp requirements.txt /app
cp pyproject.toml /app
cp config.json /app
cp settings.json /app

crontab crontab_file

cd /app || exit
python -m venv venv
source /app/venv/bin/activate
pip install -r requirements.txt


