"""
ASGI config for noctis_pro project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'noctis_pro.settings')

# For now, use simple HTTP ASGI application until channels are properly configured
django_asgi_app = get_asgi_application()

# Optional FastAPI acceleration for hot image endpoints.
# If FastAPI isn't installed, we silently fall back to Django views.
http_app = django_asgi_app
try:
    from noctis_pro.fastapi_image_app import fastapi_app as _fastapi_image_app

    async def http_app(scope, receive, send):  # type: ignore[no-redef]
        """
        Route only the expensive PNG render endpoint to FastAPI.
        Everything else stays on the existing Django ASGI app.
        """
        try:
            path = (scope.get("path") or "")
            method = (scope.get("method") or "GET").upper()
            if (
                scope.get("type") == "http"
                and method == "GET"
                and path.startswith("/dicom-viewer/api/image/")
                and path.endswith("/render.png")
            ):
                return await _fastapi_image_app(scope, receive, send)
        except Exception:
            # Never block requests due to router errors
            pass
        return await django_asgi_app(scope, receive, send)
except ImportError:
    http_app = django_asgi_app

try:
    from channels.routing import ProtocolTypeRouter, URLRouter
    from channels.auth import AuthMiddlewareStack
    from channels.security.websocket import AllowedHostsOriginValidator
    import chat.routing
    import notifications.routing

    application = ProtocolTypeRouter({
        "http": http_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                URLRouter([
                    *chat.routing.websocket_urlpatterns,
                    *notifications.routing.websocket_urlpatterns,
                ])
            )
        ),
    })
except ImportError:
    # Fallback to simple HTTP application if channels dependencies are not available
    application = http_app
