# core/views.py
import os
import json
from django.shortcuts import render, redirect
from django.http import JsonResponse, FileResponse, HttpResponseNotFound
from django.utils import timezone
from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.http import require_GET
from coreapi.models import UserProfile, SiteVisitReport
from chat.models import ChatMessage, FolderChatMessage
from django.db.models import Avg, Count, Max
from django.db.models import Count, Avg, Q
from django.shortcuts import get_object_or_404
from django.views.decorators.clickjacking import xframe_options_exempt 

# --- 1. THE MAIN PAGE (HTML Shell) ---
def admin_dashboard(request):
    if request.session.get("user_role") != "admin":
        return redirect("coreapi:login_page")
    return render(request, "admin_dashboard.html")

# --- 2. LIVE DATA API (Polled every 2 seconds) ---
@require_GET
def dashboard_stats_api(request):
    # Security: Ensure only admins can call this
    if request.session.get("user_role") != "admin":
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    # A. Online Users (Active in last 5 mins)
    threshold = timezone.now() - timezone.timedelta(minutes=5)
    online_users = UserProfile.objects.filter(last_seen__gte=threshold).values(
        'user_name', 'role', 'current_page', 'last_seen'
    )

    # B. Report Stats
    # "Created Now" = Created Today
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    reports_today = SiteVisitReport.objects.filter(created_at__gte=today_start).count()
    total_reports = SiteVisitReport.objects.count()

    # C. Global Chats (Last 20)
    # We fetch related user to get the name
    global_msgs = ChatMessage.objects.select_related('user').order_by('-created_at')[:20]
    chat_data = [{
        'user': msg.user.user_name,
        'message': msg.content,
        'time': msg.created_at.strftime("%H:%M")
    } for msg in reversed(global_msgs)] # Reverse to show oldest -> newest

    return JsonResponse({
        'online_users': list(online_users),
        'stats': {
            'today': reports_today,
            'total': total_reports
        },
        'chats': chat_data
    })

# --- 3. PDF MANAGEMENT ---
# core/views.py

def list_pdfs_api(request):
    """
    Fetches reports from DB that have a PDF generated.
    Returns metadata needed for the Admin Dashboard list.
    """
    if request.session.get("user_role") != "admin":
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    # Fetch reports that have a PDF file linked
    reports = SiteVisitReport.objects.exclude(generated_pdf_name__isnull=True).exclude(generated_pdf_name='').select_related('user').order_by('-updated_at')
    
    data = []
    for r in reports:
        data.append({
            'id': r.id,  # Important for the link
            'filename': r.generated_pdf_name,
            'applicant': r.applicant_name or "Unknown Applicant",
            'file_no': r.office_file_no or "No File #",
            'user': r.user.user_name,
            'created': r.updated_at.strftime("%d-%b %H:%M"),
        })

    return JsonResponse({'files': data})

@xframe_options_exempt  
def view_pdf(request, filename):
    if request.session.get("user_role") != "admin":
        return HttpResponseNotFound("Unauthorized")
        
    filepath = os.path.join(settings.GENERATED_PDFS_ROOT, filename)
    if os.path.exists(filepath):
        return FileResponse(open(filepath, 'rb'), content_type='application/pdf')
    return HttpResponseNotFound("File not found")

@require_GET
def dashboard_stats_api(request):
    if request.session.get("user_role") != "admin":
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    # 1. LIVE USERS (Existing logic)
    threshold = timezone.now() - timezone.timedelta(minutes=5)
    online_users = UserProfile.objects.filter(last_seen__gte=threshold).values(
        'user_name', 'role', 'current_page'
    )

    # 2. USER ANALYTICS (The "Performance" Data)
    # Group by User -> Calculate Average Score & Count Reports
    user_performance = SiteVisitReport.objects.values('user__user_name').annotate(
        avg_score=Avg('completion_score'),
        total_reports=Count('id'),
        last_active=Max('updated_at')
    ).order_by('-avg_score')

    # 3. RECENT REPORTS (Who generated what?)
    # We fetch the last 10 reports from the DB to show "Who did what"
    recent_db_reports = SiteVisitReport.objects.select_related('user').order_by('-updated_at')[:10]
    
    reports_list = []
    for r in recent_db_reports:
        reports_list.append({
            'file_no': r.office_file_no,
            'applicant': r.applicant_name,
            'user': r.user.user_name,
            'score': r.completion_score,
            'time': r.updated_at.strftime("%d-%m %H:%M"),
            'id': r.id
        })

    return JsonResponse({
        'online_users': list(online_users),
        'analytics': list(user_performance),
        'recent_reports': reports_list,
        'stats': {
            'today': SiteVisitReport.objects.filter(created_at__date=timezone.now().date()).count(),
            'total': SiteVisitReport.objects.count()
        }
    })
# core/views.py

