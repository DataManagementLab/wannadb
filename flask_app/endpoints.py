# main_routes.py
from flask import Blueprint

main_routes = Blueprint('main_routes', __name__)


@main_routes.route('/api')
def hello_world():
	return "Hello a"
