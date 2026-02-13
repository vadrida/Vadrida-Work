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
from django.db.models.functions import TruncMonth
from datetime import timedelta, datetime
from django.views.decorators.csrf import csrf_protect
from django.core.paginator import Paginator
from coreapi.search_index import get_index

from .utils import (
    parse_hdfc_folder, parse_muthoot_folder, parse_bajaj_folder,
    parse_dcb_folder, parse_pnbhfl_folder, parse_sbi_folder,
    parse_csb_folder, parse_chola_folder, parse_sib_folder
)
@csrf_protect
def admin_summary_page(request):
    if request.session.get("user_role") not in ["admin", "office", "accountant"]:
        return redirect("coreapi:dashboard")

    # 1. Get Filters from UI
    selected_bank = request.GET.get('bank', '1000.HDFC') # Default
    selected_district = request.GET.get('district', '')

    # 2. Get Data from Memory Index
    index = get_index()
    all_folders = index.get("folders", []) 
    summary_data = []

    # 3. Main Filtering Loop
    for f in all_folders:
        # Bank Filter: The folder path must contain the selected bank string
        # e.g. "G:\My Drive\...\9000.SIB\..."
        if selected_bank in f['path']:
            
            # District Filter: Check if district string is in the name or path
            if selected_district and selected_district not in f['name'] and selected_district not in f['path']:
                continue

            # Validation: Must start with a digit (Case Folder)
            if f['name'][0].isdigit() and '_' in f['name']:
                
                # --- CENTRAL ROUTER ---
                row = {}
                
                if selected_bank == '1000.HDFC':
                    row = parse_hdfc_folder(f)
                    
                elif selected_bank == '2000.Muthoot':
                    row = parse_muthoot_folder(f)
                    
                elif selected_bank == '3000.Bajaj':
                    row = parse_bajaj_folder(f)
                    
                elif selected_bank == '4000.DCB':
                    row = parse_dcb_folder(f)
                    
                elif selected_bank == '5000.PNBHFL':
                    row = parse_pnbhfl_folder(f)
                    
                elif selected_bank == '6000.SBI':
                    row = parse_sbi_folder(f)
                    
                elif selected_bank == '7000.CSB':
                    row = parse_csb_folder(f)
                    
                elif selected_bank == '8000.Chola':
                    row = parse_chola_folder(f)
                    
                elif selected_bank == '9000.SIB':
                    row = parse_sib_folder(f)
                
                # Only add if we successfully parsed a row
                if row:
                    summary_data.append(row)

    # 4. Sorting (Sort by Date Newest First, fallback to File No)
    # We can't easily sort by date since it might be 'Pending', so let's sort by Office File No descending
    def get_sort_key(item):
        val = item.get('office_file_no', '0')
        return int(val) if val.isdigit() else 0
        
    summary_data.sort(key=get_sort_key, reverse=True)

    # 5. Pagination (50 items per page)
    paginator = Paginator(summary_data, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # 6. Render Template
    context = {
        'page_obj': page_obj,
        'selected_bank': selected_bank,
        'selected_district': selected_district,
        'banks': [
            '1000.HDFC', '2000.Muthoot', '3000.Bajaj', '4000.DCB', 
            '5000.PNBHFL', '6000.SBI', '7000.CSB', '8000.Chola', '9000.SIB'
        ],
        'districts': [
            'TVM', 'KLM', 'PTA', 'ALP', 'KTM', 'IDK', 'EKM', 
            'TSR', 'PKD', 'MPM', 'KKD', 'WYD', 'KNR', 'KSD'
        ]
    }
    return render(request, "admin_summary.html", context)


# --- 1. THE MAIN PAGE (HTML Shell) ---
def admin_dashboard(request):
    role = request.session.get("user_role")
    if role not in ["admin", "accountant"]:
        return redirect("coreapi:login_page")
    return render(request, "admin_dashboard.html")


# --- 3. PDF MANAGEMENT ---
# core/views.py

def list_pdfs_api(request):
    """
    Fetches reports from DB that have a PDF generated.
    Returns metadata needed for the Admin Dashboard list.
    """
    if request.session.get("user_role") not in ["admin", "accountant"]:
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
    if request.session.get("user_role") not in ["admin","accountant"]:
        return HttpResponseNotFound("Unauthorized")
        
    filepath = os.path.join(settings.GENERATED_PDFS_ROOT, filename)
    if os.path.exists(filepath):
        return FileResponse(open(filepath, 'rb'), content_type='application/pdf')
    return HttpResponseNotFound("File not found")

def get_report_percent(report):
    """
    Robustly finds the completion percentage.
    Checks:
    1. form_data['completion_metrics']['percent']
    2. form_data['payload']['completion_metrics']['percent'] (Nested case)
    3. report.completion_score (DB Fallback)
    """
    data = report.form_data or {}
    
    # 1. Try to find metrics directly or inside 'payload'
    metrics = data.get('completion_metrics')
    
    if not metrics and 'payload' in data:
        # Check inside 'payload' wrapper if it exists
        payload = data.get('payload')
        if isinstance(payload, dict):
            metrics = payload.get('completion_metrics')

    # 2. Extract the percent value
    val = 0
    if isinstance(metrics, dict):
        val = metrics.get('percent', 0)
    else:
        # Fallback to the database column if JSON fails
        val = report.completion_score

    # 3. Return clean integer
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0



@require_GET
def dashboard_stats_api(request):
    if request.session.get("user_role") not in ["admin", "accountant"]:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    # 1. GLOBAL AVERAGE LOGIC (Keep this as is)
    all_reports = SiteVisitReport.objects.all().only('form_data', 'completion_score')
    total_sum = 0
    count = 0
    for r in all_reports:
        total_sum += get_report_percent(r)
        count += 1
    global_average = round(total_sum / count) if count > 0 else 0

    # 2. TEAM MEMBERS (Updated to include Avg Score)
    # Prefetch reports to avoid N+1 query problem (optimizes speed)
    team_query = UserProfile.objects.exclude(role='admin').prefetch_related('sitevisitreport_set').order_by('-last_seen')
    
    users_data = []
    threshold = timezone.now() - timezone.timedelta(minutes=5)

    for u in team_query:
        is_online = u.last_seen and u.last_seen >= threshold
        
        # --- CALCULATE INDIVIDUAL AVG SCORE ---
        # We loop through this specific user's reports
        u_reports = u.sitevisitreport_set.all() 
        u_sum = 0
        u_count = 0
        for r in u_reports:
            u_sum += get_report_percent(r)
            u_count += 1
        
        user_avg = round(u_sum / u_count) if u_count > 0 else 0

        users_data.append({
            'id': u.id,
            'user_name': u.user_name,
            'role': u.role,
            'is_online': bool(is_online),
            'last_seen': u.last_seen.strftime("%H:%M") if u.last_seen else "Never",
            'current_page': u.current_page if is_online else "Offline",
            'avg_score': user_avg  # <--- NEW FIELD WE NEED FOR SORTING
        })

    # ... (Keep the rest of your view: recent_reports, chats, stats) ... 
    # Just ensure you return 'users_data' in the JsonResponse as 'team_members'

    recent_reports = SiteVisitReport.objects.select_related('user').order_by('-updated_at')[:10]
    reports_data = []
    for r in recent_reports:
        reports_data.append({
            'id': r.id, 'user': r.user.user_name, 'applicant': r.applicant_name,
            'score': get_report_percent(r), 'time': r.updated_at.strftime("%H:%M") 
        })

    chats = ChatMessage.objects.all().order_by('-created_at')[:20]
    chat_data = [{'user': c.user.user_name, 'message': c.content, 'time': c.created_at.strftime("%H:%M")} for c in reversed(chats)]
    
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    reports_today = SiteVisitReport.objects.filter(created_at__gte=today_start).count()

    return JsonResponse({
        'global_average': global_average,
        'team_members': users_data, # Contains the new 'avg_score'
        'recent_reports': reports_data,
        'chats': chat_data,
        'stats': {'today': reports_today, 'total': count}
    })

# --- 2. SPECIFIC USER DETAILS API ---
# core/views.py

def user_details_api(request, user_id):
    if request.session.get("user_role") not in ["admin", "accountant"]:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    user = get_object_or_404(UserProfile, id=user_id)
    
    # 1. Fetch all reports for this user
    reports = SiteVisitReport.objects.filter(user=user).order_by('-updated_at')
    
    total_sum = 0
    count = 0
    recent_work_list = []

    # 2. Iterate to calculate "Real" Average based on JSON Payload
    for i, r in enumerate(reports):
        # Use the helper function that reads 'payload' -> 'completion_metrics' -> 'percent'
        score = get_report_percent(r) 
        
        total_sum += score
        count += 1
        
        # Collect top 5 for the list
        if i < 5:
            recent_work_list.append({
                'id': r.id,
                'office_file_no': r.office_file_no,
                'applicant_name': r.applicant_name,
                'updated_at': r.updated_at,
                'completion_score': score # <--- Send the calculated JSON score, not DB column
            })

    # 3. Calculate Average
    avg_score = round(total_sum / count) if count > 0 else 0
    
    return JsonResponse({
        'name': user.user_name,
        'role': user.role,
        'total_reports': count,
        'avg_score': avg_score, # <--- The correctly calculated average
        'last_seen': user.last_seen,
        'recent_work': recent_work_list
    })

@xframe_options_exempt
def report_detail_view(request, report_id):
    if request.session.get("user_role") not in ["admin", "accountant"]:
        return redirect("coreapi:login_page")
        
    report = get_object_or_404(SiteVisitReport, id=report_id)
    sketches = report.sketches.all()
    
    # USE THE NEW HELPER HERE
    completion_percent = get_report_percent(report)

    # Process Data
    structured_data = process_data_recursive(report.form_data)

    context = {
        'report': report,
        'sketches': sketches,
        'structured_data': structured_data,
        'completion_percent': completion_percent, # Shows correct %
        'pdf_url': f"/core/view-pdf/{report.generated_pdf_name}/" if report.generated_pdf_name else None
    }
    return render(request, "report_detail.html", context)
        
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

def report_analysis_view(request):
    """Renders the Monthly Analysis HTML template."""
    if request.session.get("user_role") not in  ["admin","accountant"]:
        return redirect("coreapi:login_page")
    return render(request, "report_analysis.html")


def analysis_data_api(request):
    if request.session.get("user_role") not in ["admin","accountant"]:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    # 1. GET PARAMETERS
    role_filter = request.GET.get('role', 'site') # default to site
    range_months = request.GET.get('range', '6')
    month_param = request.GET.get('month', '')
    sort_by = request.GET.get('sort_by', 'reports')

    # 2. START BASE QUERY
    all_reports = SiteVisitReport.objects.all().select_related('user')

    # 3. APPLY ROLE FILTER
    if role_filter != 'overall':
        all_reports = all_reports.filter(user__role__iexact=role_filter)

    # 4. APPLY TIME FILTERS
    now = timezone.now()
    if month_param:
        # Filter for a SPECIFIC month
        selected_month = datetime.strptime(month_param, '%Y-%m')
        all_reports = all_reports.filter(
            updated_at__year=selected_month.year,
            updated_at__month=selected_month.month
        )
    elif range_months and range_months != 'none':
        # Filter for a RANGE (e.g., last 6 months)
        start_date = now - timedelta(days=int(range_months) * 30)
        all_reports = all_reports.filter(updated_at__gte=start_date)

    # 5. VELOCITY CALCULATION (Current vs Previous Month)
    start_this_month = now.replace(day=1, hour=0, minute=0, second=0)
    start_last_month = (start_this_month - timedelta(days=1)).replace(day=1)
    
    this_month_count = all_reports.filter(updated_at__gte=start_this_month).count()
    last_month_count = all_reports.filter(updated_at__gte=start_last_month, updated_at__lt=start_this_month).count()
    
    velocity = 0
    if last_month_count > 0:
        velocity = round(((this_month_count - last_month_count) / last_month_count) * 100)
    elif this_month_count > 0:
        velocity = 100

    # 6. GROUP DATA FOR CHART
    monthly_data = {}
    report_scores = []
    for r in all_reports:
        m_key = r.updated_at.strftime('%b %Y')
        if m_key not in monthly_data:
            monthly_data[m_key] = {'sum': 0, 'count': 0}
        
        score = get_report_percent(r) 
        monthly_data[m_key]['sum'] += score
        monthly_data[m_key]['count'] += 1
        report_scores.append(score)

    sorted_months = sorted(monthly_data.keys(), key=lambda x: datetime.strptime(x, '%b %Y'))
    labels = [m for m in sorted_months]
    volumes = [monthly_data[m]['count'] for m in sorted_months]
    qualities = [round(monthly_data[m]['sum'] / monthly_data[m]['count'], 1) for m in sorted_months]

    # 7. TEAM RANKING (Filtered by Role)
    target_users = UserProfile.objects.all()
    if role_filter != 'overall':
        target_users = target_users.filter(role__iexact=role_filter)
    
    team_stats = []
    total_avg_acc = 0
    for u in target_users:
        # Only show users who have reports in the CURRENT FILTERED SET
        u_reports = all_reports.filter(user=u)
        u_count = u_reports.count()
        if u_count > 0:
            u_avg = round(sum(get_report_percent(r) for r in u_reports) / u_count)
            total_avg_acc += u_avg
            team_stats.append({
                'name': u.user_name,
                'reports': u_count,
                'score': u_avg,
                'role_display': u.role.upper(),
                'color': ['#00a884','#34B7F1','#075e54'][len(u.user_name) % 3]
            })

    # Final Average (Weighted by reports to match graph)
    final_avg = round(sum(report_scores) / len(report_scores)) if report_scores else 0

    return JsonResponse({
        'labels': labels, 'volume': volumes, 'quality': qualities,
        'total_count': sum(volumes), 'total_avg': final_avg,
        'team_stats': sorted(team_stats, key=lambda x: x['score' if sort_by=='score' else 'reports'], reverse=True),
        'velocity': velocity
    })
