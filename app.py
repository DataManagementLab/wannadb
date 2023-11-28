# app.py
from flask import Flask
from flask_cors import CORS
from flask_app.endpoints import main_routes
from flask_app.user import user_management



app = Flask(__name__)
CORS(app)

# Register the blueprints
app.register_blueprint(main_routes)
app.register_blueprint(user_management)



@app.route('/')
def hello_world():
	return 'Hello'


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
        
      
