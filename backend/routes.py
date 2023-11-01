import sys

# Add a dummy package to sys.modules to force Flask to be imported as a package
sys.modules['flask'] = sys.modules[__name__]

from flask import Flask

app = Flask(__name__)

@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"
