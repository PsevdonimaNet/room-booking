import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"  # PORT задаёт хостинг (Render)
workers = int(os.environ.get("WEB_CONCURRENCY", "4"))
threads = int(os.environ.get("WEB_THREADS", "4"))
worker_class = "gthread"
timeout = 30


def child_exit(server, worker):
    """Нужно для метрик Prometheus в режиме нескольких процессов."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(worker.pid)
