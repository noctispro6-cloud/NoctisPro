from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q, Count
from django.core.paginator import Paginator
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from accounts.models import User, Facility
from .utils import get_user_caps
from worklist.models import Study, Modality
from .models import SystemConfiguration, AuditLog, SystemUsageStatistics
import json
import re
from django.utils.crypto import get_random_string


def is_admin(user):
    """Check if user is admin"""
    return user.is_authenticated and user.is_admin()

def _standardize_aetitle(source: str) -> str:
    """Generate a DICOM-compliant AE Title (<=16 chars, A-Z 0-9 _), ensure uniqueness."""
    base = re.sub(r"[^A-Z0-9 ]+", "", (source or "").upper()).strip().replace(" ", "_") or "FACILITY"
    aet = base[:16]
    suffix = 1
    # Ensure uniqueness (case-insensitive)
    while Facility.objects.filter(ae_title__iexact=aet).exists():
        tail = f"_{suffix}"
        aet = (base[: 16 - len(tail)] + tail)[:16] or f"FAC_{suffix:02d}"
        suffix += 1
        if suffix > 99:
            break
    return aet

@login_required
@user_passes_test(is_admin)
def dashboard(request):
    """Admin dashboard with system overview"""
    # Get system statistics
    total_users = User.objects.count()
    total_facilities = Facility.objects.count()
    total_studies = Study.objects.count()
    active_users_today = User.objects.filter(last_login__date=timezone.now().date()).count()
    
    # Recent activities
    recent_studies = Study.objects.select_related('patient', 'facility', 'modality').order_by('-upload_date')[:10]
    recent_users = User.objects.order_by('-date_joined')[:10]
    
    # System usage by modality
    modality_stats = Study.objects.values('modality__name').annotate(
        count=Count('id')
    ).order_by('-count')[:5]
    
    context = {
        'total_users': total_users,
        'total_facilities': total_facilities,
        'total_studies': total_studies,
        'active_users_today': active_users_today,
        'recent_studies': recent_studies,
        'recent_users': recent_users,
        'modality_stats': modality_stats,
    }
    
    return render(request, 'admin_panel/dashboard.html', context)

@login_required
@user_passes_test(is_admin)
def system_logs(request):
    """Placeholder: system logs view."""
    messages.info(request, 'System Logs view is under construction.')
    return dashboard(request)

@login_required
@user_passes_test(is_admin)
def settings_view(request):
    """Placeholder: settings view."""
    messages.info(request, 'Settings view is under construction.')
    return dashboard(request)

@login_required
@user_passes_test(is_admin)
def upload_facilities(request):
    """Placeholder: upload facilities view."""
    messages.info(request, 'Upload facilities view is under construction.')
    return dashboard(request)

@login_required
@user_passes_test(is_admin)
def user_management(request):
    """User management interface with search and filtering"""
    users = User.objects.select_related('facility').all()
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(license_number__icontains=search_query) |
            Q(specialization__icontains=search_query)
        )
    
    # Role filtering
    role_filter = request.GET.get('role', '')
    if role_filter:
        users = users.filter(role=role_filter)
    
    # Facility filtering
    facility_filter = request.GET.get('facility', '')
    if facility_filter:
        users = users.filter(facility_id=facility_filter)
    
    # Status filtering
    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)
    elif status_filter == 'verified':
        users = users.filter(is_verified=True)
    elif status_filter == 'unverified':
        users = users.filter(is_verified=False)
    
    # Export functionality
    export_format = request.GET.get('export', '')
    if export_format:
        return export_users(users, export_format)
    
    # Pagination
    paginator = Paginator(users, 20)
    page_number = request.GET.get('page')
    users_page = paginator.get_page(page_number)
    
    # Get facilities for filter dropdown
    facilities = Facility.objects.filter(is_active=True)
    
    context = {
        'users': users_page,
        'facilities': facilities,
        'search_query': search_query,
        'role_filter': role_filter,
        'facility_filter': facility_filter,
        'user_roles': User.USER_ROLES,
    }
    
    return render(request, 'admin_panel/user_management.html', context)

