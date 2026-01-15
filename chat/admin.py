from django.contrib import admin
# 1. Update the import to include the missing models
from .models import ChatMessage, FolderChatMessage, FolderChatVisit

# --- Existing ChatMessage Admin ---
@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'get_user', 'short_content', 'attached_type', 'is_pinned', 'created_at')
    list_filter = ('is_pinned', 'attached_type', 'created_at')
    search_fields = ('user__user_name', 'content', 'attached_label')
    list_display_links = ('id', 'short_content')

    def get_user(self, obj):
        return obj.user.user_name
    get_user.short_description = 'User'

    def short_content(self, obj):
        if obj.content:
            return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content
        return "(No Text)"
    short_content.short_description = 'Message'


# --- NEW: Register FolderChatMessage ---
@admin.register(FolderChatMessage)
class FolderChatMessageAdmin(admin.ModelAdmin):
    # Columns to show
    list_display = ('id', 'folder_path', 'get_user', 'short_message', 'timestamp')
    
    # Filters sidebar
    list_filter = ('timestamp',)
    
    # Search bar (searching by path, message, or username)
    search_fields = ('folder_path', 'message', 'user__user_name')

    def get_user(self, obj):
        return obj.user.user_name
    get_user.short_description = 'User'

    def short_message(self, obj):
        return obj.message[:50] + "..." if len(obj.message) > 50 else obj.message
    short_message.short_description = 'Message'


# --- NEW: Register FolderChatVisit (Optional, but useful for debugging) ---
@admin.register(FolderChatVisit)
class FolderChatVisitAdmin(admin.ModelAdmin):
    list_display = ('get_user', 'folder_path', 'last_visit')
    search_fields = ('user__user_name', 'folder_path')
    list_filter = ('last_visit',)

    def get_user(self, obj):
        return obj.user.user_name
    get_user.short_description = 'User'