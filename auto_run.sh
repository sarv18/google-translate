#!/bin/sh
cd /home/code

#gunicorn
#gunicorn main:app --workers 2 --timeout 300 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:3131

# uvicorn
uvicorn main:app --host 0.0.0.0 --port 5000 #--reload