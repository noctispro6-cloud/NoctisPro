"""
Middleware for NoctisPro - Image optimization for slow connections
"""

import os
import io
from PIL import Image
from django.http import HttpResponse, FileResponse
from django.conf import settings
from django.core.files.storage import default_storage
import mimetypes


class ImageOptimizationMiddleware:
    """
    Middleware to optimize images for slow internet connections
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Check if this is an image request
        if self.should_optimize_image(request, response):
            response = self.optimize_image_response(request, response)
        
        return response
    
    def should_optimize_image(self, request, response):
        """
        Determine if we should optimize this image
        """
        # Check if response is a file response
        if not isinstance(response, (HttpResponse, FileResponse)):
            return False
        
        # Check if it's an image
        content_type = response.get('Content-Type', '')
        if not content_type.startswith('image/'):
            return False
        
        # Check if client wants optimization (from query params)
        optimize = request.GET.get('optimize', 'true').lower()
        if optimize == 'false':
            return False
        
        # Check connection speed hint from query params
        connection = request.GET.get('connection', 'auto').lower()
        
        return True
    
    def optimize_image_response(self, request, response):
        """
        Optimize image based on connection speed and requirements
        """
        try:
            # Get optimization parameters from request
            quality = int(request.GET.get('quality', '70'))  # Default 70% quality
            max_width = int(request.GET.get('max_width', '1920'))
            max_height = int(request.GET.get('max_height', '1080'))
            format_type = request.GET.get('format', 'auto').upper()
            connection = request.GET.get('connection', 'auto').lower()
            
            # Adjust settings based on connection type
            if connection == 'slow':
                quality = min(quality, 50)
                max_width = min(max_width, 800)
                max_height = min(max_height, 600)
            elif connection == 'mobile':
                quality = min(quality, 60)
                max_width = min(max_width, 1200)
                max_height = min(max_height, 800)
            
            # Get image content
            if hasattr(response, 'streaming_content'):
                content = b''.join(response.streaming_content)
            else:
                content = response.content
            
            if not content:
                return response
            
            # Open and process image
            img = Image.open(io.BytesIO(content))
            
            # Convert RGBA to RGB if saving as JPEG
            if img.mode in ('RGBA', 'LA') and format_type in ('JPEG', 'auto'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'LA':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            
            # Resize if needed
            if img.width > max_width or img.height > max_height:
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            
            # Determine output format
            if format_type == 'auto':
                # Use WebP for better compression if supported
                if 'webp' in request.META.get('HTTP_ACCEPT', '').lower():
                    output_format = 'WEBP'
                    content_type = 'image/webp'
                else:
                    output_format = 'JPEG'
                    content_type = 'image/jpeg'
            else:
                output_format = format_type
                content_type = f'image/{format_type.lower()}'
            
            # Save optimized image
            output = io.BytesIO()
            
            if output_format == 'WEBP':
                img.save(output, format='WEBP', quality=quality, optimize=True)
            elif output_format == 'JPEG':
                img.save(output, format='JPEG', quality=quality, optimize=True)
            elif output_format == 'PNG':
                img.save(output, format='PNG', optimize=True)
            else:
                img.save(output, format=output_format, quality=quality if output_format != 'PNG' else None)
            
            # Create optimized response
            optimized_content = output.getvalue()
            optimized_response = HttpResponse(optimized_content, content_type=content_type)
            
            # Copy headers from original response
            for header, value in response.items():
                if header.lower() not in ['content-length', 'content-type']:
                    optimized_response[header] = value
            
            # Add optimization headers
            optimized_response['X-Image-Optimized'] = 'true'
            optimized_response['X-Original-Size'] = str(len(content))
            optimized_response['X-Optimized-Size'] = str(len(optimized_content))
            optimized_response['X-Compression-Ratio'] = f"{(1 - len(optimized_content)/len(content))*100:.1f}%"
            
            # Add cache headers for optimized images
            optimized_response['Cache-Control'] = 'public, max-age=86400'  # 24 hours
            
            return optimized_response
            
        except Exception as e:
            # If optimization fails, return original response
            print(f"Image optimization failed: {e}")
            return response


class SlowConnectionOptimizationMiddleware:
    """
    Middleware to detect slow connections and adjust content accordingly
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Detect connection speed from various headers
        self.detect_connection_speed(request)
        
        response = self.get_response(request)
        
        # Add optimization hints to HTML responses
        if response.get('Content-Type', '').startswith('text/html'):
            self.add_optimization_script(request, response)
        
        return response
    
    def detect_connection_speed(self, request):
        """
        Detect connection speed from various indicators
        """
        # Check for explicit connection parameter
        connection = request.GET.get('connection')
        if connection:
            request.connection_speed = connection
            return
        
        # Check for network information from headers
        downlink = request.META.get('HTTP_DOWNLINK')
        effective_type = request.META.get('HTTP_ECT')  # Effective Connection Type
        rtt = request.META.get('HTTP_RTT')  # Round Trip Time
        
        # Estimate connection speed
        if effective_type:
            if effective_type in ['slow-2g', '2g']:
                request.connection_speed = 'slow'
            elif effective_type == '3g':
                request.connection_speed = 'medium'
            else:
                request.connection_speed = 'fast'
        elif downlink:
            try:
                downlink_mbps = float(downlink)
                if downlink_mbps < 1.5:
                    request.connection_speed = 'slow'
                elif downlink_mbps < 10:
                    request.connection_speed = 'medium'
                else:
                    request.connection_speed = 'fast'
            except ValueError:
                request.connection_speed = 'auto'
        else:
            request.connection_speed = 'auto'
    
    def add_optimization_script(self, request, response):
        """
        Add JavaScript for client-side optimization
        """
        if not hasattr(response, 'content'):
            return
        
        connection_speed = getattr(request, 'connection_speed', 'auto')
        
        optimization_script = f"""
        <script>
        // NoctisPro Image Optimization for Slow Connections
        (function() {{
            const connectionSpeed = '{connection_speed}';
            const isSlowConnection = connectionSpeed === 'slow' || 
                                   (navigator.connection && 
                                    navigator.connection.effectiveType && 
                                    ['slow-2g', '2g'].includes(navigator.connection.effectiveType));
            
            // Optimize images based on connection
            function optimizeImages() {{
                const images = document.querySelectorAll('img');
                images.forEach(img => {{
                    if (img.dataset.optimized) return; // Already optimized
                    
                    const src = img.src;
                    if (!src) return;
                    
                    // Add optimization parameters
                    const url = new URL(src, window.location.href);
                    
                    if (isSlowConnection) {{
                        url.searchParams.set('quality', '50');
                        url.searchParams.set('max_width', '800');
                        url.searchParams.set('max_height', '600');
                        url.searchParams.set('connection', 'slow');
                    }} else if (connectionSpeed === 'medium') {{
                        url.searchParams.set('quality', '60');
                        url.searchParams.set('max_width', '1200');
                        url.searchParams.set('connection', 'medium');
                    }}
                    
                    url.searchParams.set('optimize', 'true');
                    
                    // Update image source if different
                    if (url.href !== img.src) {{
                        img.src = url.href;
                        img.dataset.optimized = 'true';
                    }}
                }});
            }}
            
            // Optimize on page load
            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', optimizeImages);
            }} else {{
                optimizeImages();
            }}
            
            // Optimize dynamically loaded images
            const observer = new MutationObserver(function(mutations) {{
                mutations.forEach(function(mutation) {{
                    mutation.addedNodes.forEach(function(node) {{
                        if (node.nodeType === 1) {{ // Element node
                            if (node.tagName === 'IMG') {{
                                setTimeout(optimizeImages, 100);
                            }} else if (node.querySelectorAll) {{
                                const images = node.querySelectorAll('img');
                                if (images.length > 0) {{
                                    setTimeout(optimizeImages, 100);
                                }}
                            }}
                        }}
                    }});
                }});
            }});
            
            observer.observe(document.body, {{
                childList: true,
                subtree: true
            }});
            
            // Add connection info to page
            if (isSlowConnection) {{
                console.log('🐌 Slow connection detected - images will be optimized');
            }}
        }})();
        </script>
        """
        
        # Insert script before closing </body> tag
        content = response.content.decode('utf-8')
        if '</body>' in content:
            content = content.replace('</body>', optimization_script + '</body>')
            response.content = content.encode('utf-8')


