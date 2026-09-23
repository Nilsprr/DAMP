import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.environ.get("DAMP_SECRET_KEY", "dev-insecure-change-me")
    # Default (instance/damp.db) is filled in by create_app, since it needs the instance path.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DAMP_DATABASE_URL")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("DAMP_SECURE_COOKIES") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    WTF_CSRF_TIME_LIMIT = None  # token lives as long as the session
    RATELIMIT_ENABLED = True
    TIMEZONE = "Europe/Stockholm"
