from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.hashers import check_password
from .models import UserProfile,ReportSketch
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.middleware.csrf import get_token
from django_ratelimit.decorators import ratelimit
import os,io
import mimetypes
from django.http import JsonResponse, FileResponse, Http404
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from PyPDF2 import PdfMerger
from PIL import Image,ImageDraw
from datetime import datetime, timedelta
import time
from django.conf import settings
from coreapi.search_index import get_index
from coreapi.search_index import refresh_index
from docx import Document
import openpyxl
from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
import base64
from django.db.models import Q, Max
import uuid
from django.contrib.auth.decorators import login_required
from weasyprint import HTML, CSS
from .models import UserProfile, SiteVisitReport
import fitz  
from django.shortcuts import render, get_object_or_404
import shutil
from urllib.parse import unquote
from django.http import HttpResponseNotFound, HttpResponseBadRequest
import re
from django.utils import timezone
from chat.models import FolderChatMessage, FolderChatVisit 
from django.core.cache import cache
from .utils import get_case_folder_info
from playwright.sync_api import sync_playwright
import sys
import asyncio


@csrf_protect
def refresh_files(request):
    try:
        # Rebuild the index synchronously
        refresh_index()
        return JsonResponse({"status": "success", "message": "Index refreshed"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
# ----------------------------
# Login / Logout / Dashboard
# ----------------------------

@ensure_csrf_cookie
def login_page(request):
    if request.session.get("user_id"):
        return redirect("coreapi:dashboard")
    return render(request, "login.html")



def dashboard(request):
    role = request.session.get("user_role")
    
    # 1. Admin goes to the new Core Dashboard
    if role in ["admin", "accountant"]:
        return redirect("core:admin_dashboard") 
        
    # 2. Others go to the Office Dashboard
    elif role == "site":
        return redirect("coreapi:office_dashboard")
    
    elif role == "office":
        return redirect("coreapi:office")
    
    elif role == "IT":
        return redirect("coreapi:office_verification")
    
    # 3. Unknown roles get rejected
    return JsonResponse({"error": "Invalid role"}, status=500)
# ==========================

@csrf_protect
def office_verification(request):
    """
    Renders the three-part office verification dashboard.
    """
    if request.session.get("user_role") not in ["office", "IT"]:
        return redirect("coreapi:login_page")
        
    rel_path = request.GET.get("path", "").strip("/")
    report = None
    
    if rel_path:
        # Fetch the site staff's report for this folder
        report = SiteVisitReport.objects.filter(target_folder=rel_path).first()

    context = {
        'current_path': rel_path,
        'report': report,
        'site_data': report.form_data if report else {},
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
    }
    return render(request, "office_verification.html", context)

@csrf_protect
def get_site_report_data(request):
    file_no = request.GET.get('file_no')
    folder_path = request.GET.get('path', '')
    
    report = None

    # 1. Search Logic (Same as before)
    if raw_path := request.GET.get('path', ''):
        clean_path = unquote(raw_path).replace('\\', '/').replace('G:/My Drive/', '').strip('/')
        report = SiteVisitReport.objects.filter(target_folder__endswith=clean_path).order_by('-updated_at').first()

    if not report and file_no:
        report = SiteVisitReport.objects.filter(office_file_no=file_no).first()

    if report:
        # 2. Prepare Metadata for Sidebar
        meta = {
            "user": report.user.user_name if report.user else "Unknown",  # Get name from UserProfile
            "office_file_no": report.office_file_no,
            "applicant_name": report.applicant_name,
            "target_folder": report.target_folder,
            "created_at": report.created_at.strftime("%d-%b-%Y %I:%M %p"),
            "generated_pdf_name": report.generated_pdf_name or "Not Generated",
            "completion_score": report.completion_score
        }
        
        return JsonResponse({
            'found': True, 
            'data': report.form_data or {}, 
            'meta': meta,
            'real_file_no': report.office_file_no
        })
    else:
        return JsonResponse({'found': False, 'message': 'Report not found'})
      
def save_office_corrections(request):
    """
    Saves corrections back to the SiteVisitReport form_data.
    Handles nested keys like 'Valuers_Checklist.applicant_name'
    """
    if request.method == "POST":
        try:
            payload = json.loads(request.body)
            file_no = payload.get('file_no')
            corrections = payload.get('corrections', {}) # e.g. {'Valuers_Checklist.applicant_name': 'New Name'}

            if not file_no:
                return JsonResponse({'error': 'Missing file number'}, status=400)

            report = SiteVisitReport.objects.filter(office_file_no=file_no).first()
            if not report:
                return JsonResponse({'error': 'Report not found'}, status=404)

            # Get current data
            current_data = report.form_data if report.form_data else {}
            
            # Apply corrections using dot notation (Parent.Child)
            for path, value in corrections.items():
                keys = path.split('.')
                d = current_data
                # Navigate to the last key
                for key in keys[:-1]:
                    if key not in d: 
                        d[key] = {} # Create dict if missing
                    d = d[key]
                # Set the value
                d[keys[-1]] = value
            
            # Save back to DB
            report.form_data = current_data
            report.save()

            return JsonResponse({'success': True, 'message': 'Corrections saved successfully'})

        except Exception as e:
            print(f"Error saving: {e}")
            return JsonResponse({'error': str(e)}, status=500)
            
    return JsonResponse({'error': 'Invalid method'}, status=405)

@csrf_protect
@ratelimit(key="ip", rate="5/m", block=True)
def login_api(request):
    get_token(request)

    if request.method != "POST":
        return JsonResponse({"error": "POST request required"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not email or not password:
        return JsonResponse({"error": "Email and password required"}, status=400)

    try:
        user = UserProfile.objects.get(email=email)
    except UserProfile.DoesNotExist:
        return JsonResponse({"error": "Invalid email or password"}, status=401)

    if not check_password(password, user.password):
        return JsonResponse({"error": "Invalid email or password"}, status=401)

    # SESSION SAVE
    request.session["user_id"] = user.id
    request.session["user_name"] = user.user_name
    request.session["user_email"] = user.email
    request.session["user_role"] = user.role
    request.session.set_expiry(60 * 60 * 12)  # 12 hours
    request.session.modified = True

    return JsonResponse({
        "success": True,
        "message": "Login successful",
        "redirect": "/coreapi/dashboard/"
    })


def logout_api(request):
    request.session.flush()
    return redirect("coreapi:login_page")

# ----------------------------
# File / Folder Handling
# ----------------------------
DOCUMENTS_FOLDER = settings.DOCUMENTS_ROOT

@csrf_protect
def office(request):
    """
    Renders the Office Landing Page with Actions & Profile.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return redirect("coreapi:login_page")
        
    try:
        user_profile = UserProfile.objects.get(id=user_id)
    except UserProfile.DoesNotExist:
        return redirect("coreapi:login_page")

    context = {
        "user_profile": user_profile,
        "last_login": user_profile.last_seen if user_profile.last_seen else "Never",
        "created_at": user_profile.created_at
    }
    return render(request, "office.html", context)

def create_folder_page(request):
    return render(request, "create_folder.html")

def office_dashboard(request):
    """
    Loads the dashboard instantly. 
    Only fetches the top-level folders to populate the sidebar/initial view.
    No files are loaded yet.
    """
    # Only scan the immediate root directory, do NOT walk the whole tree
    folders = scan_root_folders_only(DOCUMENTS_FOLDER) 
    
    context = {
        "folders": folders,
        "files": [], # Empty on purpose. JS will fetch files when a user clicks a folder.
    }
    return render(request, "office_dashboard.html", context)

def scan_root_folders_only(base_folder):
    """
    LIGHTWEIGHT SCANNER: Uses os.scandir for maximum speed.
    Only returns folders in the immediate root.
    """
    folders = []
    try:
        # os.scandir is significantly faster than os.listdir or os.walk
        with os.scandir(base_folder) as it:
            for entry in it:
                if entry.is_dir():
                    folders.append({
                        "id": entry.name,
                        "name": entry.name,
                        "path": entry.name, # Relative path at root is just the name
                        "type": "folder"
                    })
    except Exception as e:
        print(f"Error scanning root: {e}")
        
    # Sort alphabetically
    return sorted(folders, key=lambda x: x['name'].lower())


def categorize_file(extension):
    categories = {
        'A': ['.pdf', '.doc', '.docx'],
        'B': ['.xls', '.xlsx', '.csv'],
        'C': ['.jpg', '.jpeg', '.png', '.gif', '.bmp'],
    }
    for cat, exts in categories.items():
        if extension in exts:
            return cat
    return 'Other'


def get_file_type_description(extension):
    types = {
        '.pdf': 'PDF Document',
        '.doc': 'Word Document',
        '.docx': 'Word Document',
        '.xls': 'Excel Spreadsheet',
        '.xlsx': 'Excel Spreadsheet',
        '.csv': 'CSV File',
        '.jpg': 'Image',
        '.jpeg': 'Image',
        '.png': 'Image',
        '.gif': 'Image',
        '.txt': 'Text File',
    }
    return types.get(extension, 'Document')


def format_file_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

# ----------------------------
# APIs
# ----------------------------
@require_http_methods(["GET"])
def search_folders_api(request):
    q = request.GET.get("q", "").lower()
    
    # 1. Get from Index instead of Disk
    index = get_index()
    all_folders = index.get("folders", [])

    # 2. Filter
    if q:
        folders = [
            f for f in all_folders 
            if q in f["name"].lower() or q in f.get("id", "").lower()
        ]
    else:
        # If no query, return top-level folders (or first 50 cached folders)
        # Assuming your index stores root paths correctly
        folders = all_folders[:50] 

    # 3. Sort Newest First
    folders.sort(key=lambda x: x.get('mtime', 0), reverse=True)

    return JsonResponse({"folders": folders})

# search files-----------------
def search_files(request):
    q = request.GET.get("q", "").strip().lower()
    
    if not q or len(q) < 2:
        return JsonResponse({"folders": [], "files": []})

    # 1. Get the Index (Instant RAM access)
    index = get_index()
    
    # --- HELPER: Sort by Modified Time (Descending) ---
    # Requires 'mtime' to be saved in your index. If missing, defaults to 0.
    def sort_newest(item):
        return item.get('mtime', 0)

    # 2. Filter & Sort FOLDERS
    # We filter first, THEN sort, THEN slice.
    matched_folders = [
        f for f in index.get("folders", []) 
        if q in f["name"].lower()
    ]
    # Sort: Newest First
    matched_folders.sort(key=sort_newest, reverse=True)
    # Slice: Take top 20
    matched_folders = matched_folders[:20]

    # --- PROCESS FOLDERS (Chat/Unread Status) ---
    processed_folders = []
    
    user_id = request.session.get("user_id")
    current_user_profile = None
    if user_id:
        try: current_user_profile = UserProfile.objects.get(id=user_id)
        except: pass

    for folder in matched_folders:
        # Create a copy so we don't mutate the cached index
        f_copy = folder.copy()
        
        name = f_copy['name']
        path = f_copy['path']
        
        has_hash = "#" in name
        is_case_folder = re.search(r'^\d+_.*\d{2}\.\d{2}\.\d{4}', name)
        has_chat = bool(has_hash or is_case_folder)
        
        is_unread = False
        if has_chat and current_user_profile:
            is_unread = check_unread_status(current_user_profile, path)

        f_copy['has_chat'] = has_chat
        f_copy['is_unread'] = is_unread
        processed_folders.append(f_copy)

    # 3. Filter & Sort FILES
    matched_files = [
        f for f in index.get("files", []) 
        if q in f["name"].lower()
    ]
    # Sort: Newest First
    matched_files.sort(key=sort_newest, reverse=True)
    # Slice: Take top 50
    matched_files = matched_files[:50]

    return JsonResponse({
        "folders": processed_folders,
        "files": matched_files
    })


@require_http_methods(["GET"])
def get_folder_contents_api(request):
    rel_path = request.GET.get("path", "").strip("/")
    page = int(request.GET.get("page", 1))
    limit = int(request.GET.get("limit", 50))
    
    base = os.path.realpath(DOCUMENTS_FOLDER)
    abs_path = os.path.realpath(os.path.join(base, rel_path))
    
    saved_draft = None
    folder_info = None
    auto_fill_data = None

    if not abs_path.startswith(base) or not os.path.isdir(abs_path):
        return JsonResponse({"folders": [], "files": [], "has_next": False})

    # --- METADATA (Page 1 Only) ---
    if page == 1:
        if rel_path:
            current_folder_name = os.path.basename(abs_path)
            auto_fill_data = parse_folder_metadata(current_folder_name)
        
        folder_name = os.path.basename(abs_path)
        has_hash = "#" in folder_name
        is_case_folder = re.search(r'^\d+_.*\d{2}\.\d{2}\.\d{4}', folder_name)
        
        if has_hash or is_case_folder:
            folder_info = get_case_folder_info(abs_path)
            user_id = request.session.get("user_id")
            if user_id:
                try:
                    draft = SiteVisitReport.objects.filter(
                        user_id=user_id, target_folder=rel_path
                    ).order_by('-updated_at').first()
                    if draft and draft.form_data:
                        saved_draft = draft.form_data if isinstance(draft.form_data, dict) else json.loads(draft.form_data)
                        # if 'vectors' in saved_draft: del saved_draft['vectors']
                        sketches = ReportSketch.objects.filter(report=draft)
                        if 'images' not in saved_draft: saved_draft['images'] = {}
                        for sketch in sketches:
                            if sketch.image: saved_draft['images'][sketch.source_key] = sketch.image.url
                except Exception as e:
                    print(f"Draft fetch error: {e}")

    # --- SCANNING & SORTING ---
    all_folders = []
    all_files = []
    
    user_id = request.session.get("user_id")
    current_user_profile = None
    if user_id:
        try: current_user_profile = UserProfile.objects.get(id=user_id)
        except: pass

    try:
        with os.scandir(abs_path) as it:
            for entry in it:
                if entry.is_dir():
                    all_folders.append(entry)
                else:
                    all_files.append(entry)

        # ✅ FIX 1: Sort BOTH by Date Descending (Newest First)
        all_folders.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        all_files.sort(key=lambda x: x.stat().st_mtime, reverse=True) # Changed from name to mtime

        # --- PAGINATION SLICE ---
        start = (page - 1) * limit
        end = start + limit
        
        folders_to_process = []
        files_to_process = []
        current_idx = 0
        
        for f in all_folders:
            if current_idx >= start and current_idx < end:
                folders_to_process.append(f)
            current_idx += 1
            
        for f in all_files:
            if current_idx >= start and current_idx < end:
                files_to_process.append(f)
            current_idx += 1

        has_next = current_idx > end

        # --- PROCESS FOLDERS ---
        final_folders = []
        for entry in folders_to_process:
            folder_stats = entry.stat()
            name = entry.name
            full_rel_path = f"{rel_path}/{name}" if rel_path else name
            full_abs_path = os.path.join(abs_path, name)
            
            has_hash = "#" in name
            is_case_folder = re.search(r'^\d+_.*\d{2}\.\d{2}\.\d{4}', name)
            has_chat = bool(has_hash or is_case_folder)
            
            is_unread = False
            status_color = None
            
            if has_chat:
                if current_user_profile:
                    is_unread = check_unread_status(current_user_profile, full_rel_path)
                
                cache_key = f"folder_status_{full_abs_path}"
                cached_stats = cache.get(cache_key)
                if cached_stats:
                    status_color = cached_stats['status_color']
                else:
                    stats = get_case_folder_info(full_abs_path)
                    if stats:
                        status_color = stats['status_color']
                        cache.set(cache_key, stats, 3600)

            final_folders.append({
                "name": name,
                "path": full_rel_path,
                "type": "folder",
                "has_chat": has_chat,
                "is_unread": is_unread,
                "status_color": status_color,
                "created": folder_stats.st_mtime,
                "mtime": folder_stats.st_mtime  # ✅ FIX 2: Send mtime
            })

        # --- PROCESS FILES ---
        final_files = []
        for entry in files_to_process:
            stats = entry.stat()
            ext = os.path.splitext(entry.name)[1].lower()
            full_file_path = f"{rel_path}/{entry.name}" if rel_path else entry.name
            
            final_files.append({
                "name": entry.name,
                "path": full_file_path,
                "parent_folder": rel_path,
                "type": "file",
                "extension": ext,
                "size": format_file_size(stats.st_size),
                "mtime": stats.st_mtime  # ✅ FIX 2: Send mtime
            })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({
        "folders": final_folders,
        "files": final_files,
        "folder_info": folder_info,
        "auto_fill": auto_fill_data,
        "saved_draft": saved_draft,
        "has_next": has_next,
        "page": page
    })


def parse_folder_metadata(folder_name):
    """
    Bank-Specific Parsing Logic for Auto-Fill.
    Detects the pattern based on the starting ID of the folder string.
    """
    print(f"DEBUG: Analyzing Folder -> {folder_name}")

    metadata = {
        'file_no': '',
        'applicant_name': '',
        'product': 'notselected'
    }
    
    # --- PRODUCT CODE MAPPING (Common for all banks) ---
    product_map = {
        'RESL': 'resale', 'RESA': 'resale',
        'LAPL': 'lap', 'BLLP': 'lap', 'SBLM': 'lap', 'CCOL': 'lap', 'LAP': 'lap',
        'PRCS': '1st purchase', 'PUCH': '1st purchase', 'LAND': '1st purchase', 'PURC': '1st purchase', 'PUR': '1st purchase',
        'CONS': 'construction', 'CONST': 'construction',
        'PDPD': 'pd', 'PD': 'pd',
        'TOUP': 'topup', 'TOP': 'topup',
        'RENO': 'renovation',
        'TAKO': 'takeover', 'HLBG': 'takeover', 'BT': 'takeover',
        'NPA': 'npa'
    }

    # Helper to find product in string
    def find_product(text):
        keys = "|".join(product_map.keys())
        match = re.search(f'(?:_|^| )({keys})(?:_|$| )', text, re.IGNORECASE)
        if match:
            return product_map.get(match.group(1).upper(), 'notselected')
        return 'notselected'

    # =========================================================================
    # BANK SPECIFIC STRATEGIES
    # =========================================================================

    # 1. HDFC (1000...) & 9. SIB (9000...)
    # Pattern: ID_#NAME#_Loc_Date_..._PRODUCT
    # Ex: 1011398_#SWAPNA_S_R#_TVM_02.12.2025_118XXX_117VMJ_704656665_RESL
    if folder_name.startswith("10") or folder_name.startswith("90") or folder_name.startswith("10") or "#" in folder_name:
        # File No: Start digits
        file_match = re.match(r'^(\d+)', folder_name)
        if file_match: metadata['file_no'] = file_match.group(1)

        # Name: Inside # hashes #
        name_match = re.search(r'#([^#]+)#', folder_name)
        if name_match: 
            metadata['applicant_name'] = name_match.group(1).replace('_', ' ').strip()
        
        metadata['product'] = find_product(folder_name)
        return metadata

    # 2. Muthoot (2000...)
    # Pattern: ID_Code_Code_Loc_PRODUCT_Loc_Code_Code_Date_NAME
    # Ex: 2427_999OTR_114JAY_KOT_LAPL_KOLLAM_S0147_HKAY92150408_24.01.2026_Anandhumon Shaji
    if folder_name.startswith("2"):
        parts = folder_name.split('_')
        if len(parts) > 1:
            metadata['file_no'] = parts[0] # First part is ID
            metadata['applicant_name'] = parts[-1].strip() # Last part is Name
        metadata['product'] = find_product(folder_name)
        return metadata

    # 3. Bajaj (3000...)
    # Pattern: ID_Loc_Date_Code_Code_LongCode_PRODUCT_NAME
    # Ex: 3120_TSR_08.05.2025_104FMY_107SRJ_SME000015744679_LAPL_Angel Wilson
    if folder_name.startswith("3"):
        parts = folder_name.split('_')
        if len(parts) > 1:
            metadata['file_no'] = parts[0]
            metadata['applicant_name'] = parts[-1].strip()
        metadata['product'] = find_product(folder_name)
        return metadata

    # 4. DCB (4000...)
    # Pattern: ID_Loc_Name_Date_Code_Code_LongCode_PRODUCT_Name2
    # Ex: 40144_KOT_Anil_29.01.2026_999OTR_114JAY_APPL01685793_PDPD_SAJIMON C S
    # Note: Name appears twice sometimes, usually the last one is full name
    if folder_name.startswith("4"):
        parts = folder_name.split('_')
        if len(parts) > 1:
            metadata['file_no'] = parts[0]
            metadata['applicant_name'] = parts[-1].strip() # Prefer last part
        metadata['product'] = find_product(folder_name)
        return metadata

    # 5. PNBHFL (5000...)
    # Pattern: ID_Loc_Date_Loc_PAN_Code_LongCode_PRODUCT_NAME
    # Ex: 50382_KOT_02.02.2026_Kottayam_PAN_114JAY_NHL.KTYM.0126.1473599_LAPL_SNEHA SIBY
    if folder_name.startswith("5"):
        parts = folder_name.split('_')
        if len(parts) > 1:
            metadata['file_no'] = parts[0]
            metadata['applicant_name'] = parts[-1].strip()
        metadata['product'] = find_product(folder_name)
        return metadata

    # 6. SBI (6000...)
    # Pattern: ID_Loc_Code_Date_Code_Code_NA_PRODUCT_NAME
    # Ex: 6097_ALP_RASMECCALA_26.07.2025_109NNU_103VIS_N.A_CONS_PRASEEJA
    if folder_name.startswith("6"):
        parts = folder_name.split('_')
        if len(parts) > 1:
            metadata['file_no'] = parts[0]
            metadata['applicant_name'] = parts[-1].strip()
        metadata['product'] = find_product(folder_name)
        return metadata

    # 7. CSB (7000...)
    # Pattern: ID_Loc_Date_Code_Code_PRODUCT_NAME
    # Ex: 7113_EKM_28.05.2025_109NNU_107SRJ_LAPL_Pathrose
    if folder_name.startswith("7"):
        parts = folder_name.split('_')
        if len(parts) > 1:
            metadata['file_no'] = parts[0]
            metadata['applicant_name'] = parts[-1].strip()
        metadata['product'] = find_product(folder_name)
        return metadata

    # 8. Chola (8000...)
    # Pattern 1: ID_Loc_Date_Loc_Code_ID_PRODUCT_NAME
    # Pattern 2: ID_Loc_Date_Loc_Code_LongCode_PRODUCT_NAME
    # Ex: 864_EKM_02.09.2025_COCHIN _`_109NNU_864_LAPL_REENA and UNNIMAYA
    # Ex: 8065_KOL_21.05.2025_Thiruvalla_106JOJ_HL05NUR000036070_NPA_SHIMOJ PALAKKOOL POLAPPADY
    if folder_name.startswith("8"):
        parts = folder_name.split('_')
        if len(parts) > 1:
            metadata['file_no'] = parts[0]
            metadata['applicant_name'] = parts[-1].strip()
        metadata['product'] = find_product(folder_name)
        return metadata

    # =========================================================================
    # FALLBACK STRATEGY (If none of the above match strictly)
    # =========================================================================
    
    # Try generic underscore splitting
    if '_' in folder_name:
        parts = folder_name.split('_')
        # Assume first part is ID if digits
        if parts[0].isdigit():
            metadata['file_no'] = parts[0]
        
        # Assume last part is Name if not product code
        possible_name = parts[-1].strip()
        # Clean file extensions
        possible_name = re.sub(r'\.[a-zA-Z0-9]{3,}$', '', possible_name)
        
        # Determine product
        found_product = find_product(folder_name)
        if found_product != 'notselected':
            metadata['product'] = found_product
            # If the last part was the product code, take the 2nd to last part as name
            if possible_name.upper() in product_map:
                if len(parts) > 2:
                    metadata['applicant_name'] = parts[-2].strip()
            else:
                metadata['applicant_name'] = possible_name
        else:
             metadata['applicant_name'] = possible_name

    return metadata

def update_user_activity(user_id):
    """Updates last_seen for a user. Call this on key interactions."""
    try:
        UserProfile.objects.filter(id=user_id).update(last_seen=timezone.now())
    except Exception:
        pass

@csrf_protect
@require_POST
def auto_save_api(request):
    user_id = request.session.get("user_id")
    if not user_id:
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    update_user_activity(user_id)

    try:
        user = UserProfile.objects.get(id=user_id)
        data = json.loads(request.body)
        
        current_folder_path = data.get('folder_path', "").strip("/")
        form_payload = data.get('payload', {})
        
        metrics = form_payload.get('completion_metrics', {})
        try:
            score = int(float(metrics.get('percent', 0)))
        except (ValueError, TypeError):
            score = 0
        
        # ---------------------------------------------------------
        # 🛑 LOGIC UPDATE 1: COMPLETION THRESHOLD (< 10%)
        # ---------------------------------------------------------
        # If less than 10%, we acknowledge the request but DO NOT save to DB.
        if score < 10:
            return JsonResponse({
                'success': True, 
                'message': 'Skipped: Completion under 10%',
                'saved': False
            })

        checklist = form_payload.get('Valuers_Checklist', {})
        user_file_no = str(checklist.get('Office_file_no', "")).strip()
        applicant_name = str(checklist.get('applicant_name', "")).strip()

        if not user_file_no or not applicant_name:
             return JsonResponse({'success': False, 'error': 'Required identification missing'})

        # Initial assumption: we save to current folder
        final_target_path = current_folder_path
        folder_changed = False

        # =========================================================
        # 🛡️ STRICT MATCHING & REDIRECTION LOGIC
        # =========================================================
        if score >= 20 and user_file_no:
            current_folder_name = os.path.basename(current_folder_path)
            # Handle cases where folder might not have underscores
            folder_parts = current_folder_name.split('_')
            folder_file_no = folder_parts[0] if folder_parts else ""

            if user_file_no != folder_file_no:
                print(f"🔍 Mismatch! User: {user_file_no} vs Folder: {folder_file_no}. Searching index...")
                
                # Query the In-Memory Index
                index = get_index()
                all_folders = index.get("folders", [])
                
                # Find folder starting with "user_file_no_"
                match = next((f for f in all_folders if f['name'].startswith(f"{user_file_no}_")), None)
                
                if match:
                    final_target_path = match['path']
                    folder_changed = True
                    print(f"🚀 Found correct folder: {final_target_path}")
                else:
                    # Critical mismatch and no valid folder found
                    print(f"❌ No matching folder found for {user_file_no}. Save rejected.")
                    return JsonResponse({
                        'success': False, 
                        'error': 'File Number mismatch. No valid folder found in index.',
                        'mismatch': True
                    })

        # =========================================================
        # 💾 LOGIC UPDATE 2: SAVE OPERATION (Unique Office File No)
        # =========================================================
        
        # We use update_or_create using 'office_file_no' as the ONLY lookup field.
        # This prevents duplicate records for the same file number.
        report, created = SiteVisitReport.objects.update_or_create(
            office_file_no=user_file_no,  # <--- Lookup Key
            defaults={
                'user': user,  # Update the user ownership to the last person who saved
                'target_folder': final_target_path,
                'form_data': form_payload,
                'applicant_name': applicant_name,
                'completion_score': score
            }
        )

        # Cleanup: If we moved folders, ensure no lingering drafts exist under the old folder name
        # (Optional, but good for hygiene)
        if folder_changed:
            SiteVisitReport.objects.filter(
                user=user, 
                target_folder=current_folder_path
            ).exclude(id=report.id).delete()

        return JsonResponse({
            'success': True, 
            'last_saved': datetime.now().strftime("%H:%M:%S"),
            'report_id': report.id,
            'new_folder_path': final_target_path if folder_changed else None,
            'saved': True
        })

    except Exception as e:
        print(f"Auto-save error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
            
# chat folders////////////////

def check_unread_status(user_profile, folder_path):
    # Ensure we actually have a user profile before querying
    if not user_profile:
        return False

    # 1. Check if there are ANY messages in this folder
    last_msg = FolderChatMessage.objects.filter(folder_path=folder_path).last()
    if not last_msg:
        return False # No messages, so it can't be unread
    
    # 2. Check when the user last visited
    visit = FolderChatVisit.objects.filter(user=user_profile, folder_path=folder_path).first()
    
    # 3. Logic: If never visited OR last message is newer than visit -> Unread
    if not visit:
        return True 
    
    return last_msg.timestamp > visit.last_visit

@require_http_methods(["GET"])
def serve_file(request):
    # 1. Get the relative path from the URL
    raw_path = request.GET.get('path')
    if not raw_path:
        return HttpResponseBadRequest("Missing 'path' parameter")
    
    # 2. Decode URL (converts '%20' to space)
    rel_path = unquote(raw_path)
    
    # 3. Construct the Full Path using DOCUMENTS_ROOT (G:\My Drive...)
    # We use os.path.normpath to fix slashes (forward vs backward)
    full_path = os.path.normpath(os.path.join(settings.DOCUMENTS_ROOT, rel_path))

    # 4. Debugging: Print exactly where we are looking (Check your terminal!)
    print(f"--- SERVE FILE DEBUG ---")
    print(f"Looking for: {rel_path}")
    print(f"Full Path:   {full_path}")

    # 5. Check if file exists
    if not os.path.exists(full_path):
        print("ERROR: File not found on disk.")
        return HttpResponseNotFound(f"File not found at: {full_path}")

    # 6. Security Check (Prevent accessing files outside G:\My Drive)
    # This ensures someone can't ask for "..\..\Windows\System32"
    if not full_path.startswith(os.path.normpath(settings.DOCUMENTS_ROOT)):
        return HttpResponseNotFound("Access Denied: Invalid file path.")

    # 7. Serve the file
    content_type, _ = mimetypes.guess_type(full_path)
    if not content_type:
        content_type = 'application/octet-stream'

    response = FileResponse(open(full_path, 'rb'), content_type=content_type)
    
    is_download = request.GET.get('download') == 'true'
    
    if is_download:
        # Force browser to save file
        response['Content-Disposition'] = f'attachment; filename="{os.path.basename(full_path)}"'
    elif 'pdf' in content_type:
        # Otherwise, preview it
        response['Content-Disposition'] = 'inline'  
    return response



import fitz  # PyMuPDF
from django.http import HttpResponse, HttpResponseNotFound
from django.core.cache import cache

def get_thumbnail(request):
    # 1. Get Path
    rel_path = request.GET.get('path')
    if not rel_path:
        return HttpResponseNotFound()
    
    # 2. Clean Path (Handle spaces/encoding)
    rel_path = unquote(rel_path)
    full_path = os.path.normpath(os.path.join(settings.DOCUMENTS_ROOT, rel_path))

    # 3. Security & Existence Check
    if not full_path.startswith(os.path.normpath(settings.DOCUMENTS_ROOT)):
        return HttpResponseNotFound()
    if not os.path.exists(full_path):
        return HttpResponseNotFound()

    # 4. Check Cache (Optional: To make it even faster on reload)
    # cache_key = f"thumb_{rel_path}"
    # cached_img = cache.get(cache_key)
    # if cached_img:
    #     return HttpResponse(cached_img, content_type="image/jpeg")

    try:
        # 5. Generate Image using PyMuPDF (Fast!)
        doc = fitz.open(full_path)
        page = doc.load_page(0)  # Load first page
        pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5))  # 50% scale (thumbnail size)
        img_data = pix.tobytes("jpg")  # Convert to JPG bytes
        
        # cache.set(cache_key, img_data, 60*60*24) # Cache for 24 hours
        return HttpResponse(img_data, content_type="image/jpeg")
        
    except Exception as e:
        print(f"Thumbnail Error: {e}")
        # Return a 1x1 pixel empty image or 404 so browser shows default icon
        return HttpResponseNotFound()
    

# Add this function to views.py
# It uses 'fitz' which you already imported

@require_http_methods(["GET"])
def render_pdf_page(request):
    """
    Renders a specific page of a PDF as an image (PNG).
    Usage: /coreapi/render-page/?path=Folder/file.pdf&page=5&zoom=1.5
    """
    # 1. Get Parameters
    rel_path = request.GET.get('path')
    page_num = int(request.GET.get('page', 0))  # Default to Page 0 (First page)
    zoom = float(request.GET.get('zoom', 1.0))  # Zoom level (1.0 = 100%, 2.0 = 200%)

    if not rel_path:
        return HttpResponseBadRequest("Missing path")

    # 2. Construct Path
    rel_path = unquote(rel_path)
    full_path = os.path.normpath(os.path.join(settings.DOCUMENTS_ROOT, rel_path))

    # 3. Security Check
    if not full_path.startswith(os.path.normpath(settings.DOCUMENTS_ROOT)):
        return HttpResponseNotFound("Access Denied")
    
    if not os.path.exists(full_path):
        return HttpResponseNotFound("File not found")

    try:
        # 4. Open PDF with PyMuPDF
        doc = fitz.open(full_path)
        
        # Validation
        if page_num < 0 or page_num >= len(doc):
             doc.close()
             return HttpResponseNotFound("Page number out of range")

        # 5. Render the Page
        page = doc.load_page(page_num)
        
        # Matrix handles the Zoom/Quality
        # 1.5 zoom is good balance of quality vs speed
        mat = fitz.Matrix(zoom, zoom) 
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        # 6. Convert to PNG bytes
        img_data = pix.tobytes("png")
        
        doc.close()

        # 7. Return Image
        return HttpResponse(img_data, content_type="image/png")

    except Exception as e:
        print(f"PDF Render Error: {e}")
        return HttpResponseBadRequest("Error rendering PDF")

@require_http_methods(["GET"])
def get_file_info(request):
    """Get detailed file information"""
    file_path = request.GET.get('path', '')
    
    if not file_path:
        return JsonResponse({'error': 'File path not provided'}, status=400)
    
    full_path = os.path.join(DOCUMENTS_FOLDER, file_path)
    full_path = os.path.normpath(full_path)
    
    if not full_path.startswith(DOCUMENTS_FOLDER) or not os.path.exists(full_path):
        return JsonResponse({'error': 'File not found'}, status=404)
    
    file_stat = os.stat(full_path)
    
    info = {
        'name': os.path.basename(full_path),
        'size': format_file_size(file_stat.st_size),
        'modified': file_stat.st_mtime,
        'created': file_stat.st_ctime,
        'extension': os.path.splitext(full_path)[1],
    }
    
    return JsonResponse(info)


@require_http_methods(["GET"])
def list_all_folders_api(request):
    folders = []

    for root, dirs, _ in os.walk(DOCUMENTS_FOLDER):
        rel = os.path.relpath(root, DOCUMENTS_FOLDER)
        if rel != ".":
            folders.append(rel.replace("\\", "/"))

    return JsonResponse({"folders": folders})

# ------------------------------------------------

@csrf_protect
@require_http_methods(["POST"])
def analyze_file(request):
    try:
        data = json.loads(request.body)

        files = data.get("files", [])
        selected_folder = data.get("folder")

        if not selected_folder:
            return JsonResponse({"success": False, "error": "Folder not provided"})

        user_folder = os.path.join(settings.DOCUMENTS_ROOT, selected_folder)

        if not os.path.isdir(user_folder):
            return JsonResponse({"success": False, "error": "Selected folder does not exist"})

        if not files:
            return JsonResponse({"success": False, "error": "No files selected"})

        ocr_inputs = []
        direct_texts = []

        # ---------------------------
        # STEP 1: CLASSIFY FILES
        # ---------------------------
        for f in files:
            rel_path = f.get("file_path")
            if not rel_path:
                continue

            abs_path = os.path.normpath(
                os.path.join(settings.DOCUMENTS_ROOT, rel_path)
            )

            if not abs_path.startswith(settings.DOCUMENTS_ROOT):
                return JsonResponse({"success": False, "error": "Invalid file path"})

            if not os.path.exists(abs_path):
                continue

            ext = abs_path.lower()

            if ext.endswith(".pdf"):
                ocr_inputs.append(abs_path)

            elif ext.endswith((".jpg", ".jpeg", ".png", ".bmp", ".tiff")):
                img = Image.open(abs_path).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="PDF")
                buf.seek(0)
                ocr_inputs.append(buf)

            elif ext.endswith(".docx"):
                direct_texts.append(extract_text_from_docx(abs_path))

            elif ext.endswith((".xls", ".xlsx")):
                direct_texts.append(extract_text_from_excel(abs_path))

        extracted_text = []

        # ---------------------------
        # STEP 2: OCR (ONLY IF NEEDED)
        # ---------------------------
        if ocr_inputs:
            merger = PdfMerger()
            for item in ocr_inputs:
                merger.append(item)

            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            temp_pdf_path = os.path.join(
                settings.GENERATED_PDFS_ROOT,
                f"temp_{timestamp}.pdf"
            )

            merger.write(temp_pdf_path)
            merger.close()

            from google.cloud import vision
            client = vision.ImageAnnotatorClient()

            with open(temp_pdf_path, "rb") as f:
                pdf_content = f.read()

            request_vision = vision.AnnotateFileRequest(
                input_config=vision.InputConfig(
                    content=pdf_content,
                    mime_type="application/pdf"
                ),
                features=[
                    vision.Feature(
                        type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION
                    )
                ]
            )

            response = client.batch_annotate_files(
                requests=[request_vision]
            )

            for file_response in response.responses:
                for page_response in file_response.responses:
                    if page_response.full_text_annotation:
                        extracted_text.append(
                            page_response.full_text_annotation.text
                        )

            os.remove(temp_pdf_path)

        # ---------------------------
        # STEP 3: MERGE ALL TEXT
        # ---------------------------
        full_text = "\n".join(direct_texts + extracted_text).strip()

        if not full_text:
            return JsonResponse({
                "success": False,
                "error": "No text detected"
            })

        # ---------------------------
        # STEP 4: SAVE RESULT
        # ---------------------------
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        txt_filename = f"extracted_{timestamp}.txt"
        txt_path = os.path.join(user_folder, txt_filename)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(full_text)

        return JsonResponse({
            "success": True,
            "message": "Text extracted successfully",
            "output_file": txt_filename
        })

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})

def extract_text_from_docx(path):
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def extract_text_from_excel(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    texts = []

    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value:
                    texts.append(str(cell.value))

    return "\n".join(texts)


def feedback(request):
    """Render the feedback form page"""
    if not request.session.get("user_id"):
        return redirect("coreapi:login_page")
    context = {
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
    }
    return render(request, "feedback.html", context)


# --- HELPER: DRAW VECTORS TO IMAGE (Server Side) ---
def generate_image_from_vectors(vector_list, width=1000, height=1000):
    """
    Takes a list of stroke objects (from frontend JSON) and draws them 
    onto a white canvas using Python's Pillow library.
    """
    if not vector_list:
        return None

    try:
        # 1. Create a white canvas
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)

        # 2. Loop through every stroke in the vector list
        for stroke in vector_list:
            points = stroke.get('points', [])
            color = stroke.get('color', '#000000')
            width = int(stroke.get('size', 3))
            
            # Convert JSON points [{'x':1, 'y':1}, ...] to Python tuples [(1,1), ...]
            # We add an offset (e.g. +500) if your coordinates are negative/centered
            # Assuming standard top-left coordinates here, but you might need to adjust
            xy_points = [(p['x'], p['y']) for p in points]

            if len(xy_points) > 1:
                # Draw the line connecting points
                draw.line(xy_points, fill=color, width=width, joint='curve')
            elif len(xy_points) == 1:
                # Draw a dot if it's just one point
                x, y = xy_points[0]
                draw.ellipse([x-width, y-width, x+width, y+width], fill=color)

        # 3. Save to memory buffer
        output = io.BytesIO()
        image.save(output, format="PNG")
        return ContentFile(output.getvalue(), name="generated_sketch.png")

    except Exception as e:
        print(f"Vector generation error: {e}")
        return None
# --- MAIN VIEW (Refactored for Strict Folder Matching) ---
@csrf_protect
@require_POST
def save_feedback(request):
    user_id = request.session.get("user_id")
    if not user_id: 
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        user = UserProfile.objects.get(id=user_id)
        request_data = json.loads(request.body)
        
        # 1. Get Payload
        payload = request_data.get('payload', {})
        
        # 2. Extract Data
        checklist_data = payload.get('Valuers_Checklist', {})
        office_file_no_val = str(checklist_data.get('Office_file_no', "")).strip()
        applicant_name_val = str(checklist_data.get('applicant_name', "")).strip()
        current_folder_path = payload.get('target_folder', "").strip("/")
        
        # 3. Completion Threshold Check
        metrics = payload.get('completion_metrics', {})
        try:
            score = int(float(metrics.get('percent', 0)))
        except (ValueError, TypeError):
            score = 0

        final_target_path = current_folder_path
        folder_changed = False

        # =========================================================
        # 🛡️ THE TRAFFIC CONTROLLER (Strict Folder Matching)
        # =========================================================
        # Logic triggers only if form is >= 20% filled
        if score >= 20 and office_file_no_val:
            # Extract ID from current folder name (e.g., "2428_Mahesh" -> "2428")
            current_folder_name = os.path.basename(current_folder_path)
            folder_file_no = current_folder_name.split('_')[0]

            if office_file_no_val != folder_file_no:
                print(f"🔍 Mismatch! User: {office_file_no_val} vs Folder: {folder_file_no}. Searching index...")
                
                # Query the In-Memory Index (Previously built at server start)
                index = get_index()
                all_folders = index.get("folders", [])
                
                # Search for folder starting with "office_file_no_val_"
                match = next((f for f in all_folders if f['name'].startswith(f"{office_file_no_val}_")), None)
                
                if match:
                    final_target_path = match['path']
                    folder_changed = True
                    print(f"🚀 Found correct folder: {final_target_path}")
                else:
                    # 🛑 ABORT SAVE: Mismatch detected but no matching folder found in index
                    print(f"❌ No matching folder found for {office_file_no_val}. Save rejected.")
                    return JsonResponse({
                        'success': False, 
                        'error': f'Office File No {office_file_no_val} does not match current folder and was not found in system.',
                        'mismatch': True
                    })

        # 4. IDENTIFY REPORT
        report_id = payload.get('report_id')
        report = None

        if report_id:
            report = SiteVisitReport.objects.filter(id=report_id, user=user).first()

        if not report:
            # Use final_target_path to ensure we are looking in the right place
            report = SiteVisitReport.objects.filter(
                user=user, 
                target_folder=final_target_path
            ).order_by('-updated_at').first()

        # 5. EXTRACT IMAGES AND VECTORS
        images_data = payload.pop('images', {}) 
        vectors_data = payload.get('vectors', {})

        # 6. CREATE OR UPDATE REPORT
        if report:
            print(f"Updating report: {report.id}")
            report.form_data = payload
            report.office_file_no = office_file_no_val
            report.applicant_name = applicant_name_val
            report.target_folder = final_target_path # Update to final path
            report.completion_score = score
            report.save()
        else:
            print("Creating NEW report")
            report = SiteVisitReport.objects.create(
                user=user,
                form_data=payload,
                office_file_no=office_file_no_val,
                applicant_name=applicant_name_val,
                target_folder=final_target_path,
                completion_score=score
            )

        # 7. PROCESS SKETCHES (With Explicit Deletion Logic)
        all_sketch_keys = set(images_data.keys()) | set(vectors_data.keys())

        for source_key in all_sketch_keys:
            image_file = None 
            is_base64 = False
            
            base64_val = images_data.get(source_key)
            vector_val = vectors_data.get(source_key)
            
            # ✅ THE MISSING PIECE: If both values are empty, the user cleared the sketch.
            # We MUST delete the record, otherwise the old one stays in the DB forever.
            if not base64_val and not vector_val:
                print(f"🗑️ Deleting sketch record for: {source_key}")
                ReportSketch.objects.filter(report=report, source_key=source_key).delete()
                continue 

            # STRATEGY A: Try Base64 Image
            if base64_val and isinstance(base64_val, str) and base64_val.startswith('data:image'):
                try:
                    format_header, imgstr = base64_val.split(';base64,') 
                    ext = format_header.split('/')[-1]
                    file_name = f"{source_key}_{report.id}.{ext}"
                    image_file = ContentFile(base64.b64decode(imgstr), name=file_name)
                    is_base64 = True
                except Exception as e:
                    print(f"Base64 error for {source_key}: {e}")

            # STRATEGY B: Fallback to Vectors
            if not image_file and vector_val: 
                print(f"Generating image from vectors for: {source_key}")
                generated_file = generate_image_from_vectors(vector_val)
                if generated_file:
                    generated_file.name = f"{source_key}_{report.id}_generated.png"
                    image_file = generated_file

            # SAVE/UPDATE only if we have a valid file
            if image_file:
                ReportSketch.objects.update_or_create(
                    report=report,
                    source_key=source_key,
                    defaults={'image': image_file}
                )

        return JsonResponse({
            'success': True, 
            'report_id': report.id,
            'new_folder_path': final_target_path if folder_changed else None,
            'redirect_url': f"/coreapi/pdf-editor/{report.id}/"
        })

    except Exception as e:
        print(f"Save Feedback Error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
             
# --- STEP 2: RENDER EDITOR PAGE ---


def get_report_data_with_sketches(report):
    """
    Helper function: Merges the saved form text with the images 
    stored in the ReportSketch table.
    """
    # 1. Get the base text data
    context_data = report.form_data
    if isinstance(context_data, str):
        try:
            context_data = json.loads(context_data)
        except json.JSONDecodeError:
            context_data = {}
            
    if not context_data:
        context_data = {}

    # 2. Ensure 'images' key exists
    if 'images' not in context_data:
        context_data['images'] = {}

    # 3. Fetch images from ReportSketch table and re-inject them
    # This puts the URLs back into the JSON so the frontend sees them
    sketches = ReportSketch.objects.filter(report=report)
    for sketch in sketches:
        if sketch.image:
            # We use the file URL so the browser can load it
            context_data['images'][sketch.source_key] = sketch.image.url

    return context_data

def pdf_editor_page(request, report_id):
    """
    Renders the PDF Editor. Now includes the re-injected sketch images.
    """
    report = get_object_or_404(SiteVisitReport, id=report_id)
    
    # Use the helper to get data + images
    full_data = get_report_data_with_sketches(report)

    context = {
        'report_id': report_id,
        'data': full_data, 
        'target_folder': report.target_folder,
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY
    }
    
    return render(request, "pdf_editor.html", context)

@require_GET
def get_report_data(request, report_id):
    """
    API called by the PDF Editor JS (if it uses fetch).
    Now returns data + images.
    """
    report = get_object_or_404(SiteVisitReport, id=report_id)
    full_data = get_report_data_with_sketches(report)
    return JsonResponse(full_data)


@csrf_protect
@require_POST
def finalize_pdf(request):
    try:
        # --- CORRECT FIX: Force ProactorEventLoop for Windows ---
        # Playwright requires subprocesses, which only Proactor supports on Windows.
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        # --------------------------------------------------------

        # 1. Parse Data
        payload = json.loads(request.body)
        report_id = payload.get('report_id')
        target_path = payload.get('target_folder', '')
        html_content = payload.get('html_content', '')

        if not html_content:
            return JsonResponse({'success': False, 'error': "No HTML content received"}, status=400)

        # 2. Determine Save Directory
        if not target_path or target_path == "/":
            save_dir = settings.DOCUMENTS_ROOT
        else:
            clean_target = target_path.lstrip('/')
            save_dir = os.path.join(settings.DOCUMENTS_ROOT, clean_target)
        
        if not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        # 3. Filename Logic
        checklist = payload.get('Valuers_Checklist', {})
        raw_file_no = checklist.get('Office_file_no') or 'Draft'
        raw_name = checklist.get('applicant_name') or 'Report'
        safe_file_no = str(raw_file_no).strip().replace(' ', '_').replace('/', '-')
        safe_name = str(raw_name).strip().replace(' ', '_').replace('/', '-')
        base_filename = f"{safe_file_no}_{safe_name}"
        
        counter = 1
        while True:
            pdf_filename = f"{base_filename}_site_report_{counter}.pdf"
            full_save_path = os.path.join(save_dir, pdf_filename)
            if not os.path.exists(full_save_path):
                break
            counter += 1

        # 4. GENERATE PDF
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            
            # Set content & wait for network to be idle (images loaded)
            page.set_content(html_content, wait_until="networkidle") 
            
            page.pdf(
                path=full_save_path,
                format="A4",
                margin={ "top": "0", "bottom": "0", "left": "0", "right": "0" },
                print_background=True, 
                scale=1.0 
            )
            browser.close()

        # 5. Backup Logic
        try:
            backup_dir = os.path.join(settings.BASE_DIR, 'generated_pdfs')
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)
            backup_save_path = os.path.join(backup_dir, pdf_filename)
            shutil.copy2(full_save_path, backup_save_path)
            
            if report_id:
                try:
                    rpt = SiteVisitReport.objects.get(id=report_id)
                    rpt.generated_pdf_name = pdf_filename 
                    rpt.save()
                except:
                    pass

            return JsonResponse({'success': True, 'file_path': full_save_path})
        except Exception as copy_error:
            print(f"Warning: Could not save backup copy: {copy_error}")
        
        return JsonResponse({'success': True, 'file_path': full_save_path})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ==========================================
#  PDF GENERATION UTILS
# ==========================================

def fill_site_report_pdf(data, images_dict, target_folder_path, filename):
    """
    Fills 'Sitefeedbackform.pdf' template using PyMuPDF (fitz).
    """
    # 1. Setup Paths
    template_path = os.path.join(settings.BASE_DIR, 'static', 'pdf_templates', 'Sitefeedbackform.pdf')
    
    # Handle User Selected Folder
    if not target_folder_path or target_folder_path == "/":
        save_dir = settings.DOCUMENTS_ROOT
    else:
        # Remove leading slash if present to join correctly
        clean_target = target_folder_path.lstrip('/')
        save_dir = os.path.join(settings.DOCUMENTS_ROOT, clean_target)
    
    if not os.path.exists(save_dir):
        os.makedirs(save_dir, exist_ok=True)
        
    output_path = os.path.join(save_dir, filename)

    if not os.path.exists(template_path):
        raise FileNotFoundError(f"PDF Template not found at: {template_path}")

    # 2. Flatten JSON
    flat_data = {}
    
    def flatten(y, prefix=""):
        for k, v in y.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                flatten(v, full_key)
            elif isinstance(v, list):
                flat_data[full_key] = v 
                # Check items for checkboxes
                for item in v:
                    flat_data[f"{full_key}.{item}"] = True
            else:
                flat_data[full_key] = v
                flat_data[k] = v 

    flatten(data)

    # 3. Open PDF & Fill
    doc = fitz.open(template_path)

    for page in doc:
        widgets = list(page.widgets())
        
        for widget in widgets:
            name = widget.field_name
            
            # --- A. IMAGE INSERTION ---
            if name in images_dict:
                b64_img = images_dict[name]
                if b64_img and 'base64,' in b64_img:
                    try:
                        img_data = base64.b64decode(b64_img.split('base64,')[1])
                        rect = widget.rect
                        page.insert_image(rect, stream=img_data, keep_proportion=True)
                        page.delete_widget(widget)
                        continue 
                    except Exception as e:
                        print(f"Image error for {name}: {e}")

            # --- B. DATA FILLING ---
            
            # Checkbox Logic
            if widget.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                is_checked = False
                
                # Case 1: Boolean match (e.g. data is True)
                if name in flat_data and flat_data[name] is True:
                    is_checked = True
                # Case 2: String match (e.g. data is "true")
                elif name in flat_data and str(flat_data[name]).lower() == "true":
                    is_checked = True
                # Case 3: List membership (Value inside a list)
                else:
                    for key, val in flat_data.items():
                        if isinstance(val, list) and name in val:
                            is_checked = True
                            break
                            
                if is_checked:
                    widget.field_value = True
                    widget.update()

            # Text Field Logic
            elif name in flat_data:
                val = flat_data[name]
                if val is not None and not isinstance(val, list) and not isinstance(val, dict):
                    widget.field_value = str(val)
                    widget.update()

    # 4. Save
    doc.flatten_form_fields()
    doc.save(output_path)
    doc.close()
    
    return output_path


def assetlinks(request):
    data = [{
      "relation": ["delegate_permission/common.handle_all_urls"],
      "target": {
        "namespace": "android_app",
        "package_name": "com.vadrida.app",
        "sha256_cert_fingerprints": [
            "8B:52:BA:5E:C0:CF:17:21:D7:1D:E6:60:41:E7:4F:F1:9D:4A:84:CA:4D:54:8E:77:58:3B:4D:AB:74:7E:2F:38"
        ]
      }
    }]
    return JsonResponse(data, safe=False)