@login_required
@user_passes_test(is_admin)
def user_create(request):
    """
    Professional User Creation Backend - Medical Staff Management Excellence
    Enhanced with masterpiece-level validation and medical standards compliance
    """
    from .forms import CustomUserCreationForm
    import logging
    import time
    
    # Initialize professional logging
    logger = logging.getLogger('noctis_pro.user_management')
    
    if request.method == 'POST':
        creation_start_time = time.time()
        form = CustomUserCreationForm(request.POST)
        
        if form.is_valid():
            try:
                # Professional user creation with medical standards validation
                logger.info(f"Professional user creation initiated by {request.user.username}")
                
                # Enhanced user creation with comprehensive validation
                user = form.save(commit=False)
                
                # Professional medical staff validation
                role = user.role
                facility = user.facility
                
                # Medical standards compliance checks
                validation_results = {
                    'role_valid': role in ['admin', 'radiologist', 'technologist', 'facility_user'],
                    'facility_required': role in ['radiologist', 'technologist', 'facility_user'],
                    'license_required': role in ['radiologist', 'technologist'],
                    'specialization_recommended': role == 'radiologist',
                }
                
                # Professional validation logging
                if validation_results['facility_required'] and not facility:
                    logger.warning(f"User creation: {role} role requires facility assignment")
                    messages.error(request, f'Medical staff role "{role}" requires facility assignment for professional standards compliance')
                    raise ValueError(f'Facility required for {role} role')
                
                if validation_results['license_required'] and not user.license_number:
                    logger.warning(f"User creation: {role} role should have license number for medical compliance")
                    messages.warning(request, f'Medical professional "{role}" should have license number for regulatory compliance')
                
                # Professional user activation with medical standards
                user.is_active = True
                user.is_verified = True  # Auto-verify for admin-created users
                # Note: removed non-existent fields that were causing errors
                user.save()
                
                # Professional audit logging with medical precision
                AuditLog.objects.create(
                    user=request.user,
                    action='create',
                    model_name='User',
                    object_id=str(user.id),
                    object_repr=str(user),
                    description=f'Professional user created: {user.username} ({user.get_role_display()}) - Medical staff management',
                    details=json.dumps({
                        'created_user_id': user.id,
                        'created_username': user.username,
                        'role': user.role,
                        'facility': facility.name if facility else None,
                        'license_number': user.license_number or 'Not provided',
                        'specialization': user.specialization or 'Not specified',
                        'validation_results': validation_results,
                        'creation_time_ms': round((time.time() - creation_start_time) * 1000, 1),
                        'created_by': request.user.username,
                        'timestamp': timezone.now().isoformat(),
                    })
                )
                
                # Professional success messaging with medical context
                creation_time = round((time.time() - creation_start_time) * 1000, 1)
                facility_info = f" - Assigned to {user.facility.name}" if user.facility else ""
                license_info = f" - License: {user.license_number}" if user.license_number else ""
                
                logger.info(f"Professional user created successfully: {user.username} in {creation_time}ms")
                
                messages.success(
                    request, 
                    f'🏥 Professional medical staff created successfully!\n'
                    f'👤 User: {user.username} ({user.get_full_name()})\n'
                    f'🏷️ Role: {user.get_role_display()}{facility_info}{license_info}\n'
                    f'✅ Status: Active & Verified\n'
                    f'⚡ Processing: {creation_time}ms (Medical Grade Excellence)'
                )
                
                return redirect('admin_panel:user_management')
                
            except Exception as e:
                # Professional error handling with medical-grade logging
                error_details = {
                    'error': str(e),
                    'user_data': {
                        'username': form.cleaned_data.get('username', 'Unknown'),
                        'role': form.cleaned_data.get('role', 'Unknown'),
                        'facility': form.cleaned_data.get('facility', 'None'),
                    },
                    'created_by': request.user.username,
                    'timestamp': timezone.now().isoformat(),
                }
                
                logger.error(f"Professional user creation failed: {str(e)}")
                logger.error(f"Error details: {json.dumps(error_details, indent=2)}")
                
                messages.error(request, f'🚨 Professional user creation failed: {str(e)}')
        else:
            # Professional form validation error handling
            logger.warning(f"User creation form validation failed for {request.user.username}")
            
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, f'🚨 Validation Error: {error}')
                    else:
                        field_name = form.fields[field].label or field.replace('_', ' ').title()
                        messages.error(request, f'🚨 {field_name}: {error}')
    else:
        # Initialize form with preset values from URL parameters
        initial_data = {}
        if request.GET.get('role'):
            initial_data['role'] = request.GET.get('role')
        if request.GET.get('facility'):
            try:
                facility_id = int(request.GET.get('facility'))
                if Facility.objects.filter(id=facility_id, is_active=True).exists():
                    initial_data['facility'] = facility_id
            except (ValueError, TypeError):
                pass
        
        form = CustomUserCreationForm(initial=initial_data)
    
    # Get facilities for context (for debugging/display)
    facilities = Facility.objects.filter(is_active=True).order_by('name')
    
    context = {
        'form': form,
        'facilities': facilities,
        'user_roles': User.USER_ROLES,
        'preset_role': request.GET.get('role', ''),
        'preset_facility': request.GET.get('facility', ''),
        'facilities_count': facilities.count(),
        'edit_mode': False,
    }
    
    return render(request, 'admin_panel/user_form.html', context)

