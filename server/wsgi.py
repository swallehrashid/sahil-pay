"""
WSGI entry point for production servers (gunicorn / uWSGI).

    gunicorn -w 3 -b 127.0.0.1:8000 wsgi:app

The app factory picks its config from APP_ENV (set APP_ENV=production in the
service's EnvironmentFile). This mirrors the module-level `app` in app.py; both
`wsgi:app` and `app:app` resolve to the same application object.
"""
from app import app

if __name__ == "__main__":
    app.run()
