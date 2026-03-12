"""Parkaran Helper - Flask Application."""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template
from api.routes import api_bp

app = Flask(__name__)
app.register_blueprint(api_bp, url_prefix="/api")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/database")
def database():
    return render_template("database.html")


@app.route("/discover")
def discover():
    return render_template("discover.html")


@app.route("/builder")
def builder():
    return render_template("builder.html")


@app.route("/reviewer")
def reviewer():
    return render_template("reviewer.html")


@app.route("/occasions")
def occasions():
    return render_template("occasions.html")


if __name__ == "__main__":
    app.run(debug=True, port=5050)