@login_required
@user_passes_test(is_admin)
def user_edit(request, user_id):
    """Edit existing user with enhanced form validation"""
    from .forms import CustomUserUpdateForm
    
    user = get_object_or_404(User, id=user_id)
    
    if request.method == 'POST':
        form = CustomUserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            try:
                # Save the updated user
                updated_user = form.save()
                
                # Log the action
                AuditLog.objects.create(
                    user=request.user,
                    action='update',
                    model_name='User',
                    object_id=str(updated_user.id),
                    object_repr=str(updated_user),
                    description=f'Updated user {updated_user.username} ({updated_user.get_role_display()})'
                )
                
                # Success message with detailed info
                facility_info = f" - Assigned to {updated_user.facility.name}" if updated_user.facility else ""
                status_info = []
                if updated_user.is_active:
                    status_info.append("Active")
                if updated_user.is_verified:
                    status_info.append("Verified")
                status_text = ", ".join(status_info) if status_info else "Inactive"
                
                messages.success(
                    request,
                    f'User "{updated_user.username}" updated successfully! '
                    f'Role: {updated_user.get_role_display()}{facility_info}. '
                    f'Status: {status_text}.'
                )
                
                return redirect('admin_panel:user_management')
                
            except Exception as e:
                messages.error(request, f'Error updating user: {str(e)}')
        else:
            # Form validation errors
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, error)
                    else:
                        field_name = form.fields[field].label or field.replace('_', ' ').title()
                        messages.error(request, f'{field_name}: {error}')
    else:
        form = CustomUserUpdateForm(instance=user)
    
    # Get facilities for context
    facilities = Facility.objects.filter(is_active=True).order_by('name')
    
    context = {
        'form': form,
        'user_obj': user,
        'facilities': facilities,
        'user_roles': User.USER_ROLES,
        'edit_mode': True,
        'facilities_count': facilities.count(),
    }
    
    return render(request, 'admin_panel/user_form.html', context)

@login_required
@user_passes_test(is_admin)
def user_delete(request, user_id):
    """Delete user immediately without confirmation"""
    user = get_object_or_404(User, id=user_id)
    username = user.username

    # Log the action before deleting
    AuditLog.objects.create(
        user=request.user,
        action='delete',
        model_name='User',
        object_id=str(user.id),
        object_repr=str(user),
        description=f'Deleted user {username}'
    )

    user.delete()
    messages.success(request, f'User {username} deleted successfully')
    return redirect('admin_panel:user_management')