def dashboard_stats_api(request):
    if request.session.get("user_role") != "admin":
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    # 1. FETCH TEAM MEMBERS (Exclude Admin)
    # We get everyone, ordered by who was seen last
    # CHANGE 'Sanjay Babu' to your exact admin username if role check isn't enough
    team_query = UserProfile.objects.exclude(role='admin').order_by('-last_seen')
    
    users_data = []
    threshold = timezone.now() - timezone.timedelta(minutes=5)

    for u in team_query:
        # Determine if Online
        is_online = u.last_seen and u.last_seen >= threshold
        
        users_data.append({
            'user_name': u.user_name,  # Consistent field name
            'role': u.role,
            'is_online': bool(is_online),
            # Show time if offline, or "Online" if online
            'last_seen': u.last_seen.strftime("%H:%M") if u.last_seen else "Never",
            'current_page': u.current_page if is_online else "Offline"
        })

    # 2. WORK LOG (Recent Reports)
    # Get recent reports for the "Work Overview" table
    recent_reports = SiteVisitReport.objects.select_related('user').order_by('-updated_at')[:10]
    reports_data = [{
        'user': r.user.user_name,
        'applicant': r.applicant_name,
        'score': r.completion_score,
        'time': r.updated_at.strftime("%H:%M")
    } for r in recent_reports]

    # 3. CHATS
    chats = ChatMessage.objects.all().order_by('-created_at')[:20]
    chat_data = [{
        'user': c.user.user_name, 
        'message': c.content, 
        'time': c.created_at.strftime("%H:%M")
    } for c in reversed(chats)]

    return JsonResponse({
        'team_members': users_data, # Sending ALL users now
        'recent_reports': reports_data,
        'chats': chat_data
    })
# --- 2. SPECIFIC USER DETAILS API ---
def user_details_api(request, user_id):
    if request.session.get("user_role") != "admin":
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    user = get_object_or_404(UserProfile, id=user_id)
    
    # Calc Stats
    total_reports = SiteVisitReport.objects.filter(user=user).count()
    avg_score = SiteVisitReport.objects.filter(user=user).aggregate(Avg('completion_score'))['completion_score__avg'] or 0
    
    # Recent Activity
    recent_work = SiteVisitReport.objects.filter(user=user).order_by('-updated_at')[:5].values(
        'office_file_no', 'applicant_name', 'updated_at', 'completion_score'
    )

    return JsonResponse({
        'name': user.user_name,
        'role': user.role,
        'total_reports': total_reports,
        'avg_score': round(avg_score, 1),
        'last_seen': user.last_seen,
        'recent_work': list(recent_work)
    })

@xframe_options_exempt
def report_detail_view(request, report_id):
    if request.session.get("user_role") != "admin":
        return redirect("coreapi:login_page")
        
    report = get_object_or_404(SiteVisitReport, id=report_id)
    sketches = report.sketches.all()
    
    # 1. Get Completion Score
    metrics = report.form_data.get('completion_metrics', {})
    if isinstance(metrics, dict):
        completion_percent = metrics.get('percent', report.completion_score)
    else:
        completion_percent = report.completion_score

    # 2. Process the Data using the Smart Parser
    structured_data = process_data_recursive(report.form_data)

    context = {
        'report': report,
        'sketches': sketches,
        'structured_data': structured_data, # Use this new list
        'completion_percent': completion_percent,
        'pdf_url': f"/core/view-pdf/{report.generated_pdf_name}/" if report.generated_pdf_name else None
    }
    return render(request, "report_detail.html", context)\
        
def format_item_key(key):
    """Converts 'documents_received' -> 'Documents Received'"""
    return key.replace('_', ' ').title()

def clean_label(key):
    return str(key).replace('_', ' ').title().replace('Check', '').strip()

def process_boundary_group(data):
    """
    Groups boundary data into 4 buckets.
    PRIORITIZES 'Translation' and 'Site' checks to ensure they aren't missed.
    """
    groups = {
        'doc1': {'name': 'Document 1', 'fields': {}, 'order': 1},
        'doc2': {'name': 'Document 2', 'fields': {}, 'order': 2},
        'site': {'name': 'Site Measurement', 'fields': {}, 'order': 3},
        'trans': {'name': 'Translation Reason', 'fields': {}, 'order': 4},
    }

    # 1. Extract Document Names
    for key, value in data.items():
        if key == 'ref_doc_1_name': groups['doc1']['name'] = value
        if key == 'ref_doc_2_name': groups['doc2']['name'] = value

    # 2. Group Data
    for key, value in data.items():
        # Skip empty values and the name keys we already used
        if not value: continue
        if key in ['ref_doc_1_name', 'ref_doc_2_name']: continue
        
        key_lower = key.lower()
        target = None
        
        # --- LOGIC ORDER MATTERS HERE ---
        
        # 1. Check for Translation/Reason FIRST
        if 'translation' in key_lower or 'reason' in key_lower:
            target = 'trans'
            
        # 2. Check for Site Data (Ensure it's not a doc field)
        elif 'site' in key_lower and 'doc' not in key_lower:
            target = 'site'
            
        # 3. Check for Doc 1
        elif 'doc1' in key_lower:
            target = 'doc1'
            
        # 4. Check for Doc 2
        elif 'doc2' in key_lower:
            target = 'doc2'
            
        # If we found a group, clean the key to get the Direction (North/South)
        if target:
            # Strip out all known suffixes to leave just the direction
            clean = key_lower.replace('_translation_reason', '') \
                             .replace('_reason', '') \
                             .replace('_site_data', '') \
                             .replace('site_', '') \
                             .replace('_boundary', '') \
                             .replace('_doc1', '') \
                             .replace('_doc2', '') \
                             .replace('_', ' ').title().strip()
            
            groups[target]['fields'][clean] = value

    # 3. Convert to Sorted List
    final_list = []
    # Sort by the 'order' defined at top (Doc1 -> Doc2 -> Site -> Trans)
    sorted_keys = sorted(groups.keys(), key=lambda k: groups[k]['order'])
    
    for k in sorted_keys:
        group = groups[k]
        if group['fields']:
            final_list.append({
                'doc_name': group['name'],
                'data': group['fields']
            })
            
    return final_list

