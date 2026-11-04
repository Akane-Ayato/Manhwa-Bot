import os

from flask import Flask

app = Flask(__name__)


@app.route("/")
def hello():
    return "Hello World"


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    # Only for running this file directly; in production bot.py starts it
    # through gunicorn (so importing `app` must NOT start a server).
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