import time
from django.http import JsonResponse
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


class SessionTimeoutMiddleware(MiddlewareMixin):
    """
    Middleware to handle automatic logout on inactivity
    """
    
    def process_request(self, request):
        # Skip processing for ASGI requests or when user attribute doesn't exist
        if hasattr(request, 'scope') or not hasattr(request, 'user'):
            return None
        
        # Check if user is authenticated
        try:
            if not request.user.is_authenticated:
                return None
        except AttributeError:
            # User attribute not properly initialized
            return None
        
        # Skip timeout for AJAX requests to avoid interrupting operations
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # Update last activity for AJAX requests but don't timeout
            request.session['last_activity'] = time.time()
            return None
        
        # Check if this is a session timeout check request
        if request.path == '/accounts/session-status/':
            return None
        
        # Get session timeout settings
        timeout_seconds = getattr(settings, 'SESSION_COOKIE_AGE', 1800)  # Default 30 minutes
        warning_seconds = getattr(settings, 'SESSION_TIMEOUT_WARNING', 300)  # Default 5 minutes
        
        # Get last activity time
        last_activity = request.session.get('last_activity')
        current_time = time.time()
        
        if last_activity:
            # Check if session has expired
            time_since_activity = current_time - last_activity
            
            if time_since_activity > timeout_seconds:
                # Session expired - logout user
                logout(request)
                if request.headers.get('Accept', '').startswith('application/json'):
                    return JsonResponse({
                        'error': 'Session expired due to inactivity',
                        'redirect': reverse('accounts:login')
                    }, status=401)
                else:
                    return redirect('accounts:login')
        
        # Update last activity time
        request.session['last_activity'] = current_time
        
        return None


