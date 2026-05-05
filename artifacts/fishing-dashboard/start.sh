#!/bin/bash
cd /home/runner/workspace/artifacts/fishing-dashboard
exec gunicorn --bind "0.0.0.0:${PORT:-5000}" --workers 2 app:app
