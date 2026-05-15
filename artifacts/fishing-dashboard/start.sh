#!/bin/bash
cd "$(dirname "$0")"
exec gunicorn --bind "0.0.0.0:${PORT:-5000}" --workers 4 app:app
