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

try:
    from channels.routing import ProtocolTypeRouter, URLRouter
    from channels.auth import AuthMiddlewareStack
    from channels.security.websocket import AllowedHostsOriginValidator
    import chat.routing
    import notifications.routing

    application = ProtocolTypeRouter({
        "http": django_asgi_app,
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
    application = django_asgi_app
