import logging
import os
from contextlib import closing

from flask import Flask, g, make_response
from uuid import uuid4
from flask_cors import CORS
from kombu.exceptions import OperationalError
from redis.exceptions import RedisError
from werkzeug.exceptions import RequestEntityTooLarge
#from flask_debugtoolbar import DebugToolbarExtension
from wannadb_web.limits import MAX_REQUEST_BYTES, MAX_UPLOAD_FILES, QueueFullError, WorkLimitError
from wannadb_web.log_filters import _RedactLegacyTaskStatus
from wannadb_web.postgres.migrate import MIGRATIONS
from wannadb_web.postgres.util import connectPG
from wannadb_web.Redis.util import connectRedis
from wannadb_web.routing.core import core_routes
from wannadb_web.routing.user import user_management
from wannadb_web.routing.files import main_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

logging.getLogger("werkzeug").addFilter(_RedactLegacyTaskStatus())
app = Flask(__name__)


# Combine Flask and Celery configs
app.config.from_mapping(
	SECRET_KEY=os.environ.get('WANNA_DB_JWT_SECRET'),
	MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
	MAX_FORM_PARTS=MAX_UPLOAD_FILES + 16,
	DEBUG=False,
	DEBUG_TB_ENABLED=False,
	DEBUG_TB_PROFILER_ENABLED=False,
	broker_url=os.environ.get("CELERY_BROKER_URL"),
	task_ignore_result=True,
	PREFERRED_URL_SCHEME='https',
	#PROPAGATE_EXCEPTIONS=True
)
# Register the Extensions
# #toolbar = DebugToolbarExtension(app)



# Register the blueprints
app.register_blueprint(main_routes)
app.register_blueprint(user_management)
app.register_blueprint(core_routes)

if os.environ.get('WANNADB_PRODUCTION') != '1':
	CORS(
	    app,
	    supports_credentials=True,
	    origins=["http://localhost:3000"],
	    resources={r"/*": {"origins": "http://localhost:3000"}}
	)


@app.before_request
def assign_request_id():
	g.request_id = uuid4().hex


@app.after_request
def add_request_id(response):
	request_id = getattr(g, "request_id", None)
	if request_id:
		response.headers["X-Request-ID"] = request_id
	return response


@app.errorhandler(500)
def unexpected_error(error):
	app.logger.error("Unexpected request failure. request_id=%s", getattr(g, "request_id", "-"))
	return make_response({"error": "The request failed."}, 500)


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(error):
	return make_response({"error": "The request exceeds the upload size or form part limit."}, 413)


@app.errorhandler(WorkLimitError)
def work_limit_reached(error):
	return make_response({"error": str(error)}, 413)


@app.errorhandler(QueueFullError)
def queue_full(error):
	return make_response({"error": str(error)}, 429)


@app.errorhandler(RedisError)
@app.errorhandler(OperationalError)
def queue_unavailable(error):
	return make_response({"error": "The task service is temporarily unavailable."}, 503)


@app.errorhandler(404)
def not_found_error(error):
	return make_response({'error': f'Not Found  \n {error}'}, 404)




@app.get('/')
@app.get('/health/live')
def liveness():
	return make_response({'status': 'live'}, 200, {'Cache-Control': 'no-store'})


@app.get('/health/ready')
def readiness():
	try:
		with closing(connectPG(connect_timeout=2)) as conn, conn.cursor() as cursor:
			cursor.execute("SET LOCAL statement_timeout = '2s'")
			cursor.execute("SELECT count(*), max(version) FROM public.wannadb_schema_migrations")
			migrated = cursor.fetchone() == (len(MIGRATIONS), len(MIGRATIONS))
		with closing(connectRedis()) as redis:
			ready = migrated and redis.ping()
	except Exception:
		ready = False
	return make_response({'status': 'ready' if ready else 'unavailable'},
		200 if ready else 503, {'Cache-Control': 'no-store'})
