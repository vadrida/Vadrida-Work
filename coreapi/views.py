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
from .utils import generate_site_report_pdf
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


# def admin_dashboard(request):
#     users = UserProfile.objects.all()
#     return render(request, "admin_dashboard.html", {"users": users})


def dashboard(request):
    role = request.session.get("user_role")
    # if role == "admin":
    #     return redirect("coreapi:admin_dashboard")
    if role in ["office", "IT", "site"]:
        return redirect("coreapi:office_dashboard")
    return JsonResponse({"error": "Invalid"}, status=401)

# ================================

def admin_dash(request):
    return render(request,"admin_dashboard.html")

# ==========================

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

# views.py

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
    folders, _ = scan_root_folders_only(DOCUMENTS_FOLDER)

    if q:
        folders = [f for f in folders if q in f["name"].lower() or q in f["id"].lower()]

    return JsonResponse({"folders": folders})

# search files-----------------
def search_files(request):
    q = request.GET.get("q", "").strip().lower()
    
    if not q or len(q) < 2:
        return JsonResponse({"folders": [], "files": []})

    index = get_index()
    
    # 1. Filter Folders
    raw_folders = [f.copy() for f in index.get("folders", []) if q in f["name"].lower()][:20]
    
    processed_folders = []
    
    # --- FIX 1: Get UserProfile Object ---
    user_id = request.session.get("user_id")
    current_user_profile = None
    if user_id:
        try:
            current_user_profile = UserProfile.objects.get(id=user_id)
        except UserProfile.DoesNotExist:
            pass
    # -------------------------------------

    for folder in raw_folders:
        name = folder['name']
        path = folder['path']
        
        # --- A. Chat Pattern Matching ---
        has_hash = "#" in name
        is_case_folder = re.search(r'^\d+_.*\d{2}\.\d{2}\.\d{4}', name)
        
        has_chat = bool(has_hash or is_case_folder)
        
        # --- B. Unread Status Check ---
        is_unread = False
        if has_chat and current_user_profile:
            # --- FIX 2: Pass Object ---
            is_unread = check_unread_status(current_user_profile, path)

        folder['has_chat'] = has_chat
        folder['is_unread'] = is_unread
        
        processed_folders.append(folder)

    matched_files = [f for f in index.get("files", []) if q in f["name"].lower()][:50]

    return JsonResponse({
        "folders": processed_folders,
        "files": matched_files
    })

