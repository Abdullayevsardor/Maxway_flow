web: python init_db.py && gunicorn main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:$PORT --timeout 120 --access-logfile -
