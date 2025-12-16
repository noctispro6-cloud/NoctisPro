from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from .models import Notification

@login_required
def notification_list(request):
    """List notifications"""
    notifications = Notification.objects.filter(recipient=request.user).select_related('study', 'facility').order_by('-created_at')[:200]
    return render(request, 'notifications/list.html', { 'notifications': notifications })

@login_required
def api_notifications(request):
    """API endpoint for notifications"""
    notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:50]
    data = [{
        'id': n.id,
        'title': n.title,
        'message': n.message,
        'is_read': n.is_read,
        'created_at': n.created_at.isoformat(),
        'study_id': n.study_id,
        'facility': n.facility.name if n.facility else None,
        'priority': n.priority,
    } for n in notifications]
    return JsonResponse({'notifications': data})

@login_required
def api_unread_count(request):
    """API endpoint to get unread notifications count"""
    user = request.user
    unread_count = Notification.objects.filter(recipient=user, is_read=False).count()
    return JsonResponse({'count': unread_count})

@login_required
def mark_read(request, notification_id):
    """Mark a notification as read and redirect back to list"""
    notif = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    if not notif.is_read:
        notif.is_read = True
        from django.utils import timezone
        notif.read_at = timezone.now()
        notif.save(update_fields=['is_read', 'read_at'])
    return redirect('notifications:notification_list')


@login_required
@require_POST
def api_mark_read(request, notification_id: int):
    """Mark a notification as read (JSON)."""
    notif = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    if not notif.is_read:
        from django.utils import timezone
        notif.is_read = True
        notif.read_at = timezone.now()
        notif.save(update_fields=['is_read', 'read_at'])
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({'ok': True, 'id': notif.id, 'unread_count': unread_count})


@login_required
@require_POST
def api_mark_all_read(request):
    """Mark all notifications as read for current user (JSON)."""
    from django.utils import timezone
    qs = Notification.objects.filter(recipient=request.user, is_read=False)
    updated = qs.update(is_read=True, read_at=timezone.now())
    return JsonResponse({'ok': True, 'updated': updated, 'unread_count': 0})