@require_http_methods(["GET"])
def get_folder_contents_api(request):
    rel_path = request.GET.get("path", "").strip("/") 
    base = os.path.realpath(DOCUMENTS_FOLDER)
    abs_path = os.path.realpath(os.path.join(base, rel_path))
    saved_draft = None
    if not abs_path.startswith(base) or not os.path.isdir(abs_path):
        return JsonResponse({"folders": [], "files": []})
    auto_fill_data = None
    if rel_path:
        current_folder_name = os.path.basename(abs_path)
        auto_fill_data = parse_folder_metadata(current_folder_name)
    folder_name = os.path.basename(abs_path)
    has_hash = "#" in folder_name
    is_case_folder = re.search(r'^\d+_.*\d{2}\.\d{2}\.\d{4}', folder_name)
    is_chat_folder = bool(has_hash or is_case_folder)

    user_id = request.session.get("user_id")
    if user_id and rel_path: # Only check if user is logged in and not at root
        try:
            # Find a report for this user in this specific folder
            draft = SiteVisitReport.objects.filter(
                user_id=user_id, 
                target_folder=rel_path
            ).order_by('-updated_at').first()
            
            if draft and draft.form_data:
                # If form_data is string, parse it; else use as is
                saved_draft = draft.form_data if isinstance(draft.form_data, dict) else json.loads(draft.form_data)
        except Exception as e:
            print(f"Draft fetch error: {e}")

    folder_info = None
    if is_chat_folder:
        folder_info = get_case_folder_info(abs_path)
    folders = []
    files = []
    user_id = request.session.get("user_id")
    current_user_profile = None
    if user_id:
        try:
            current_user_profile = UserProfile.objects.get(id=user_id)
        except UserProfile.DoesNotExist:
            pass
    try:
        with os.scandir(abs_path) as it:
            for entry in it:
                if entry.is_dir():
                    folder_stats = entry.stat()
                    name = entry.name
                    
                    if rel_path:
                        full_rel_path = f"{rel_path}/{name}"
                    else:
                        full_rel_path = name
                    
                    full_abs_path = os.path.join(abs_path, name)
                    has_hash = "#" in name
                    is_case_folder = re.search(r'^\d+_.*\d{2}\.\d{2}\.\d{4}', name)
                    has_chat = bool(has_hash or is_case_folder)
                    
                    is_unread = False
                    if has_chat and current_user_profile:
                        is_unread = check_unread_status(current_user_profile, full_rel_path)
                    
                    status_color = None
                    if has_chat:
                        cache_key = f"folder_status_{full_abs_path}"
                        cached_stats = cache.get(cache_key)
                        if cached_stats:
                            status_color = cached_stats['status_color']
                        else:
                            stats = get_case_folder_info(full_abs_path)
                            if stats:
                                status_color = stats['status_color']

                    folders.append({
                        "name": entry.name,
                        "path": full_rel_path,
                        "type": "folder",
                        "has_chat": has_chat,
                        "is_unread": is_unread,
                        "status_color": status_color,
                        "created": folder_stats.st_mtime
                    })
                else:
                    stats = entry.stat() 
                    ext = os.path.splitext(entry.name)[1].lower()
                    
                    if rel_path:
                        full_file_path = f"{rel_path}/{entry.name}"
                    else:
                        full_file_path = entry.name

                    files.append({
                        "name": entry.name,
                        "path": full_file_path, 
                        "parent_folder": rel_path,
                        "type": "file",
                        "extension": ext,
                        "mime_type": "application/octet-stream",
                        "size": format_file_size(stats.st_size),
                    })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

    # Sort results
    folders.sort(key=lambda x: x.get("created", 0), reverse=True)
    files.sort(key=lambda x: x["name"].lower())
    
    current_folder_info = None
    if bool("#" in os.path.basename(abs_path) or re.search(r'^\d+_.*\d{2}\.\d{2}\.\d{4}', os.path.basename(abs_path))):
         current_folder_info = get_case_folder_info(abs_path)

    return JsonResponse({
        "folders": folders,
        "files": files,
        "folder_info": current_folder_info,
        "auto_fill": auto_fill_data,
        "saved_draft": saved_draft
    })

def parse_folder_metadata(folder_name):
    """
    Robust parsing for various bank folder formats.
    Ignores simple numeric folders (years/ids like '100', '2025').
    """
    # 1. SKIP INVALID FOLDERS
    # If folder is just a number (e.g., "100", "2025"), ignore it.
    if folder_name.isdigit():
        return None
    
    # If folder has no separators (_ or # or -), it's likely a container, not a case.
    if "_" not in folder_name and "#" not in folder_name and " - " not in folder_name:
        return None

    print(f"DEBUG: Parsing case folder -> {folder_name}")

    metadata = {
        'file_no': '',
        'applicant_name': '',
        'product': 'notselected'
    }

    # 2. EXTRACT FILE NUMBER
    # Strict Rule: Must be at the START, followed by a separator (underscore, space, hyphen)
    # or inside a HDFC pattern.
    # ^(\d+)  -> Starts with digits
    # (?=[_ \-]) -> Lookahead ensuring an underscore, space, or dash follows immediately
    file_match = re.search(r'^(\d+)(?=[_ \-])', folder_name)
    
    # Fallback: Sometimes HDFC puts "HDFC - 1011..."
    if not file_match:
        file_match = re.search(r'[\- ]+(\d{4,})(?=[_ \-])', folder_name)

    if file_match:
        metadata['file_no'] = file_match.group(1)

    # 3. PRODUCT MAPPING
    product_map = {
        'RESL': 'resale', 'RESA': 'resale',
        'LAPL': 'lap', 'BLLP': 'lap', 'SBLM': 'lap', 'CCOL': 'lap', 'LAP': 'lap',
        'PRCS': '1st purchase', 'PUCH': '1st purchase', 'LAND': '1st purchase', 'PURC': '1st purchase',
        'CONS': 'construction', 'CONST': 'construction',
        'PDPD': 'pd', 'PD': 'pd',
        'TOUP': 'topup', 'TOP': 'topup',
        'RENO': 'renovation',
        'TAKO': 'takeover', 'HLBG': 'takeover', 'BT': 'takeover'
    }
    
    product_keys = "|".join(product_map.keys())
    # Regex looks for code surrounded by underscores or at boundaries
    prod_match = re.search(f'(?:^|_| )({product_keys})(?:$|_| )', folder_name, re.IGNORECASE)
    
    if prod_match:
        code = prod_match.group(1).upper()
        metadata['product'] = product_map.get(code, 'notselected')

    # 4. APPLICANT NAME STRATEGIES
    # Strategy A: Hash #NAME#
    if '#' in folder_name:
        name_match = re.search(r'#([^#]+)#', folder_name)
        if name_match:
            metadata['applicant_name'] = name_match.group(1).replace('_', ' ').strip()
    
    # Strategy B: Name at the END (After last underscore)
    elif '_' in folder_name:
        parts = folder_name.split('_')
        # Filter empty strings caused by trailing underscores
        parts = [p for p in parts if p.strip()]
        
        if len(parts) > 1:
            possible_name = parts[-1].strip()
            # Clean file extensions if present
            possible_name = re.sub(r'\.[a-zA-Z0-9]{3,}$', '', possible_name)
            
            # Sanity Check: If name is purely digits or a date, it's not a name.
            if not re.match(r'^[\d\.\-]+$', possible_name):
                metadata['applicant_name'] = possible_name
            elif len(parts) > 2:
                # Try the previous part if last part was a date/number
                metadata['applicant_name'] = parts[2]

    # If we didn't find *any* useful data, return None to avoid partial junk fills
    if not metadata['file_no'] and not metadata['applicant_name']:
        return None

    return metadata