@login_required
@user_passes_test(is_admin)
def facility_management(request):
    """Enhanced facility management interface"""
    facilities = Facility.objects.all()
    
    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        facilities = facilities.filter(
            Q(name__icontains=search_query) |
            Q(address__icontains=search_query) |
            Q(license_number__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(ae_title__icontains=search_query)
        )
    
    # Status filtering
    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        facilities = facilities.filter(is_active=True)
    elif status_filter == 'inactive':
        facilities = facilities.filter(is_active=False)
    
    # Sorting
    sort_by = request.GET.get('sort', 'name')
    if sort_by == 'name':
        facilities = facilities.order_by('name')
    elif sort_by == 'created_at':
        facilities = facilities.order_by('-created_at')
    elif sort_by == 'user_count':
        facilities = facilities.annotate(user_count=Count('user')).order_by('-user_count')
    elif sort_by == 'study_count':
        facilities = facilities.annotate(study_count=Count('study')).order_by('-study_count')
    
    # Export functionality
    export_format = request.GET.get('export', '')
    selected_ids = request.GET.get('selected', '')
    if export_format:
        if selected_ids:
            facility_ids = [int(id) for id in selected_ids.split(',')]
            export_facilities = facilities.filter(id__in=facility_ids)
        else:
            export_facilities = facilities
        return export_facilities_data(export_facilities, export_format)
    
    # Pagination
    paginator = Paginator(facilities, 12)  # 12 per page for grid view
    page_number = request.GET.get('page')
    facilities_page = paginator.get_page(page_number)
    
    # Statistics
    total_users = User.objects.count()
    total_studies = Study.objects.count() if hasattr(facilities.first(), 'study_set') else 0
    
    context = {
        'facilities': facilities_page,
        'search_query': search_query,
        'total_users': total_users,
        'total_studies': total_studies,
    }
    
    return render(request, 'admin_panel/facility_management.html', context)

def export_users(users, format):
    """Export users data in various formats"""
    import csv
    from django.http import HttpResponse
    import io
    
    if format == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="users_export.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Username', 'First Name', 'Last Name', 'Email', 'Phone', 
            'Role', 'Facility', 'License Number', 'Specialization', 
            'Active', 'Verified', 'Date Joined', 'Last Login'
        ])
        
        for user in users:
            writer.writerow([
                user.username,
                user.first_name,
                user.last_name,
                user.email,
                user.phone,
                user.get_role_display(),
                user.facility.name if user.facility else '',
                user.license_number,
                user.specialization,
                'Yes' if user.is_active else 'No',
                'Yes' if user.is_verified else 'No',
                user.date_joined.strftime('%Y-%m-%d %H:%M:%S'),
                user.last_login.strftime('%Y-%m-%d %H:%M:%S') if user.last_login else 'Never'
            ])
        
        return response
    
    elif format == 'excel':
        try:
            import openpyxl
            from openpyxl.utils.dataframe import dataframe_to_rows
            import pandas as pd
            
            # Create DataFrame
            data = []
            for user in users:
                data.append({
                    'Username': user.username,
                    'First Name': user.first_name,
                    'Last Name': user.last_name,
                    'Email': user.email,
                    'Phone': user.phone,
                    'Role': user.get_role_display(),
                    'Facility': user.facility.name if user.facility else '',
                    'License Number': user.license_number,
                    'Specialization': user.specialization,
                    'Active': 'Yes' if user.is_active else 'No',
                    'Verified': 'Yes' if user.is_verified else 'No',
                    'Date Joined': user.date_joined.strftime('%Y-%m-%d %H:%M:%S'),
                    'Last Login': user.last_login.strftime('%Y-%m-%d %H:%M:%S') if user.last_login else 'Never'
                })
            
            df = pd.DataFrame(data)
            
            # Create Excel response
            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = 'attachment; filename="users_export.xlsx"'
            
            with pd.ExcelWriter(response, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Users', index=False)
            
            return response
            
        except ImportError:
            # Fallback to CSV if pandas/openpyxl not available
            return export_users(users, 'csv')
    
    # Default to CSV
    return export_users(users, 'csv')

def export_facilities_data(facilities, format):
    """Export facilities data in various formats"""
    import csv
    from django.http import HttpResponse
    
    if format == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="facilities_export.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Name', 'Address', 'Phone', 'Email', 'License Number', 
            'AE Title', 'Active', 'User Count', 'Study Count', 'Created Date'
        ])
        
        for facility in facilities:
            writer.writerow([
                facility.name,
                facility.address,
                facility.phone,
                facility.email,
                facility.license_number,
                facility.ae_title,
                'Yes' if facility.is_active else 'No',
                facility.user_set.count(),
                facility.study_set.count() if hasattr(facility, 'study_set') else 0,
                facility.created_at.strftime('%Y-%m-%d %H:%M:%S') if facility.created_at else ''
            ])
        
        return response
    
    elif format == 'excel':
        try:
            import pandas as pd
            
            # Create DataFrame
            data = []
            for facility in facilities:
                data.append({
                    'Name': facility.name,
                    'Address': facility.address,
                    'Phone': facility.phone,
                    'Email': facility.email,
                    'License Number': facility.license_number,
                    'AE Title': facility.ae_title,
                    'Active': 'Yes' if facility.is_active else 'No',
                    'User Count': facility.user_set.count(),
                    'Study Count': facility.study_set.count() if hasattr(facility, 'study_set') else 0,
                    'Created Date': facility.created_at.strftime('%Y-%m-%d %H:%M:%S') if facility.created_at else ''
                })
            
            df = pd.DataFrame(data)
            
            # Create Excel response
            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = 'attachment; filename="facilities_export.xlsx"'
            
            with pd.ExcelWriter(response, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Facilities', index=False)
            
            return response
            
        except ImportError:
            # Fallback to CSV if pandas not available
            return export_facilities_data(facilities, 'csv')
    
    # Default to CSV
    return export_facilities_data(facilities, 'csv')

@csrf_exempt
@login_required
@user_passes_test(is_admin)
def bulk_user_action(request):
    """Handle bulk user actions"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        data = json.loads(request.body)
        action = data.get('action')
        user_ids = data.get('user_ids', [])
        
        if not user_ids:
            return JsonResponse({'error': 'No users selected'}, status=400)
        
        users = User.objects.filter(id__in=user_ids)
        
        if action == 'activate':
            users.update(is_active=True)
            message = f'Activated {users.count()} users'
        elif action == 'deactivate':
            users.update(is_active=False)
            message = f'Deactivated {users.count()} users'
        elif action == 'verify':
            users.update(is_verified=True)
            message = f'Verified {users.count()} users'
        elif action == 'delete':
            count = users.count()
            users.delete()
            message = f'Deleted {count} users'
        else:
            return JsonResponse({'error': 'Invalid action'}, status=400)
        
        return JsonResponse({'success': True, 'message': message})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@login_required
@user_passes_test(is_admin)
def bulk_facility_action(request):
    """Handle bulk facility actions"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        data = json.loads(request.body)
        action = data.get('action')
        facility_ids = data.get('facility_ids', [])
        
        if not facility_ids:
            return JsonResponse({'error': 'No facilities selected'}, status=400)
        
        facilities = Facility.objects.filter(id__in=facility_ids)
        
        if action == 'activate':
            facilities.update(is_active=True)
            message = f'Activated {facilities.count()} facilities'
        elif action == 'deactivate':
            facilities.update(is_active=False)
            message = f'Deactivated {facilities.count()} facilities'
        elif action == 'delete':
            count = facilities.count()
            facilities.delete()
            message = f'Deleted {count} facilities'
        else:
            return JsonResponse({'error': 'Invalid action'}, status=400)
        
        return JsonResponse({'success': True, 'message': message})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@user_passes_test(is_admin)
def facility_create(request):
    """Create new facility with enhanced form validation"""
    from .forms import FacilityForm
    
    if request.method == 'POST':
        form = FacilityForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                # Save the facility
                facility = form.save()
                
                # Handle optional facility user creation
                if form.cleaned_data.get('create_facility_user'):
                    username = form.cleaned_data.get('facility_username') or facility.ae_title or facility.name
                    username = re.sub(r"[^A-Za-z0-9_.-]", "", username)[:150] or facility.ae_title
                    
                    # Ensure unique username
                    original_username = username
                    idx = 1
                    while User.objects.filter(username=username).exists():
                        suffix = f"{idx}"
                        username = (original_username[:150 - len(suffix)] + suffix)
                        idx += 1
                    
                    # Create facility user
                    facility_email = form.cleaned_data.get('facility_email') or ''
                    raw_password = form.cleaned_data.get('facility_password') or get_random_string(12)
                    
                    user = User.objects.create_user(
                        username=username,
                        email=facility_email,
                        password=raw_password,
                        first_name=facility.name,
                        role='facility'
                    )
                    user.facility = facility
                    user.is_verified = True
                    user.is_active = True
                    user.save()
                    
                    # Log user creation
                    AuditLog.objects.create(
                        user=request.user,
                        action='create',
                        model_name='User',
                        object_id=str(user.id),
                        object_repr=str(user),
                        description=f'Created facility user {user.username} for {facility.name}'
                    )
                    
                    messages.success(
                        request,
                        f'Facility "{facility.name}" created successfully! '
                        f'Facility user account "{username}" has been created. '
                        f'AE Title: {facility.ae_title}'
                    )
                else:
                    messages.success(
                        request,
                        f'Facility "{facility.name}" created successfully! '
                        f'AE Title: {facility.ae_title}'
                    )
                
                # Log facility creation
                AuditLog.objects.create(
                    user=request.user,
                    action='create',
                    model_name='Facility',
                    object_id=str(facility.id),
                    object_repr=str(facility),
                    description=f'Created facility {facility.name}'
                )
                
                return redirect('admin_panel:facility_management')
                
            except Exception as e:
                messages.error(request, f'Error creating facility: {str(e)}')
        else:
            # Form validation errors
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, error)
                    else:
                        field_name = form.fields[field].label or field.replace('_', ' ').title()
                        messages.error(request, f'{field_name}: {error}')
    else:
        form = FacilityForm()
    
    context = {
        'form': form,
        'edit_mode': False,
    }
    
    return render(request, 'admin_panel/facility_form.html', context)

