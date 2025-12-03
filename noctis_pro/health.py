"""
Health check views for NoctisPro
"""

import json
import time
from django.http import JsonResponse, HttpResponse
from django.db import connection
from django.conf import settings
from django.core.cache import cache
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@require_http_methods(["GET"])
def health_check(request):
    """
    Comprehensive health check endpoint
    Returns HTTP 200 if all systems are healthy
    """
    start_time = time.time()
    health_status = {
        'status': 'healthy',
        'timestamp': time.time(),
        'checks': {}
    }
    
    overall_healthy = True
    
    # Database check
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        health_status['checks']['database'] = {
            'status': 'healthy',
            'message': 'Database connection successful'
        }
    except Exception as e:
        health_status['checks']['database'] = {
            'status': 'unhealthy',
            'message': f'Database error: {str(e)}'
        }
        overall_healthy = False
    
    # Cache check
    try:
        cache_key = 'health_check_test'
        cache.set(cache_key, 'test_value', 10)
        cached_value = cache.get(cache_key)
        
        # Handle DummyCache which always returns None
        if 'DummyCache' in str(type(cache._cache)):
            health_status['checks']['cache'] = {
                'status': 'healthy',
                'message': 'Cache (DummyCache) configured correctly'
            }
        elif cached_value == 'test_value':
            health_status['checks']['cache'] = {
                'status': 'healthy',
                'message': 'Cache working correctly'
            }
        else:
            health_status['checks']['cache'] = {
                'status': 'warning',
                'message': 'Cache test failed but system functional'
            }
            # Don't mark as unhealthy for cache issues in development
    except Exception as e:
        health_status['checks']['cache'] = {
            'status': 'warning',
            'message': f'Cache check failed: {str(e)} (system still functional)'
        }
        # Don't mark as unhealthy for cache issues
    
    # Disk space check
    try:
        import shutil
        total, used, free = shutil.disk_usage('/')
        free_gb = free // (1024**3)
        used_percent = (used / total) * 100
        
        if free_gb < 5:
            health_status['checks']['disk_space'] = {
                'status': 'unhealthy',
                'message': f'Low disk space: {free_gb}GB free'
            }
            overall_healthy = False
        else:
            health_status['checks']['disk_space'] = {
                'status': 'healthy',
                'message': f'Disk space OK: {free_gb}GB free ({used_percent:.1f}% used)'
            }
    except Exception as e:
        health_status['checks']['disk_space'] = {
            'status': 'unhealthy',
            'message': f'Disk space check failed: {str(e)}'
        }
        overall_healthy = False
    
    # Set overall status
    health_status['status'] = 'healthy' if overall_healthy else 'unhealthy'
    health_status['response_time_ms'] = int((time.time() - start_time) * 1000)
    
    # Return appropriate HTTP status
    status_code = 200 if overall_healthy else 503
    
    return JsonResponse(health_status, status=status_code)

@csrf_exempt
@require_http_methods(["GET"])
def simple_health_check(request):
    """
    Simple health check for load balancers
    Just returns HTTP 200 OK
    """
    return HttpResponse("OK", content_type="text/plain")

@csrf_exempt
@require_http_methods(["GET"])
def ready_check(request):
    """
    Readiness check - verifies the application is ready to serve traffic
    """
    try:
        # Quick database check
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        
        return HttpResponse("READY", content_type="text/plain")
    except Exception as e:
        return HttpResponse(f"NOT READY: {str(e)}", 
                          content_type="text/plain", 
                          status=503)

@csrf_exempt
@require_http_methods(["GET"])
def live_check(request):
    """
    Liveness check - verifies the application is running
    """
    return HttpResponse("ALIVE", content_type="text/plain")