@csrf_protect
@require_POST
def auto_save_api(request):
    """
    Saves the current form state to the database.
    Handles duplicate records robustly by keeping only the latest one.
    """
    if not request.session.get("user_id"):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        # Get the User object
        user = UserProfile.objects.get(id=request.session["user_id"])
        
        # Parse Request Data
        data = json.loads(request.body)
        folder_path = data.get('folder_path')
        form_payload = data.get('payload')
        
        if not folder_path or not form_payload:
            return JsonResponse({'success': False, 'error': 'Missing data'})

        # Extract helper fields
        checklist = form_payload.get('Valuers_Checklist', {})
        office_file_no_val = checklist.get('Office_file_no')
        applicant_name_val = checklist.get('applicant_name')

        # --- ROBUST LOOKUP LOGIC START ---
        
        # 1. Find all matching reports for this user and folder
        reports = SiteVisitReport.objects.filter(
            user=user, 
            target_folder=folder_path
        ).order_by('-updated_at') # Newest first

        if reports.exists():
            # Use the newest one
            report = reports.first()
            
            # CLEANUP: If duplicates exist, delete the older ones
            if reports.count() > 1:
                print(f"Cleaning up {reports.count() - 1} duplicate reports for {folder_path}")
                for dup in reports[1:]:
                    dup.delete()
        else:
            # Create new if none exist
            report = SiteVisitReport(user=user, target_folder=folder_path)

        # --- ROBUST LOOKUP LOGIC END ---

        # 2. Update Fields
        report.form_data = form_payload
        report.office_file_no = office_file_no_val
        report.applicant_name = applicant_name_val
        report.save()

        return JsonResponse({
            'success': True, 
            'last_saved': datetime.now().strftime("%H:%M:%S"),
            'report_id': report.id
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
    return render(request, "feedback.html")


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

# --- MAIN VIEW ---
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
        office_file_no_val = checklist_data.get('Office_file_no')
        applicant_name_val = checklist_data.get('applicant_name')
        target_folder_val = payload.get('target_folder') 

        # 3. IDENTIFY REPORT
        report_id = payload.get('report_id')
        report = None

        if report_id:
            try:
                report = SiteVisitReport.objects.get(id=report_id, user=user)
            except SiteVisitReport.DoesNotExist:
                report = None

        if not report and target_folder_val:
            report = SiteVisitReport.objects.filter(
                user=user, 
                target_folder=target_folder_val
            ).order_by('-updated_at').first()

        # 4. EXTRACT IMAGES AND VECTORS
        # We pop 'images' so huge strings don't go into the text DB
        images_data = payload.pop('images', {}) 
        # We KEEP 'vectors' in the payload so the history works, but we reference it
        vectors_data = payload.get('vectors', {})

        # 5. CREATE OR UPDATE REPORT
        if report:
            print(f"Updating report: {report.id}")
            report.form_data = payload
            report.office_file_no = office_file_no_val
            report.applicant_name = applicant_name_val
            if target_folder_val:
                report.target_folder = target_folder_val
            report.save()
        else:
            print("Creating NEW report")
            report = SiteVisitReport.objects.create(
                user=user,
                form_data=payload,
                office_file_no=office_file_no_val,
                applicant_name=applicant_name_val,
                target_folder=target_folder_val
            )

        # 6. PROCESS SKETCHES (Priority: Base64 > Vector Gen)
        
        # Combine keys from both sources to ensure we catch everything
        all_sketch_keys = set(images_data.keys()) | set(vectors_data.keys())

        for source_key in all_sketch_keys:
            image_file = None
            is_base64 = False

            # STRATEGY A: Try Base64 Image (Highest Quality/Exact Match)
            base64_val = images_data.get(source_key)
            if base64_val and isinstance(base64_val, str) and base64_val.startswith('data:image'):
                try:
                    format_header, imgstr = base64_val.split(';base64,') 
                    ext = format_header.split('/')[-1]
                    file_name = f"{source_key}_{report.id}.{ext}"
                    image_file = ContentFile(base64.b64decode(imgstr), name=file_name)
                    is_base64 = True
                except Exception as e:
                    print(f"Base64 error for {source_key}: {e}")

            # STRATEGY B: If no Base64, try generating from Vectors (Fallback)
            if not image_file and source_key in vectors_data:
                print(f"Generating image from vectors for: {source_key}")
                vector_list = vectors_data[source_key]
                # Generate a file named .png
                generated_file = generate_image_from_vectors(vector_list)
                if generated_file:
                    generated_file.name = f"{source_key}_{report.id}_generated.png"
                    image_file = generated_file

            # SAVE TO DB if we have a file
            if image_file:
                ReportSketch.objects.update_or_create(
                    report=report,
                    source_key=source_key,
                    defaults={'image': image_file}
                )
                print(f"Saved sketch for {source_key} (From {'Base64' if is_base64 else 'Vectors'})")

        return JsonResponse({
            'success': True, 
            'report_id': report.id,
            'redirect_url': f"/coreapi/pdf-editor/{report.id}/"
        })

    except Exception as e:
        print(f"Save Feedback Error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)            
# --- STEP 2: RENDER EDITOR PAGE ---
# views.py

# views.py (Update these specific functions)

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
        'target_folder': report.target_folder
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
        # 1. Parse Data
        payload = json.loads(request.body)
        report_id = payload.get('report_id')
        target_path = payload.get('target_folder', '')
        html_content = payload.get('html_content', '')

        if not html_content:
            return JsonResponse({'success': False, 'error': "No HTML content received"}, status=400)

        # ... (Your DB saving logic remains the same) ...

        # 2. Determine Save Directory (Same as before)
        if not target_path or target_path == "/":
            save_dir = settings.DOCUMENTS_ROOT
        else:
            clean_target = target_path.lstrip('/')
            save_dir = os.path.join(settings.DOCUMENTS_ROOT, clean_target)
        
        if not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        # 3. Filename Logic (Same as before)
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

        # --- THE NEW PDF GENERATION (Using Playwright) ---
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            
            # 1. SET CONTENT & WAIT
            # 'networkidle' ensures it waits for images (logo/sketches) to download
            page.set_content(html_content, wait_until="networkidle") 
            
            # 2. GENERATE PDF
            # ... inside finalize_pdf ...

            page.pdf(
                path=full_save_path,
                format="A4",
                margin={ "top": "0", "bottom": "0", "left": "0", "right": "0" },
                print_background=True, 
                scale=1.0 
            )
            browser.close()

        # 4. Backup Logic (Same as before)
        try:
            backup_dir = os.path.join(settings.BASE_DIR, 'generated_pdfs')
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)
            backup_save_path = os.path.join(backup_dir, pdf_filename)
            shutil.copy2(full_save_path, backup_save_path)
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