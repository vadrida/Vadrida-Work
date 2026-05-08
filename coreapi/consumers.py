import json
from urllib.parse import unquote
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import DraftingReport, UserProfile, SiteVisitReport, VerificationReport

class DraftingConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept() # Accept FIRST to prevent timeout
        
        self.file_no = self.scope['url_route']['kwargs']['file_no']
        self.room_group_name = f'report_drafting_{self.file_no}'
        
        # Get bank details from query string
        query_string = self.scope.get('query_string', b'').decode()
        query_params = dict(qp.split('=') for qp in query_string.split('&') if '=' in qp)
        self.bank_code = query_params.get('bank_code', '')
        self.bank_name = unquote(query_params.get('bank_name', ''))

        print(f"WS CONNECT: File {self.file_no} (Bank: {self.bank_name})")

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        # Initialize the report if it doesn't exist
        try:
            await self.ensure_report_exists()
            print(f"WS SUCCESS: Report ensured for {self.file_no}")
        except Exception as e:
            print(f"WS ERROR during setup: {e}")
            # await self.close() # Don't close, let them try to edit anyway

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    async def receive(self, text_data):
        data = json.loads(text_data)
        message_type = data.get('type')
        
        if message_type == 'field_update':
            user_id = self.scope['session'].get('user_id')
            field_id = data.get('field_id')
            new_value = data.get('value')
            old_value = data.get('old_value')
            
            # Log movement and update report data
            await self.log_movement(user_id, field_id, old_value, new_value)
            
            # Broadcast update to others in the room
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'broadcast_update',
                    'field_id': field_id,
                    'value': new_value,
                    'user_id': user_id
                }
            )

    # Receive message from room group
    async def broadcast_update(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'field_update',
            'field_id': event['field_id'],
            'value': event['value'],
            'user_id': event['user_id']
        }))

    @database_sync_to_async
    def ensure_report_exists(self):
        report, created = DraftingReport.objects.get_or_create(
            office_file_no=self.file_no,
            defaults={
                'status': 'drafting',
                'report_data': {},
                'audit_log': [],
                'bank_code': self.bank_code,
                'bank_name': self.bank_name
            }
        )
        
        # FORCED UPDATE: If bank details are empty, fill them from the current session
        updated = False
        if not report.bank_code and self.bank_code:
            report.bank_code = self.bank_code
            updated = True
        if not report.bank_name and self.bank_name:
            report.bank_name = self.bank_name
            updated = True

        # Try to link collaborators if not linked yet
        if not report.site_visitor:
            site_report = SiteVisitReport.objects.filter(office_file_no=self.file_no).first()
            if site_report:
                report.site_visitor = site_report.user
                updated = True
                
        if not report.office_verifier:
            ver_report = VerificationReport.objects.filter(office_file_no=self.file_no).first()
            if ver_report:
                report.office_verifier = ver_report.verified_by
                updated = True
                
        if updated:
            report.save()

    async def log_movement(self, user_id, field_id, old_val, new_val):
        return await database_sync_to_async(self._log_movement_sync)(user_id, field_id, old_val, new_val)

    def _log_movement_sync(self, user_id, field_id, old_val, new_val):
        try:
            report = DraftingReport.objects.get(office_file_no=self.file_no)
            user = UserProfile.objects.filter(id=user_id).first()
            user_name = user.user_name if user else "Unknown"
            
            # Update current data - Use dict copy to ensure JSONField detects change
            data = dict(report.report_data)
            data[field_id] = new_val
            report.report_data = data
            
            # Add to audit log - Use list copy
            log_entry = {
                'user_id': user_id,
                'user_name': user_name,
                'field': field_id,
                'old': old_val,
                'new': new_val,
                'timestamp': timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            logs = list(report.audit_log)
            logs.append(log_entry)
            report.audit_log = logs
            
            if user:
                report.report_drafter = user
                
            report.save()
        except Exception as e:
            print(f"SAVE ERROR in log_movement: {e}")
