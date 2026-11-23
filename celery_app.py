import logging
import os

from celery import Celery

from wannadb_web.worker.health import QueueHeartbeat

from wannadb_web.worker.tasks import BaseTask, DocumentBaseAddDocument, DocumentBaseConfirmMultipleNuggets, DocumentBaseConfirmNugget, DocumentBaseForgetMatches, DocumentBaseForgetMatchesForAttribute, DocumentBaseInteractiveTablePopulation, DocumentBaseLoad, DocumentBaseNoMatchForDocument, DocumentBaseRemoveDocument, DocumentBaseStartRanking, DocumentBaseStopMatching, DocumentBaseCloseFeedbackSession, DocumentBaseUpdateAttributes, DocumentBaseUpdateDocument, ReloadDocumentBaseTask, ReviewPublicSuggestion, TestTask, InitManager, CreateDocumentBase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

app = Celery(__name__)
app.steps["consumer"].add(QueueHeartbeat)

app.conf.broker_url = os.environ.get("CELERY_BROKER_URL")
app.conf.result_serializer = "json"
app.conf.task_ignore_result = False

app.register_task(BaseTask)
app.register_task(TestTask)
app.register_task(InitManager)
app.register_task(CreateDocumentBase)
app.register_task(DocumentBaseLoad)
app.register_task(DocumentBaseAddDocument)
app.register_task(DocumentBaseRemoveDocument)
app.register_task(DocumentBaseUpdateDocument)
app.register_task(DocumentBaseUpdateAttributes)
app.register_task(ReviewPublicSuggestion)
app.register_task(DocumentBaseForgetMatches)
app.register_task(DocumentBaseForgetMatchesForAttribute)
app.register_task(DocumentBaseInteractiveTablePopulation)
app.register_task(DocumentBaseConfirmNugget)
app.register_task(DocumentBaseConfirmMultipleNuggets)
app.register_task(DocumentBaseStartRanking)
app.register_task(ReloadDocumentBaseTask)
app.register_task(DocumentBaseNoMatchForDocument)
app.register_task(DocumentBaseStopMatching)
app.register_task(DocumentBaseCloseFeedbackSession)
