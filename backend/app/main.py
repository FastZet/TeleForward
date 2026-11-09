
"""
TeleForward application entry point.

Uvicorn imports the application instance from this module.
"""

from app.core.application import create_application


app = create_application()
