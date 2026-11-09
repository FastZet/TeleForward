
"""
TeleForward backend entry point.

Exports the FastAPI application instance for Uvicorn.
"""

from app.core.application import create_application


# Main ASGI application instance.
app = create_application()
