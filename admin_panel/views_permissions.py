from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from accounts.models import User
from .utils import (
    get_user_caps, set_user_caps, DEFAULT_CAPS, load_capabilities,
    get_role_toggles, set_role_toggles
)


def is_admin(user):
    return user.is_authenticated and user.is_admin()


@login_required
@user_passes_test(is_admin)
def permissions_dashboard(request):
    users = User.objects.order_by('username').all()
    if request.method == 'POST' and request.POST.get('_roles') == '1':
        updates = {
            'admin': { 'ai_visible': request.POST.get('role_admin_ai_visible') == 'on' },
            'radiologist': { 'ai_visible': request.POST.get('role_radiologist_ai_visible') == 'on' },
            'facility': { 'ai_visible': request.POST.get('role_facility_ai_visible') == 'on' },
        }
        set_role_toggles(updates)
        messages.success(request, 'Role-based AI visibility updated')
    caps_store = load_capabilities()
    # Build a simple table of users and capabilities
    table = []
    for u in users:
        caps = get_user_caps(u.username)
        table.append({
            'user': u,
            'caps': caps,
        })
    return render(request, 'admin_panel/permissions.html', {
        'users_table': table,
        'cap_keys': list(DEFAULT_CAPS.keys()),
        'role_toggles': get_role_toggles(),
    })


@login_required
@user_passes_test(is_admin)
def edit_user_permissions(request, username: str):
    user = get_object_or_404(User, username=username)
    if request.method == 'POST':
        caps_update = {}
        for key in DEFAULT_CAPS.keys():
            caps_update[key] = (request.POST.get(key) == 'on')
        set_user_caps(user.username, caps_update)
        messages.success(request, f'Permissions updated for {user.username}')
        return redirect('admin_panel:permissions_dashboard')
    caps = get_user_caps(user.username)
    return render(request, 'admin_panel/edit_permissions.html', {
        'user_obj': user,
        'caps': caps,
        'cap_keys': list(DEFAULT_CAPS.keys()),
    })

