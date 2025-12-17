from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.contrib.auth.forms import AuthenticationForm
from django.conf import settings
from .models import User, UserSession, Facility
import json

def _get_or_create_session_key(request) -> str:
    """
    Ensure a session key exists for the current request.

    Django may not create/persist a session key until the response cycle,
    so accessing `request.session.session_key` immediately after `login()`
    can be None. We best-effort save to force key creation.
    """
    try:
        key = getattr(request, "session", None) and request.session.session_key
        if key:
            return key
        # Force session creation/persistence
        request.session.save()
        return request.session.session_key or ""
    except Exception:
        return ""

def _should_auto_create_admin_on_first_access() -> bool:
    """
    Historically this project auto-created an admin on visiting the login page.
    That's risky (side effects on GET) and can surface confusing "setup" behavior.

    Keep it as an explicit opt-in for demo/dev environments only.
    """
    val = str(getattr(settings, "AUTO_CREATE_ADMIN_ON_FIRST_ACCESS", "") or "").strip().lower()
    return val in {"1", "true", "yes", "on"}

def _bootstrap_admin_user_if_enabled() -> None:
    """
    Best-effort optional bootstrap of an initial admin user.

    IMPORTANT: This must never raise inside a request handler.
    """
    if not _should_auto_create_admin_on_first_access():
        return

    try:
        # Only bootstrap if there are no privileged accounts yet.
        if User.objects.filter(is_superuser=True).exists() or User.objects.filter(is_staff=True).exists():
            return

        domain = getattr(settings, 'DOMAIN_NAME', '') or 'noctis-pro.com'
        email = f'admin@{domain}'
        username = getattr(settings, "BOOTSTRAP_ADMIN_USERNAME", "admin")
        password = getattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "") or ""

        # If no password is provided, do NOT create a credentialed account.
        # This avoids accidentally exposing a predictable default password.
        if not password:
            return

        su, created = User.objects.get_or_create(username=username, defaults={'email': email})

        changed = False
        if created:
            su.set_password(password)
            changed = True

        if not getattr(su, 'is_superuser', False):
            su.is_superuser = True
            su.is_staff = True
            changed = True

        # Some installs rely on role/is_verified (custom User model).
        if hasattr(su, 'role') and getattr(su, 'role', None) != 'admin':
            su.role = 'admin'
            changed = True
        if hasattr(su, 'is_verified') and not getattr(su, 'is_verified', False):
            su.is_verified = True
            changed = True

        if hasattr(su, 'email') and email and not getattr(su, 'email', ''):
            su.email = email
            changed = True

        if changed:
            su.save()
    except Exception:
        # Silent best-effort by design (never block login page rendering).
        pass

def login_view(request):
    """Custom login view with enhanced security tracking"""
    # Avoid surprising side-effects on the login page; bootstrap is explicit opt-in.
    _bootstrap_admin_user_if_enabled()
    if request.user.is_authenticated:
        return redirect('worklist:dashboard')
    
    # Clear any existing messages on GET request to prevent accumulation
    if request.method == 'GET':
        # Clear any existing messages
        list(messages.get_messages(request))
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        # Allow superusers/staff to bypass verification to prevent lockout on fresh setups
        if user and user.is_active and (user.is_verified or getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False)):
            # Track login session
            login(request, user)
            
            # Get client information
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            ip_address = get_client_ip(request)
            
            # Update user login tracking
            try:
                user.last_login_ip = ip_address
                user.save(update_fields=['last_login_ip', 'updated_at'] if hasattr(user, 'updated_at') else ['last_login_ip'])
            except Exception:
                # Never block login due to tracking errors
                pass
            
            # Create session record
            try:
                session_key = _get_or_create_session_key(request)
                # `session_key` is non-nullable; store an empty string if key creation fails.
                UserSession.objects.create(
                    user=user,
                    session_key=session_key,
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            except Exception:
                # Never block login due to session-audit errors
                pass
            
            # Redirect all users to the worklist dashboard after login
            return redirect('worklist:dashboard')
        else:
            # Clear any existing messages before adding error
            list(messages.get_messages(request))
            # Only show a single generic error for any failure
            messages.error(request, 'Invalid username or password')
    
    return render(request, 'accounts/login.html', {'hide_navbar': True})

@login_required
def logout_view(request):
    """Custom logout view with session cleanup"""
    try:
        # Update session record
        session = UserSession.objects.get(
            user=request.user,
            session_key=request.session.session_key,
            is_active=True
        )
        session.logout_time = timezone.now()
        session.is_active = False
        session.save()
    except UserSession.DoesNotExist:
        pass
    
    logout(request)
    # Do not show any success/info messages on the login page
    return redirect('accounts:login')

@login_required
def profile_view(request):
    """User profile view and update"""
    user = request.user

    # Ensure notification preferences exist
    pref = None
    try:
        from notifications.models import NotificationPreference
        pref, _ = NotificationPreference.objects.get_or_create(user=user)
    except Exception:
        pref = None
    
    if request.method == 'POST':
        # Update profile information
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.email = request.POST.get('email', user.email)
        user.phone = request.POST.get('phone', user.phone)
        user.specialization = request.POST.get('specialization', user.specialization)
        user.save()

        # Update notification preference delivery method
        try:
            if pref:
                method = (request.POST.get('preferred_method') or pref.preferred_method or 'web').strip()
                valid = {c[0] for c in pref.DELIVERY_METHODS}
                if method in valid:
                    pref.preferred_method = method
                    pref.save(update_fields=['preferred_method', 'updated_at'])
        except Exception:
            pass
        
        messages.success(request, 'Profile updated successfully.')
        return redirect('accounts:profile')
    
    context = {
        'user': user,
        'notification_pref': pref,
        'recent_sessions': UserSession.objects.filter(user=user).order_by('-login_time')[:10]
    }
    return render(request, 'accounts/profile.html', context)

@csrf_exempt
def check_session(request):
    """AJAX endpoint to check if user session is still valid"""
    if request.user.is_authenticated:
        return JsonResponse({
            'authenticated': True,
            'user': {
                'id': request.user.id,
                'username': request.user.username,
                'role': request.user.role,
                'facility': request.user.facility.name if request.user.facility else None
            }
        })
    return JsonResponse({'authenticated': False})

def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

@login_required
def change_password(request):
    """Change user password"""
    if request.method == 'POST':
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if not request.user.check_password(current_password):
            messages.error(request, 'Current password is incorrect.')
            return redirect('accounts:profile')
        
        if new_password != confirm_password:
            messages.error(request, 'New passwords do not match.')
            return redirect('accounts:profile')
        
        if len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            return redirect('accounts:profile')
        
        request.user.set_password(new_password)
        request.user.save()
        
        # Re-authenticate user to maintain session
        user = authenticate(request, username=request.user.username, password=new_password)
        if user:
            login(request, user)
        
        messages.success(request, 'Password changed successfully.')
        return redirect('accounts:profile')
    
    return redirect('accounts:profile')

def user_api_info(request):
    """API endpoint for user information"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Not authenticated'}, status=401)
    
    user = request.user
    return JsonResponse({
        'id': user.id,
        'username': user.username,
        'full_name': f"{user.first_name} {user.last_name}",
        'email': user.email,
        'role': user.role,
        'facility': {
            'id': user.facility.id,
            'name': user.facility.name
        } if user.facility else None,
        'permissions': {
            'can_edit_reports': user.can_edit_reports(),
            'can_manage_users': user.can_manage_users(),
            'is_admin': user.is_admin(),
            'is_radiologist': user.is_radiologist(),
            'is_facility_user': user.is_facility_user(),
        }
    })
