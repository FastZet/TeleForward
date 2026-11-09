
"""
TeleForward API schemas package.

Contains Pydantic request and response schemas used by the
application's API endpoints and service interfaces.

Schema modules should be imported explicitly by consumers:

    from app.schemas.auth import InitialSetupRequest
    from app.schemas.forwarding import ForwardingRuleCreateRequest

Avoid eager imports here. They can introduce circular dependencies,
unnecessary module loading, and import-time side effects.
"""

__all__: list[str] = []