def process_data_recursive(data):
    processed = []
    
    excluded_keys = [
        'vectors', 'completion_metrics', 'images', 'sketch', 
        'report_id', 'id', 'csrfmiddlewaretoken', 'payload'
    ]

    if isinstance(data, dict):
        # --- 1. INITIALIZE GROUPS ---
        roof_group = {'type': 'roof_table', 'key': 'Roof Analysis', 'main_type': '-', 'percentages': []}
        floor_group = {'type': 'group_box', 'key': 'Flooring & Levels', 'fields': []}
        yard_group = {'type': 'group_box', 'key': 'Setbacks & Yards', 'fields': []}
        
        grouped_keys_registry = []

        # --- 2. FIRST PASS: EXTRACT SPECIFIC GROUPS ---
        for key, value in data.items():
            # Skip empty values immediately
            if value is None or value == "": continue
            
            k_lower = key.lower()
            
            # --- A. ROOF GROUP ---
            if 'roof_type' in k_lower:
                roof_group['main_type'] = value
                grouped_keys_registry.append(key)
            
            elif 'percentage' in k_lower:
                # Check if it relates to roof materials
                if any(x in k_lower for x in ['rcc', 'sheet', 'tiled', 'other', 'roof']):
                    label = clean_label(key).replace(' Percentage', '')
                    roof_group['percentages'].append({'k': label, 'v': value})
                    grouped_keys_registry.append(key)

            # --- B. FLOOR GROUP ---
            # Catches 'floor', 'flooring', 'level'
            elif 'floor' in k_lower or 'level' in k_lower:
                floor_group['fields'].append({'k': clean_label(key), 'v': value})
                grouped_keys_registry.append(key)

            # --- C. YARD/SETBACK GROUP ---
            # Catches 'front_yard', 'rear_setback', 'side_yard', etc.
            elif 'yard' in k_lower or 'setback' in k_lower:
                yard_group['fields'].append({'k': clean_label(key), 'v': value})
                grouped_keys_registry.append(key)

        # --- 3. SECOND PASS: PROCESS REMAINING DATA ---
        for key, value in data.items():
            if key in excluded_keys: continue
            if key in grouped_keys_registry: continue # Skip if already grouped
            
            # Standard skips
            if value is None or value == "": continue
            if isinstance(value, list) and len(value) == 0: continue
            if isinstance(value, dict) and not value: continue
            
            # Filter "Check" keys (User Request)
            if 'check' in key.lower() and isinstance(value, bool): continue

            label = clean_label(key)

            # Special: Boundary Group
            if 'boundary' in key.lower() and isinstance(value, dict):
                boundary_data = process_boundary_group(value)
                if boundary_data:
                    processed.append({'key': label, 'val': boundary_data, 'type': 'boundary_group'})
                continue 

            # Standard Logic (List/Dict/Text)
            if isinstance(value, list):
                if len(value) > 0 and isinstance(value[0], dict):
                    records = []
                    for item in value:
                        record_name = item.get('name', item.get('title', 'Record'))
                        fields = []
                        for k, v in item.items():
                            if k in ['name', 'title']: continue
                            if 'check' in k.lower(): continue
                            if v == "" or v is None: continue
                            if v is True: v = "Yes"
                            if v is False: v = "No"
                            fields.append({'k': clean_label(k), 'v': v})
                        if fields: records.append({'title': record_name, 'fields': fields})
                    if records: processed.append({'key': label, 'val': records, 'type': 'record_list'})
                else:
                    processed.append({'key': label, 'val': value, 'type': 'list'})
            
            elif isinstance(value, dict):
                inner_data = process_data_recursive(value)
                if inner_data: processed.append({'key': label, 'val': inner_data, 'type': 'section'})
            
            else:
                if value is True: value = "Yes"
                if value is False: value = "No"
                processed.append({'key': label, 'val': value, 'type': 'text'})

        # --- 4. APPEND GROUPS (Only if they have data) ---
        if roof_group['percentages'] or roof_group['main_type'] != '-':
            processed.append(roof_group)
            
        if floor_group['fields']:
            processed.append(floor_group)
            
        if yard_group['fields']:
            processed.append(yard_group)

    return processed