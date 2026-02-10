import os
from dotenv import load_dotenv
load_dotenv()

from celery import Celery
import os

REDIS_BROKER = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://redis:6379/1')

celery_app = Celery('tgshop_tasks', broker=REDIS_BROKER, backend=CELERY_BACKEND)

# Optional: load configuration from environment
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
)

# Auto-discover tasks in this package
celery_app.autodiscover_tasks(['app.tasks.celery_tasks'])

