#!/bin/sh
# Запуск на хостинге (Render): миграции, демо-данные, администратор, затем сервер.
set -e
python manage.py migrate --noinput
python manage.py seed_demo
python manage.py createsuperuser --noinput || true
exec gunicorn config.wsgi:application -c gunicorn.conf.py
