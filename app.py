import logging
import os

from flask import Flask, make_response, render_template_string
from flask_cors import CORS
from flask_debugtoolbar import DebugToolbarExtension
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
CORS(app)
toolbar = DebugToolbarExtension(app)



# Register the blueprints
app.register_blueprint(main_routes)
app.register_blueprint(user_management)
app.register_blueprint(dev_routes)
app.register_blueprint(core_routes)


@app.errorhandler(404)
def not_found_error(error):
	return make_response({'error': f'Not Found  \n {error}'}, 404)




@app.route('/')
@app.route('/DEBUG')
def index():
	html_code = """
    <html lang="ts">
        <body>
            <form>
                <p>hello</p>
            </form>
        </body>
    </html>
    """
	return render_template_string(html_code)