@login_required
@user_passes_test(is_admin)
def facility_edit(request, facility_id):
    """Edit existing facility with enhanced form validation"""
    from .forms import FacilityForm
    
    facility = get_object_or_404(Facility, id=facility_id)
    
    if request.method == 'POST':
        form = FacilityForm(request.POST, request.FILES, instance=facility)
        if form.is_valid():
            try:
                # Save the updated facility
                updated_facility = form.save()
                
                # Handle optional facility user creation during edit
                if form.cleaned_data.get('create_facility_user'):
                    username = form.cleaned_data.get('facility_username') or updated_facility.ae_title or updated_facility.name
                    username = re.sub(r"[^A-Za-z0-9_.-]", "", username)[:150] or updated_facility.ae_title
                    
                    # Ensure unique username
                    original_username = username
                    idx = 1
                    while User.objects.filter(username=username).exists():
                        suffix = f"{idx}"
                        username = (original_username[:150 - len(suffix)] + suffix)
                        idx += 1
                    
                    # Create facility user
                    facility_email = form.cleaned_data.get('facility_email') or ''
                    raw_password = form.cleaned_data.get('facility_password') or get_random_string(12)
                    
                    user = User.objects.create_user(
                        username=username,
                        email=facility_email,
                        password=raw_password,
                        first_name=updated_facility.name,
                        role='facility'
                    )
                    user.facility = updated_facility
                    user.is_verified = True
                    user.is_active = True
                    user.save()
                    
                    # Log user creation
                    AuditLog.objects.create(
                        user=request.user,
                        action='create',
                        model_name='User',
                        object_id=str(user.id),
                        object_repr=str(user),
                        description=f'Created facility user {user.username} for {updated_facility.name}'
                    )
                    
                    messages.success(
                        request,
                        f'Facility "{updated_facility.name}" updated successfully! '
                        f'Facility user account "{username}" has been created. '
                        f'AE Title: {updated_facility.ae_title}'
                    )
                else:
                    messages.success(
                        request,
                        f'Facility "{updated_facility.name}" updated successfully! '
                        f'AE Title: {updated_facility.ae_title}'
                    )
                
                # Log facility update
                AuditLog.objects.create(
                    user=request.user,
                    action='update',
                    model_name='Facility',
                    object_id=str(updated_facility.id),
                    object_repr=str(updated_facility),
                    description=f'Updated facility {updated_facility.name}'
                )
                
                return redirect('admin_panel:facility_management')
                
            except Exception as e:
                messages.error(request, f'Error updating facility: {str(e)}')
        else:
            # Form validation errors
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, error)
                    else:
                        field_name = form.fields[field].label or field.replace('_', ' ').title()
                        messages.error(request, f'{field_name}: {error}')
    else:
        form = FacilityForm(instance=facility)
    
    context = {
        'form': form,
        'facility': facility,
        'edit_mode': True,
    }
    
    return render(request, 'admin_panel/facility_form.html', context)

@login_required
@user_passes_test(is_admin)
def facility_delete(request, facility_id):
    """Delete facility"""
    facility = get_object_or_404(Facility, id=facility_id)
    
    if request.method == 'POST':
        facility_name = facility.name
        
        # Check if facility has users
        if facility.user_set.exists():
            messages.error(request, 'Cannot delete facility with existing users. Please reassign or delete users first.')
            return redirect('admin_panel:facility_management')
        
        # Log the action before deleting
        AuditLog.objects.create(
            user=request.user,
            action='delete',
            model_name='Facility',
            object_id=str(facility.id),
            object_repr=str(facility),
            description=f'Deleted facility {facility_name}'
        )
        
        facility.delete()
        messages.success(request, f'Facility {facility_name} deleted successfully')
        return redirect('admin_panel:facility_management')
    
    context = {'facility': facility}
    return render(request, 'admin_panel/facility_confirm_delete.html', context)
