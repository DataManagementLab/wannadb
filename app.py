import logging
import os

from flask import Flask, make_response, render_template_string
from flask_cors import CORS
#from flask_debugtoolbar import DebugToolbarExtension
from wannadb_web.routing.core import core_routes
from wannadb_web.routing.dev import dev_routes
from wannadb_web.routing.user import user_management
from wannadb_web.routing.files import main_routes

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

app = Flask(__name__)


# Combine Flask and Celery configs
app.config.from_mapping(
	SECRET_KEY='secret!',
	DEBUG=True,
	DEBUG_TB_ENABLED=True,
	DEBUG_TB_PROFILER_ENABLED=True,
	broker_url=os.environ.get("CELERY_BROKER_URL"),
	task_ignore_result=True,
	PREFERRED_URL_SCHEME='https',
	#PROPAGATE_EXCEPTIONS=True
)
app.config['DEBUG'] = True
# Register the Extensions
# #toolbar = DebugToolbarExtension(app)



# Register the blueprints
app.register_blueprint(main_routes)
app.register_blueprint(user_management)
app.register_blueprint(dev_routes)
app.register_blueprint(core_routes)

CORS(app, origins=["*"], supports_credentials=True, resources={r"/*": {"origins": "*"}}) # Allow all origins for CORS, should be restricted in production



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
