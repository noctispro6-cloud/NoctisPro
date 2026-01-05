from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.db.models import Q, Count, Max
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import ChatRoom, ChatParticipant, ChatMessage, ChatInvitation
from accounts.models import User

# Create your views here.

def _get_active_participant(room: ChatRoom, user: User) -> ChatParticipant | None:
    return ChatParticipant.objects.filter(room=room, user=user, is_active=True).first()


def _can_manage_room(room: ChatRoom, user: User, participant: ChatParticipant | None) -> bool:
    # System admins can always manage rooms.
    if hasattr(user, "is_admin") and user.is_admin():
        return True
    if not participant:
        return False
    return participant.role in ("admin", "moderator")


def _can_invite_to_room(room: ChatRoom, inviter: User) -> bool:
    # Keep it simple and safe:
    # - Admin/radiologist can invite anyone
    # - Facility users can only invite users in their facility
    if hasattr(inviter, "is_admin") and inviter.is_admin():
        return True
    if hasattr(inviter, "is_radiologist") and inviter.is_radiologist():
        return True
    return True  # further restricted by facility filter below


@login_required
def chat_rooms(request):
    """List chat rooms that the user has access to"""
    # Get rooms where user is a participant
    user_rooms = ChatRoom.objects.filter(
        participants__user=request.user,
        participants__is_active=True,
        is_active=True
    ).annotate(
        participant_count=Count('participants', filter=Q(participants__is_active=True)),
        last_message_time=Max('messages__created_at')
    ).order_by('-last_activity')
    
    # Get rooms user can join (public rooms in their facility or general rooms)
    available_rooms = ChatRoom.objects.filter(
        Q(room_type='general') | Q(facility=request.user.facility),
        is_private=False,
        is_active=True
    ).exclude(
        participants__user=request.user
    ).annotate(
        participant_count=Count('participants', filter=Q(participants__is_active=True))
    )[:5]  # Limit to 5 suggestions
    
    # Get pending invitations
    pending_invitations = ChatInvitation.objects.filter(
        invited_user=request.user,
        status='pending',
        expires_at__gt=timezone.now()
    ).select_related('room', 'invited_by')
    
    # Get recent messages for each room to show previews
    for room in user_rooms:
        latest_message = room.messages.filter(is_deleted=False).order_by('-created_at').first()
        room.latest_message = latest_message
        room.unread_count = room.get_unread_count(request.user)
    
    context = {
        'user_rooms': user_rooms,
        'available_rooms': available_rooms,
        'pending_invitations': pending_invitations,
    }
    
    return render(request, 'chat/chat_rooms.html', context)

@login_required
def chat_room(request, room_id):
    """Individual chat room view"""
    room = get_object_or_404(ChatRoom, id=room_id, is_active=True)
    
    # Check if user is a participant
    participant = _get_active_participant(room, request.user)
    if not participant:
        messages.error(request, "You don't have access to this chat room.")
        return redirect('chat:chat_rooms')
    
    # Mark messages as read
    participant.mark_as_read()
    
    # Get messages (limit to recent messages for performance)
    messages_list = room.messages.filter(
        is_deleted=False
    ).select_related('sender').order_by('-created_at')[:50]
    
    # Reverse to show oldest first
    messages_list = list(reversed(messages_list))
    
    # Get other participants
    other_participants = room.participants.filter(
        is_active=True
    ).exclude(user=request.user).select_related('user')
    
    context = {
        'room': room,
        'messages': messages_list,
        'participants': other_participants,
        'user_participant': participant,
        'can_manage_room': _can_manage_room(room, request.user, participant),
    }
    
    return render(request, 'chat/chat_room.html', context)

