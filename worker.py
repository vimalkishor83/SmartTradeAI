"""
Background worker entry point — owns the scheduler and the market-data stream.

Run EXACTLY ONE of these per deployment, alongside any number of web
processes started with RUN_SCHEDULER=0:

    # the single worker (background jobs + exchange WebSocket ingest)
    RUN_SCHEDULER=1 python worker.py

    # web tier — scale these freely
    RUN_SCHEDULER=0 gunicorn --worker-class eventlet -w 4 wsgi:app

Why this exists: create_app() used to start the full APScheduler roster and the
Delta Exchange WebSocket ingest in *every* process, so running more than one
web worker duplicated all background work — multiplying outbound API polling,
nightly backups, model retrains and notification dispatch by the worker count.
That is why the Dockerfile was pinned to `-w 1`. Splitting the background role
into this process is what makes the web tier horizontally scalable.

This process binds no HTTP port. It emits Socket.IO events through the Redis
message queue (SOCKETIO_MESSAGE_QUEUE / REDIS_URL) so ticks it ingests still
reach browser clients connected to the web processes.
"""
import logging
import os
import signal
import sys
import threading

# Force the background role on regardless of ambient env, so this entrypoint
# can never accidentally start as a no-op web process.
os.environ["RUN_SCHEDULER"] = "1"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app import create_app  # noqa: E402
from app.extensions import scheduler  # noqa: E402

logger = logging.getLogger("worker")


def main():
    app = create_app()

    if os.environ.get("REDIS_URL") or os.environ.get("SOCKETIO_MESSAGE_QUEUE"):
        logger.info("Socket.IO message queue configured — emitted events will reach web processes.")
    else:
        logger.warning(
            "No REDIS_URL/SOCKETIO_MESSAGE_QUEUE set. Real-time events emitted by this "
            "worker will NOT reach clients connected to separate web processes. Set "
            "REDIS_URL when running the split web/worker topology."
        )

    jobs = scheduler.get_jobs() if getattr(scheduler, "running", False) else []
    logger.info("Background worker started with %d scheduled job(s).", len(jobs))
    for job in jobs:
        logger.info("  job=%s next_run=%s", job.id, getattr(job, "next_run_time", None))

    # Block until signalled. The scheduler and stream run on their own daemon
    # threads started during create_app(), so this thread just needs to stay
    # alive and shut them down cleanly on SIGTERM (container stop / k8s drain).
    stop = threading.Event()

    def _shutdown(signum, _frame):
        logger.info("Signal %s received — shutting down scheduler...", signum)
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            logger.exception("Scheduler shutdown failed")
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _shutdown)
        except (ValueError, OSError):
            # Not on the main thread, or unsupported on this platform.
            pass

    stop.wait()
    logger.info("Worker stopped.")


if __name__ == "__main__":
    main()
