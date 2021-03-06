import newrelic.agent  # See https://bit.ly/2xBVKBH
import os
newrelic.agent.initialize() if os.getenv("NEW_RELIC", False) else {}  # noqa: E402
import sys
import traceback
import gunicorn

workers = 4
worker_class = "eventlet"
worker_connections = 256
bind = "0.0.0.0:{}".format(os.getenv("PORT"))
accesslog = '-'
gunicorn.SERVER_SOFTWARE = 'Internal Web Server'


def on_starting(server):
    server.log.info("Starting Notifications API")


def worker_abort(worker):
    worker.log.info("worker received ABORT {}".format(worker.pid))
    for threadId, stack in sys._current_frames().items():
        worker.log.error(''.join(traceback.format_stack(stack)))


def on_exit(server):
    server.log.info("Stopping Notifications API")


def worker_int(worker):
    worker.log.info("worker: received SIGINT {}".format(worker.pid))
