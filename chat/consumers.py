import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
import hashlib
from urllib.parse import unquote
from .models import ChatMessage, FolderChatMessage, FolderChatVisit
from coreapi.models import UserProfile
import asyncio
import os
from django.conf import settings
import subprocess
import logging
import psutil
logger = logging.getLogger('coreapi')


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
                'time': timezone.now().strftime('%d-%m-%Y %I:%M %p')  # System time
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


# --- FIXED PRESENCE CONSUMER ---
class PresenceConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.group_name = "presence_global"
        
        # 1. Get User from Session (Fixed Auth)
        self.user = await self.get_user_from_session()
        
        if self.user:
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
            
            # 2. Update Last Seen
            await self.update_user_activity(self.user)
            
            # 3. Broadcast
            await self.broadcast_team_state()
        else:
            await self.close()

    async def disconnect(self, close_code):
        if hasattr(self, 'user') and self.user:
            # We don't "set offline" because we don't have that field.
            # We just let the last_seen timestamp age.
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            # Optional: Broadcast that someone left (or just wait for next update)
            await self.broadcast_team_state()

    async def receive(self, text_data):
        data = json.loads(text_data)
        page_name = data.get("page", "")
        
        if self.user and page_name:
            # Update DB
            await self.update_user_page(self.user, page_name)
            await self.broadcast_team_state()

    # --- HELPERS ---
    @database_sync_to_async
    def get_user_from_session(self):
        session = self.scope.get("session")
        if not session or "user_id" not in session: return None
        try: return UserProfile.objects.get(id=session["user_id"])
        except UserProfile.DoesNotExist: return None

    @database_sync_to_async
    def update_user_activity(self, user):
        user.last_seen = timezone.now()
        # We don't set is_online because it doesn't exist
        user.save()

    @database_sync_to_async
    def update_user_page(self, user, page):
        user.current_page = page
        user.last_seen = timezone.now()  # Update seen time on page change
        user.save()

    @database_sync_to_async
    def get_team_list(self):
        # 1. FIX: Sort by 'last_seen' (Descending) instead of 'is_online'
        users = UserProfile.objects.all().order_by('-last_seen', 'user_name')
        
        data = []
        now = timezone.now()
        
        for u in users:
            # 2. FIX: Calculate "Online" dynamically (e.g., active in last 2 mins)
            is_active = False
            if u.last_seen:
                diff = (now - u.last_seen).total_seconds()
                if diff < 120:  # 2 minutes timeout
                    is_active = True

            data.append({
                "id": u.id,
                "user_name": u.user_name,
                "is_online": is_active,  # Computed Value
                "current_page": u.current_page,
                "last_seen": u.last_seen.strftime("%H:%M") if u.last_seen else "-"
            })
        return data

    async def broadcast_team_state(self):
        team_data = await self.get_team_list()
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "presence_update",
                "team_data": team_data
            }
        )

    async def presence_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "team_update",
            "members": event["team_data"]
        }))

        
class TerminalConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        session = self.scope.get("session", {})
        if session.get("user_name") != 'alnroy':
            await self.close()
            return

        await self.accept()
        self.process = None
        
        # Start BOTH background tasks: The log tailer AND the health monitor
        self.tail_task = asyncio.create_task(self.tail_logs())
        self.health_task = asyncio.create_task(self.stream_health())  # <--- NEW

    async def disconnect(self, close_code):
        logger.info(f"WEB TERMINAL DISCONNECTED. Close Code: {close_code}")
        
        # Cancel both background tasks
        if hasattr(self, 'tail_task'): self.tail_task.cancel()
        if hasattr(self, 'health_task'): self.health_task.cancel()  # <--- NEW
        
        if self.process:
            try:
                self.process.terminate()
            except:
                pass

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get('action')

        if action == 'interrupt':
            if self.process:
                self.process.terminate()
                await self.send(json.dumps({'type': 'output', 'text': '^C\n[Process Terminated]\n'}))
                self.process = None
            return

        if action == 'command':
            cmd = data.get('command', '').strip()
            if not cmd: return
            
            # --- FIX 2: Echo command to your physical server terminal ---
            logger.info(f"WEB TERMINAL COMMAND EXECUTED: {cmd}")
            
            await self.send(json.dumps({'type': 'output', 'text': f'\nroot@vadrida:~# {cmd}\n'}))

            # --- FIX 1: Bypass the Windows Asyncio limitation ---
            try:
                # Use standard Popen, but hide the pop-up windows on the server machine
                self.process = subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                
                loop = asyncio.get_running_loop()

                async def stream_output():
                    while self.process:
                        # Read the output line-by-line in a background executor thread
                        line = await loop.run_in_executor(None, self.process.stdout.readline)
                        if not line:
                            break
                        
                        # Windows command prompt uses cp1252 encoding natively
                        text = line.decode('cp1252', errors='ignore').replace('\r\n', '\n')
                        await self.send(json.dumps({'type': 'output', 'text': text}))
                        
                    if self.process:
                        self.process.wait()
                        self.process = None

                # Start the streaming thread
                asyncio.create_task(stream_output())

            except Exception as e:
                await self.send(json.dumps({'type': 'output', 'text': f'System Error: {str(e)}\n'}))

    async def tail_logs(self):
        """Watches the terminal.log file and pushes updates via WebSocket"""
        log_path = os.path.join(settings.BASE_DIR, 'logs', 'terminal.log')
        last_size = 0
        
        while True:
            try:
                if os.path.exists(log_path):
                    current_size = os.path.getsize(log_path)
                    
                    if current_size < last_size:
                        last_size = 0 
                        
                    if current_size > last_size:
                        with open(log_path, 'rb') as f:
                            f.seek(last_size)
                            new_bytes = f.read()
                            last_size = current_size
                            
                            text = new_bytes.decode('utf-8', errors='ignore').replace('\x00', '')
                            text = text.replace('\r\n', '\n').replace('\r', '')
                            
                            if text.strip():
                                await self.send(json.dumps({'type': 'log', 'text': text}))
            except Exception:
                pass
            
            await asyncio.sleep(0.5)

    async def stream_health(self):
        """Pushes CPU and RAM stats down the WebSocket every 3 seconds"""
        psutil.cpu_percent()  # Initialize CPU tracker
        
        while True:
            try:
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory().percent
                
                # Send the health data package
                await self.send(json.dumps({
                    'type': 'health',
                    'cpu': cpu,
                    'ram': ram
                }))
            except Exception:
                pass
                
            await asyncio.sleep(3)
