# chat/views.py
import os
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt,csrf_protect
from django.utils.text import get_valid_filename
from .models import ChatMessage,FolderChatMessage, FolderChatVisit
from coreapi.models import UserProfile
from django.utils import timezone
import json

def chat_history(request):
    user_id = request.session.get("user_id")
    if not user_id:
        return JsonResponse({"messages": [], "pinned": []})

    # Get Pinned
    pinned = ChatMessage.objects.filter(is_pinned=True)
    
    # Get Last 100 Messages
    normal = ChatMessage.objects.filter(is_pinned=False).select_related('user').order_by('created_at')
    count = normal.count()
    if count > 100:
        normal = normal[count-100:]

    def serialize(m):
        return {
            "id": m.id,
            "user": m.user.user_name,
            "content": m.content,
            "attached_type": m.attached_type,
            "attached_path": m.attached_path,
            "attached_label": m.attached_label,
            "is_pinned": m.is_pinned,
            "time": m.created_at.strftime("%H:%M"),
        }

    return JsonResponse({
        "pinned": [serialize(m) for m in pinned],
        "messages": [serialize(m) for m in normal],
    })

@require_POST
def unpin_message(request):
    # (Add your unpin logic here if needed)
    pass 

@require_POST
@csrf_exempt
def upload_chat_file(request):
    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "No file"}, status=400)

    base_dir = os.path.join(settings.BASE_DIR, "chat_uploads")
    os.makedirs(base_dir, exist_ok=True)

    safe_name = get_valid_filename(uploaded.name)
    path = os.path.join(base_dir, safe_name)

    with open(path, "wb+") as dest:
        for chunk in uploaded.chunks():
            dest.write(chunk)

    return JsonResponse({
        "path": f"chat_uploads/{safe_name}",
        "label": safe_name
    })

@require_GET
def folder_chat_history(request):
    user_id = request.session.get("user_id")
    if not user_id: 
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    folder_path = request.GET.get('path')
    if not folder_path: 
        return JsonResponse({'error': 'No path provided'}, status=400)

    # 1. Mark as Read (Update Last Visit)
    try:
        user_profile = UserProfile.objects.get(id=user_id)
        
        FolderChatVisit.objects.update_or_create(
            user=user_profile, 
            folder_path=folder_path, 
            defaults={'last_visit': timezone.now()}
        )
    except UserProfile.DoesNotExist:
        return JsonResponse({'error': 'User profile not found'}, status=404)

    # --- DELETED THE DUPLICATE/BROKEN BLOCK HERE ---

    # 2. Fetch Messages
    msgs = FolderChatMessage.objects.filter(folder_path=folder_path).select_related('user')
    
    data = [{
        'user': m.user.user_name,
        'message': m.message,
        'time': m.timestamp.strftime('%d-%m-%Y %I:%M %p'),
        'is_me': m.user.id == user_id
    } for m in msgs]
    
    return JsonResponse({'messages': data})

@csrf_protect
def send_folder_message(request):
    if request.method == 'POST':
        try:
            # 1. AUTH CHECK: Get User ID from Session
            user_id = request.session.get("user_id")
            if not user_id:
                return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
            
            # 2. Get the UserProfile
            try:
                user_profile = UserProfile.objects.get(id=user_id)
            except UserProfile.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'User profile not found'}, status=404)

            # 3. Parse Data
            data = json.loads(request.body)
            path_id = data.get('path')
            message_text = data.get('message')

            if not path_id or not message_text:
                return JsonResponse({'status': 'error', 'message': 'Missing path or message'}, status=400)

            # 4. Save Message using user_profile
            new_msg = FolderChatMessage.objects.create(
                folder_path=path_id,
                user=user_profile,  # <--- CHANGED from request.user to user_profile
                message=message_text
            )

            return JsonResponse({
                'status': 'success',
                'user': user_profile.user_name,
                'message': new_msg.message,
                'timestamp': new_msg.timestamp.strftime('%Y-%m-%d %H:%M')
            })

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)