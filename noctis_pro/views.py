"""
Views for NoctisPro core functionality - Deployment version
"""

import os
import mimetypes
from django.http import HttpResponse, Http404, FileResponse
from django.conf import settings
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views import View
from django.urls import re_path


class StaticFileView(View):
    """
    Custom static file view with proper MIME type handling
    """
    
    @method_decorator(cache_control(max_age=86400))  # 24 hours cache
    def get(self, request, path):
        """
        Serve static file with correct MIME type
        """
        # Security check - prevent directory traversal
        if '..' in path or path.startswith('/'):
            raise Http404("File not found")
        
        # Try static files first
        static_file_path = os.path.join(settings.STATIC_ROOT, path)
        if os.path.exists(static_file_path):
            file_path = static_file_path
        else:
            # Try staticfiles dirs
            for static_dir in settings.STATICFILES_DIRS:
                potential_path = os.path.join(static_dir, path)
                if os.path.exists(potential_path):
                    file_path = potential_path
                    break
            else:
                raise Http404("File not found")
        
        # Get MIME type with proper JavaScript handling
        content_type, _ = mimetypes.guess_type(file_path)
        
        # Fix JavaScript MIME type specifically
        if path.endswith('.js'):
            content_type = 'application/javascript'
        elif path.endswith('.css'):
            content_type = 'text/css'
        elif path.endswith('.json'):
            content_type = 'application/json'
        elif content_type is None:
            content_type = 'application/octet-stream'
        
        # Serve file with correct content type
        response = FileResponse(open(file_path, 'rb'), content_type=content_type)
        
        # Add security headers
        response['X-Content-Type-Options'] = 'nosniff'
        
        return response


@require_http_methods(["GET"])
def connection_info(request):
    """
    Return connection information for debugging
    """
    info = {
        'deployment': 'noctis_pro_deployment',
        'static_url': settings.STATIC_URL,
        'static_root': settings.STATIC_ROOT,
    }
    
    return HttpResponse(
        f"<h1>Connection Info</h1><pre>{info}</pre>",
        content_type='text/html'
    )