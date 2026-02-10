"""Compatibility shim.

Some API modules import `app.core.celery_app.celery_app`, while the project
stores the actual Celery app in `app.tasks.celery_app`.
"""

from app.tasks.celery_app import celery_app

__all__ = ["celery_app"]
