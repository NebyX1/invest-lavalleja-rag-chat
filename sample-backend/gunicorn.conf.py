import os

from prometheus_client import multiprocess


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


bind = f"0.0.0.0:{_int_env('PORT', 5000)}"

workers = _int_env("GUNICORN_WORKERS", 4)
worker_class = "gthread"
threads = _int_env("GUNICORN_THREADS", 4)

timeout = _int_env("GUNICORN_TIMEOUT", 60)
graceful_timeout = _int_env("GUNICORN_GRACEFUL_TIMEOUT", 30)
keepalive = _int_env("GUNICORN_KEEPALIVE", 5)

# Recicla workers para contener leaks
max_requests = _int_env("GUNICORN_MAX_REQUESTS", 1000)
max_requests_jitter = _int_env("GUNICORN_MAX_REQUESTS_JITTER", 100)

worker_tmp_dir = "/dev/shm"

capture_output = True
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

preload_app = False


def child_exit(server, worker):
    multiprocess.mark_process_dead(worker.pid)
