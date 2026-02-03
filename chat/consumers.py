# chat/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from coreapi.models import UserProfile
from django.utils import timezone
import hashlib
from .models import ChatMessage, FolderChatMessage, FolderChatVisit
from coreapi.models import UserProfile

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_group_name = "global_chat"
        self.user = await self.get_user_from_session()

        if self.user:
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()
        else:
            await self.close()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        if not self.user: return

        # Save to DB
        saved_msg = await self.save_message(
            data.get('content', ''),
            data.get('attached_type', 'none'),
            data.get('attached_path'),
            data.get('attached_label')
        )

        # Broadcast
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'id': saved_msg.id,
                'user': self.user.user_name,
                'content': saved_msg.content,
                'attached_type': saved_msg.attached_type,
                'attached_path': saved_msg.attached_path,
                'attached_label': saved_msg.attached_label,
                'time': saved_msg.created_at.strftime("%H:%M")
            }
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def get_user_from_session(self):
        session = self.scope.get("session")
        if not session or "user_id" not in session: return None
        try: return UserProfile.objects.get(id=session["user_id"])
        except UserProfile.DoesNotExist: return None

    @database_sync_to_async
    def save_message(self, content, att_type, path, label):
        return ChatMessage.objects.create(
            user=self.user, content=content,
            attached_type=att_type, attached_path=path, attached_label=label
        )
    
class FolderChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # 1. Get Path & Create Group
        query_string = self.scope['query_string'].decode('utf-8')
        if 'path=' not in query_string:
            await self.close()
            return

        self.folder_path = query_string.split('path=')[-1]
        # Simple URL decode (replace %20 with space, etc)
        from urllib.parse import unquote
        self.folder_path = unquote(self.folder_path)

        path_hash = hashlib.md5(self.folder_path.encode('utf-8')).hexdigest()
        self.room_group_name = f"folder_{path_hash}"

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        message = data.get('message')
        user_id = self.scope['session'].get('user_id')

        if not user_id or not message: return

        # Save & Broadcast
        user_name = await self.save_message(user_id, self.folder_path, message)
        
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message,
                'user': user_name,
                'user_id': user_id,
                'time': timezone.now().strftime('%d-%m-%Y %I:%M %p') # System time
            }
        )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'message': event['message'],
            'user': event['user'],
            'is_me': event['user_id'] == self.scope['session'].get('user_id'),
            'time': event['time']
        }))

    @database_sync_to_async
    def save_message(self, user_id, path, message):
        user = UserProfile.objects.get(id=user_id)
        FolderChatMessage.objects.create(folder_path=path, user=user, message=message)
        FolderChatVisit.objects.update_or_create(
            user=user, folder_path=path, defaults={'last_visit': timezone.now()}
        )
        return user.user_name
    

class PresenceConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.group_name = "presence_global"
        
        # 1. Add this connection to the global presence group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # 2. Mark User as Online Immediately
        user = self.scope["user"]
        # Note: If you use custom auth (session based), ensure user is in scope
        # If using session['user_id'], you might need to fetch manually.
        # Assuming standard Django Auth or middleware populates scope['user']
        if user.is_authenticated:
            await self.update_user_status(user, is_online=True)
            
        # 3. Broadcast the new Team List to everyone
        await self.broadcast_team_state()

    async def disconnect(self, close_code):
        # 1. Mark User Offline
        user = self.scope["user"]
        if user.is_authenticated:
            await self.update_user_status(user, is_online=False)

        # 2. Remove from group & Broadcast update
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        await self.broadcast_team_state()

    async def receive(self, text_data):
        # 1. Listen for "Page Change" events from the client
        data = json.loads(text_data)
        page_name = data.get("page", "")
        
        user = self.scope["user"]
        if user.is_authenticated and page_name:
            # Update DB with new page location
            await self.update_user_page(user, page_name)
            # Tell everyone "Alan is now on Feedback Page"
            await self.broadcast_team_state()

    # --- Database Methods (Must be Async) ---
    @database_sync_to_async
    def update_user_status(self, user, is_online):
        try:
            # Adjust query to match your specific User Model setup
            profile = UserProfile.objects.get(user=user)
            profile.is_online = is_online
            profile.last_seen = timezone.now()
            profile.save()
        except Exception as e:
            print(f"Error updating status: {e}")

    @database_sync_to_async
    def update_user_page(self, user, page):
        try:
            profile = UserProfile.objects.get(user=user)
            profile.current_page = page
            profile.save()
        except:
            pass

    @database_sync_to_async
    def get_team_list(self):
        # Fetch all users formatted for the frontend
        users = UserProfile.objects.all().order_by('-is_online', 'user_name')
        data = []
        for u in users:
            data.append({
                "id": u.id,
                "user_name": u.user_name,
                "is_online": u.is_online,
                "current_page": u.current_page,
                "last_seen": u.last_seen.strftime("%H:%M") if u.last_seen else "-"
            })
        return data

    async def broadcast_team_state(self):
        # Get fresh list
        team_data = await self.get_team_list()
        # Send to group
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "presence_update",
                "team_data": team_data
            }
        )

    async def presence_update(self, event):
        # Send data to WebSocket
        await self.send(text_data=json.dumps({
            "type": "team_update",
            "members": event["team_data"]
        }))