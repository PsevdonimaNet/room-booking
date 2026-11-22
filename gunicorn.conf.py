import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("WEB_CONCURRENCY", "4"))
threads = int(os.environ.get("WEB_THREADS", "4"))
worker_class = "gthread"
timeout = 30


def child_exit(server, worker):
    """Нужно для метрик Prometheus в режиме нескольких процессов."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(worker.pid)
