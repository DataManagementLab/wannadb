import logging
import os

from celery import Celery

from wannadb_web.worker.tasks import BaseTask, DocumentBaseLoad, TestTask, InitManager, CreateDocumentBase

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

app = Celery(__name__)

app.conf.broker_url = os.environ.get("CELERY_BROKER_URL")

app.register_task(BaseTask)
app.register_task(TestTask)
app.register_task(InitManager)
app.register_task(CreateDocumentBase)
app.register_task(DocumentBaseLoad)