class SessionTimeoutWarningMiddleware(MiddlewareMixin):
    """
    Middleware to inject session timeout warning JavaScript
    """
    
    def process_response(self, request, response):
        # Only inject for authenticated users and HTML responses
        # Skip for ASGI requests
        if (hasattr(request, 'user') and not hasattr(request, 'scope') and 
            hasattr(response, 'content') and response.get('Content-Type', '').startswith('text/html')):
            try:
                if request.user.is_authenticated:
                    # Get timeout settings
                    timeout_seconds = getattr(settings, 'SESSION_COOKIE_AGE', 1800)
                    warning_seconds = getattr(settings, 'SESSION_TIMEOUT_WARNING', 300)
                    
                    # Get last activity
                    last_activity = request.session.get('last_activity', time.time())
                    current_time = time.time()
                    remaining_time = timeout_seconds - (current_time - last_activity)
                    
                    # Inject session timeout JavaScript
                    timeout_script = f"""
            <script>
            (function() {{
                let sessionTimeoutSeconds = {timeout_seconds};
                let warningSeconds = {warning_seconds};
                let remainingTime = {max(0, int(remaining_time))};
                let warningShown = false;
                let logoutTimer = null;
                let warningTimer = null;
                
                function showTimeoutWarning() {{
                    if (warningShown) return;
                    warningShown = true;
                    
                    const warningDiv = document.createElement('div');
                    warningDiv.id = 'session-timeout-warning';
                    warningDiv.style.cssText = `
                        position: fixed;
                        top: 20px;
                        right: 20px;
                        background: #ff6b6b;
                        color: white;
                        padding: 15px 20px;
                        border-radius: 8px;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                        z-index: 10000;
                        max-width: 350px;
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        font-size: 14px;
                        line-height: 1.4;
                    `;
                    
                    let timeLeft = Math.floor(warningSeconds);
                    warningDiv.innerHTML = `
                        <div style="font-weight: bold; margin-bottom: 8px;">⚠️ Session Timeout Warning</div>
                        <div>Your session will expire in <span id="countdown">` + timeLeft + `</span> seconds due to inactivity.</div>
                        <div style="margin-top: 10px;">
                            <button onclick="extendSession()" style="background: white; color: #ff6b6b; border: none; padding: 5px 12px; border-radius: 4px; cursor: pointer; font-weight: bold;">Stay Logged In</button>
                        </div>
                    `;
                    
                    document.body.appendChild(warningDiv);
                    
                    // Countdown timer
                    const countdown = setInterval(() => {{
                        timeLeft--;
                        const countdownEl = document.getElementById('countdown');
                        if (countdownEl) {{
                            countdownEl.textContent = timeLeft;
                        }}
                        if (timeLeft <= 0) {{
                            clearInterval(countdown);
                        }}
                    }}, 1000);
                }}
                
                function forceLogout() {{
                    alert('Your session has expired due to inactivity. You will be redirected to the login page.');
                    window.location.href = '/login/';
                }}
                
                window.extendSession = function() {{
                    // Make a request to extend session
                    fetch('/accounts/session-extend/', {{
                        method: 'POST',
                        headers: {{
                            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || '',
                            'Content-Type': 'application/json',
                        }},
                        credentials: 'same-origin'
                    }})
                    .then(response => response.json())
                    .then(data => {{
                        if (data.success) {{
                            // Remove warning and reset timers
                            const warning = document.getElementById('session-timeout-warning');
                            if (warning) warning.remove();
                            warningShown = false;
                            
                            // Reset timers
                            clearTimeout(logoutTimer);
                            clearTimeout(warningTimer);
                            setupTimeoutTimers();
                        }}
                    }})
                    .catch(error => {{
                        console.error('Error extending session:', error);
                    }});
                }};
                
                function setupTimeoutTimers() {{
                    // Set warning timer
                    const warningTime = Math.max(0, (remainingTime - warningSeconds) * 1000);
                    warningTimer = setTimeout(showTimeoutWarning, warningTime);
                    
                    // Set logout timer
                    logoutTimer = setTimeout(forceLogout, remainingTime * 1000);
                }}
                
                // Reset timers on user activity
                let activityEvents = ['mousedown', 'mousemove', 'keypress', 'scroll', 'touchstart', 'click'];
                let activityTimeout = null;
                
                function resetActivity() {{
                    if (activityTimeout) clearTimeout(activityTimeout);
                    activityTimeout = setTimeout(() => {{
                        // Send keep-alive request
                        fetch('/accounts/session-keep-alive/', {{
                            method: 'POST',
                            headers: {{
                                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]')?.value || '',
                                'X-Requested-With': 'XMLHttpRequest'
                            }},
                            credentials: 'same-origin'
                        }});
                    }}, 60000); // Send keep-alive every minute of activity
                }}
                
                // Add activity listeners
                activityEvents.forEach(event => {{
                    document.addEventListener(event, resetActivity, true);
                }});
                
                // Initialize timers if there's remaining time
                if (remainingTime > 0) {{
                    setupTimeoutTimers();
                }}
            }})();
                    </script>
                    """
                    
                    try:
                        content = response.content.decode('utf-8')
                        if '</body>' in content:
                            content = content.replace('</body>', timeout_script + '</body>')
                            response.content = content.encode('utf-8')
                            response['Content-Length'] = len(response.content)
                    except (UnicodeDecodeError, AttributeError):
                        # Skip if we can't decode the content
                        pass
            except AttributeError:
                # Skip if user attribute is not properly initialized
                pass
        
        return response