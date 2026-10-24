import multiprocessing
import os

bind = "0.0.0.0:8000"
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "gthread"
threads = int(os.getenv("GUNICORN_THREADS", 4))
timeout = 30
keepalive = 5
# Recicla workers periodicamente para conter vazamento de memória.
max_requests = 2000
max_requests_jitter = 200
accesslog = "-"
