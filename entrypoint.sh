#!/bin/sh
set -e

mkdir -p /app/data

python manage.py migrate --noinput
python manage.py seed_workshop_data

exec gunicorn workshop_timer.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120
