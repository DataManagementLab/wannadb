import logging
import os

from flask import Flask, make_response, render_template_string
from flask_cors import CORS
from kombu.exceptions import OperationalError
from redis.exceptions import RedisError
from werkzeug.exceptions import RequestEntityTooLarge
#from flask_debugtoolbar import DebugToolbarExtension
from wannadb_web.limits import MAX_REQUEST_BYTES, MAX_UPLOAD_FILES, QueueFullError, WorkLimitError
from wannadb_web.log_filters import _RedactLegacyTaskStatus
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

CORS(
    app,
    supports_credentials=True,
    origins=["http://localhost:3000"],
    resources={r"/*": {"origins": "http://localhost:3000"}}
)


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(error):
	return make_response({"error": "The request exceeds the upload size or form part limit."}, 413)


@app.errorhandler(WorkLimitError)
def work_limit_reached(error):
	return make_response({"error": str(error)}, 413)


@app.errorhandler(QueueFullError)
def queue_full(error):
	return make_response({"error": "The worker queue is full. Try again shortly."}, 429)


@app.errorhandler(RedisError)
@app.errorhandler(OperationalError)
def queue_unavailable(error):
	return make_response({"error": "The task service is temporarily unavailable."}, 503)


@app.errorhandler(404)
def not_found_error(error):
	return make_response({'error': f'Not Found  \n {error}'}, 404)




@app.route('/')
@app.route('/DEBUG')
def index():
	routes = [
		rule.rule for rule in app.url_map.iter_rules()
		if "dev" not in str(rule.rule)
	]
	html_code = f"""
	<html lang="ts">
		<title>WannaDB Backend</title>
		<body>
			<form>
				<h1>Backend for WannaDB</h1>
				<p>
				The following routes can be accessed:<br>
				{'<br>'.join(routes)}
				</p
			</form>
		</body>
	</html>
	"""
	return render_template_string(html_code)
