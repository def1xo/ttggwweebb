from .celery_app import celery_app as celery
try:
    from . import celery_tasks
except Exception:
    import sys, traceback
    print("Warning: failed to import app.tasks.celery_tasks:", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)

__all__ = ["celery"]
