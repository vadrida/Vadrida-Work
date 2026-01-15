# chat/models.py
from django.db import models
from coreapi.models import UserProfile  # Import User from the other app

class ChatMessage(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    content = models.TextField(blank=True)
    
    attached_type = models.CharField(
        max_length=20,
        choices=[("none", "None"), ("file", "File"), ("folder", "Folder")],
        default="none"
    )
    attached_path = models.CharField(max_length=500, null=True, blank=True)
    attached_label = models.CharField(max_length=255, null=True, blank=True)
    
    read_by = models.ManyToManyField(UserProfile, related_name="read_messages", blank=True)
    is_pinned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class FolderChatMessage(models.Model):
    # We use the folder path as the identifier
    folder_path = models.CharField(max_length=500, db_index=True) 
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']


class FolderChatVisit(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    folder_path = models.CharField(max_length=500, db_index=True)
    last_visit = models.DateTimeField(auto_now=True)  # Auto-updates whenever saved

    class Meta:
        unique_together = ('user', 'folder_path')