@login_required
def create_room(request):
    """Create a new chat room"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        room_type = request.POST.get('room_type', 'general')
        is_private = request.POST.get('is_private') == 'on'
        
        if not name:
            messages.error(request, 'Room name is required.')
            return redirect('chat:chat_rooms')
        
        # Create the room
        room = ChatRoom.objects.create(
            name=name,
            description=description,
            room_type=room_type,
            is_private=is_private,
            created_by=request.user,
            facility=request.user.facility if room_type == 'facility' else None
        )
        
        # Add creator as admin participant
        ChatParticipant.objects.create(
            room=room,
            user=request.user,
            role='admin'
        )
        
        messages.success(request, f'Chat room "{name}" created successfully!')
        return redirect('chat:chat_room', room_id=room.id)
    
    return redirect('chat:chat_rooms')

@login_required
def join_room(request, room_id):
    """Join a chat room"""
    room = get_object_or_404(ChatRoom, id=room_id, is_active=True)
    
    # Check if already a participant
    if room.participants.filter(user=request.user, is_active=True).exists():
        return redirect('chat:chat_room', room_id=room.id)
    
    # Check if room is private
    if room.is_private:
        # If the user has a valid pending invitation, accept it.
        invitation = ChatInvitation.objects.filter(
            room=room,
            invited_user=request.user,
            status='pending',
            expires_at__gt=timezone.now()
        ).first()
        if invitation and invitation.accept():
            messages.success(request, f'You joined "{room.name}"!')
            return redirect('chat:chat_room', room_id=room.id)
        messages.error(request, 'This is a private room. You need an invitation to join.')
        return redirect('chat:chat_rooms')
    
    # Check room capacity
    if room.participants.filter(is_active=True).count() >= room.max_participants:
        messages.error(request, 'This room is full.')
        return redirect('chat:chat_rooms')
    
    # Add user as participant
    participant, _ = ChatParticipant.objects.get_or_create(
        room=room,
        user=request.user,
        defaults={'role': 'member'}
    )
    if not participant.is_active:
        participant.is_active = True
        participant.save(update_fields=['is_active'])
    
    messages.success(request, f'You joined "{room.name}"!')
    return redirect('chat:chat_room', room_id=room.id)

@login_required
def leave_room(request, room_id):
    """Leave a chat room"""
    room = get_object_or_404(ChatRoom, id=room_id)
    
    try:
        participant = ChatParticipant.objects.get(room=room, user=request.user)
        # If the user is the last room admin and others remain, transfer ownership.
        if participant.is_active and participant.role == 'admin':
            active_admins = ChatParticipant.objects.filter(room=room, is_active=True, role='admin').count()
            active_others = ChatParticipant.objects.filter(room=room, is_active=True).exclude(user=request.user).order_by('joined_at')
            if active_admins <= 1 and active_others.exists():
                new_admin = active_others.first()
                new_admin.role = 'admin'
                new_admin.save(update_fields=['role'])
        participant.is_active = False
        participant.save()
        messages.success(request, f'You left "{room.name}".')
    except ChatParticipant.DoesNotExist:
        messages.error(request, "You're not a member of this room.")
    
    return redirect('chat:chat_rooms')


@login_required
@require_POST
def update_room_settings(request, room_id):
    room = get_object_or_404(ChatRoom, id=room_id, is_active=True)
    participant = _get_active_participant(room, request.user)
    if not _can_manage_room(room, request.user, participant):
        return JsonResponse({'ok': False, 'error': 'Permission denied'}, status=403)

    name = (request.POST.get('name') or '').strip()
    description = (request.POST.get('description') or '').strip()
    is_private = (request.POST.get('is_private') == 'on')
    max_participants_raw = (request.POST.get('max_participants') or '').strip()

    if not name:
        return JsonResponse({'ok': False, 'error': 'Room name is required'}, status=400)

    try:
        max_participants = int(max_participants_raw) if max_participants_raw else room.max_participants
    except Exception:
        max_participants = room.max_participants
    max_participants = max(2, min(500, int(max_participants or room.max_participants)))

    room.name = name
    room.description = description
    room.is_private = bool(is_private)
    room.max_participants = max_participants
    room.save(update_fields=['name', 'description', 'is_private', 'max_participants', 'last_activity'])

    return JsonResponse({'ok': True})


@login_required
def api_search_users(request, room_id):
    room = get_object_or_404(ChatRoom, id=room_id, is_active=True)
    participant = _get_active_participant(room, request.user)
    if not participant:
        return JsonResponse({'ok': False, 'error': 'Not a participant'}, status=403)
    if not _can_manage_room(room, request.user, participant):
        return JsonResponse({'ok': False, 'error': 'Permission denied'}, status=403)

    q = (request.GET.get('q') or '').strip()
    if len(q) < 2:
        return JsonResponse({'ok': True, 'results': []})

    existing_ids = set(
        ChatParticipant.objects.filter(room=room, is_active=True).values_list('user_id', flat=True)
    )

    users = User.objects.filter(is_active=True).exclude(id__in=existing_ids)
    # Facility users can only invite within their facility (admin/radiologist can invite anyone).
    if not ((hasattr(request.user, 'is_admin') and request.user.is_admin()) or (hasattr(request.user, 'is_radiologist') and request.user.is_radiologist())):
        if getattr(request.user, 'facility_id', None):
            users = users.filter(facility_id=request.user.facility_id)
        else:
            users = users.none()

    users = users.filter(
        Q(username__icontains=q) |
        Q(first_name__icontains=q) |
        Q(last_name__icontains=q) |
        Q(email__icontains=q)
    ).order_by('first_name', 'last_name', 'username')[:12]

    results = []
    for u in users:
        results.append({
            'id': u.id,
            'username': u.username,
            'name': u.get_full_name() or u.username,
            'role': getattr(u, 'role', None),
            'facility': getattr(getattr(u, 'facility', None), 'name', None),
        })
    return JsonResponse({'ok': True, 'results': results})


@login_required
@require_POST
def invite_user(request, room_id):
    room = get_object_or_404(ChatRoom, id=room_id, is_active=True)
    participant = _get_active_participant(room, request.user)
    if not participant:
        return JsonResponse({'ok': False, 'error': 'Not a participant'}, status=403)
    if not _can_manage_room(room, request.user, participant):
        return JsonResponse({'ok': False, 'error': 'Permission denied'}, status=403)

    invited_user_id = (request.POST.get('user_id') or '').strip()
    invite_message = (request.POST.get('message') or '').strip()
    if not invited_user_id:
        return JsonResponse({'ok': False, 'error': 'user_id is required'}, status=400)

    invited_user = User.objects.filter(id=invited_user_id, is_active=True).first()
    if not invited_user:
        return JsonResponse({'ok': False, 'error': 'User not found'}, status=404)

    # If already a participant, just reactivate (no invitation spam).
    existing_participant = ChatParticipant.objects.filter(room=room, user=invited_user).first()
    if existing_participant and existing_participant.is_active:
        return JsonResponse({'ok': True, 'already_member': True})

    # Facility restriction for non-admin/non-radiologist
    if not ((hasattr(request.user, 'is_admin') and request.user.is_admin()) or (hasattr(request.user, 'is_radiologist') and request.user.is_radiologist())):
        if getattr(request.user, 'facility_id', None) and invited_user.facility_id != request.user.facility_id:
            return JsonResponse({'ok': False, 'error': 'You can only invite users in your facility'}, status=403)

    # Create or refresh invitation
    expires_at = timezone.now() + timezone.timedelta(days=7)
    invitation = ChatInvitation.objects.filter(room=room, invited_user=invited_user).first()
    if invitation:
        invitation.status = 'pending'
        invitation.message = invite_message
        invitation.invited_by = request.user
        invitation.expires_at = expires_at
        invitation.responded_at = None
        invitation.save(update_fields=['status', 'message', 'invited_by', 'expires_at', 'responded_at'])
    else:
        ChatInvitation.objects.create(
            room=room,
            invited_by=request.user,
            invited_user=invited_user,
            status='pending',
            message=invite_message,
            expires_at=expires_at,
        )

    return JsonResponse({'ok': True})


@login_required
@require_POST
def remove_participant(request, room_id, user_id: int):
    room = get_object_or_404(ChatRoom, id=room_id, is_active=True)
    participant = _get_active_participant(room, request.user)
    if not _can_manage_room(room, request.user, participant):
        return JsonResponse({'ok': False, 'error': 'Permission denied'}, status=403)

    if int(user_id) == int(request.user.id):
        return JsonResponse({'ok': False, 'error': 'Use “Leave room” to remove yourself'}, status=400)

    target = ChatParticipant.objects.filter(room=room, user_id=user_id, is_active=True).first()
    if not target:
        return JsonResponse({'ok': False, 'error': 'Participant not found'}, status=404)

    # Moderators cannot remove admins.
    if participant and participant.role == 'moderator' and target.role == 'admin':
        return JsonResponse({'ok': False, 'error': 'Moderators cannot remove room admins'}, status=403)

    # Prevent removing the last admin if other participants remain.
    if target.role == 'admin':
        active_admins = ChatParticipant.objects.filter(room=room, is_active=True, role='admin').count()
        active_others = ChatParticipant.objects.filter(room=room, is_active=True).exclude(user_id=target.user_id).count()
        if active_admins <= 1 and active_others > 0:
            return JsonResponse({'ok': False, 'error': 'Cannot remove the last room admin'}, status=400)

    target.is_active = False
    target.save(update_fields=['is_active'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def update_participant_role(request, room_id, user_id: int):
    room = get_object_or_404(ChatRoom, id=room_id, is_active=True)
    participant = _get_active_participant(room, request.user)
    if not participant or not _can_manage_room(room, request.user, participant):
        return JsonResponse({'ok': False, 'error': 'Permission denied'}, status=403)

    # Only admins can change roles (moderators can’t).
    if not ((hasattr(request.user, 'is_admin') and request.user.is_admin()) or participant.role == 'admin'):
        return JsonResponse({'ok': False, 'error': 'Only room admins can change roles'}, status=403)

    role = (request.POST.get('role') or '').strip()
    if role not in ('member', 'moderator', 'admin'):
        return JsonResponse({'ok': False, 'error': 'Invalid role'}, status=400)

    target = ChatParticipant.objects.filter(room=room, user_id=user_id, is_active=True).first()
    if not target:
        return JsonResponse({'ok': False, 'error': 'Participant not found'}, status=404)

    # Prevent demoting the last admin if others remain.
    if target.role == 'admin' and role != 'admin':
        active_admins = ChatParticipant.objects.filter(room=room, is_active=True, role='admin').count()
        active_others = ChatParticipant.objects.filter(room=room, is_active=True).exclude(user_id=target.user_id).count()
        if active_admins <= 1 and active_others > 0:
            return JsonResponse({'ok': False, 'error': 'Cannot demote the last room admin'}, status=400)

    target.role = role
    target.save(update_fields=['role'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def accept_invitation(request, invitation_id: int):
    """Accept a chat invitation."""
    invitation = get_object_or_404(
        ChatInvitation,
        id=invitation_id,
        invited_user=request.user
    )
    if invitation.status != 'pending' or timezone.now() >= invitation.expires_at:
        messages.error(request, 'This invitation is no longer valid.')
        return redirect('chat:chat_rooms')
    invitation.accept()
    messages.success(request, f'Invitation accepted: "{invitation.room.name}"')
    return redirect('chat:chat_room', room_id=invitation.room.id)


@login_required
@require_POST
def decline_invitation(request, invitation_id: int):
    """Decline a chat invitation."""
    invitation = get_object_or_404(
        ChatInvitation,
        id=invitation_id,
        invited_user=request.user
    )
    if invitation.status != 'pending':
        return redirect('chat:chat_rooms')
    invitation.decline()
    messages.success(request, 'Invitation declined.')
    return redirect('chat:chat_rooms')
