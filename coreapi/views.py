from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.hashers import check_password
from .models import UserProfile
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.middleware.csrf import get_token
from django_ratelimit.decorators import ratelimit
import os,io
import mimetypes
from django.http import JsonResponse, FileResponse, Http404
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from PyPDF2 import PdfMerger
from PIL import Image
from datetime import datetime
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
from .models import UserProfile, SiteVisitReport, ReportSketch
import fitz  
from .utils import generate_site_report_pdf
from django.shortcuts import render, get_object_or_404
import shutil
from urllib.parse import unquote
from django.http import HttpResponseNotFound, HttpResponseBadRequest

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
    
    # 1. Validate Input (Don't search for empty strings)
    if not q or len(q) < 2:
        return JsonResponse({"folders": [], "files": []})

    # 2. Get the index (This is now fast because it's cached)
    index = get_index()
    
    # 3. Filter Results
    # Limit to 50 results to keep the UI snappy
    matched_folders = [f for f in index.get("folders", []) if q in f["name"].lower()][:20]
    matched_files = [f for f in index.get("files", []) if q in f["name"].lower()][:50]

    return JsonResponse({
        "folders": matched_folders,
        "files": matched_files
    })

@require_http_methods(["GET"])
def get_folder_contents_api(request):
    rel_path = request.GET.get("path", "")
    base = os.path.realpath(DOCUMENTS_FOLDER)
    abs_path = os.path.realpath(os.path.join(base, rel_path))

    # Security check
    if not abs_path.startswith(base) or not os.path.isdir(abs_path):
        return JsonResponse({"folders": [], "files": []})

    folders = []
    files = []

    try:
        # PERFORMANCE BOOST: os.scandir gets name AND stats in one go
        with os.scandir(abs_path) as it:
            for entry in it:
                if entry.is_dir():
                    folders.append({
                        "name": entry.name,
                        "path": os.path.join(rel_path, entry.name).replace("\\", "/"),
                        "type": "folder"
                    })
                else:
                    # entry.stat() is cached from the scan! No extra disk access.
                    stats = entry.stat() 
                    ext = os.path.splitext(entry.name)[1].lower()
                    
                    files.append({
                        "name": entry.name,
                        "path": os.path.join(rel_path, entry.name).replace("\\", "/"),
                        "type": "file",
                        "extension": ext,
                        "mime_type": "application/octet-stream", # Calculate real mime only if needed to save time
                        "size": format_file_size(stats.st_size),
                    })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

    # Sort results
    folders.sort(key=lambda x: x["name"].lower())
    files.sort(key=lambda x: x["name"].lower())

    return JsonResponse({
        "folders": folders,
        "files": files
    })


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

@csrf_protect
@require_POST
def save_feedback(request):
    user_id = request.session.get("user_id")
    if not user_id: 
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        user = UserProfile.objects.get(id=user_id)
        request_data = json.loads(request.body)
        
        # 1. Get the payload wrapper
        payload = request_data.get('payload', {})
        
        # 2. Extract Data for Columns
        checklist_data = payload.get('Valuers_Checklist', {})
        office_file_no_val = checklist_data.get('Office_file_no')
        applicant_name_val = checklist_data.get('applicant_name')

        # 3. CHECK IF REPORT ID EXISTS (Update vs Create)
        report_id = payload.get('report_id')

        if report_id:
            # --- UPDATE EXISTING ---
            try:
                report = SiteVisitReport.objects.get(id=report_id, user=user)
                report.form_data = payload
                report.office_file_no = office_file_no_val
                report.applicant_name = applicant_name_val
                report.save()
            except SiteVisitReport.DoesNotExist:
                # If ID sent but not found (rare), create new
                report = SiteVisitReport.objects.create(
                    user=user,
                    form_data=payload,
                    office_file_no=office_file_no_val,
                    applicant_name=applicant_name_val
                )
        else:
            # --- CREATE NEW ---
            report = SiteVisitReport.objects.create(
                user=user,
                form_data=payload,
                office_file_no=office_file_no_val,
                applicant_name=applicant_name_val
            )

        return JsonResponse({
            'success': True, 
            'report_id': report.id,
            'redirect_url': f"/coreapi/pdf-editor/{report.id}/"
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)\
            
            
# --- STEP 2: RENDER EDITOR PAGE ---
# views.py

import json
from django.shortcuts import render, get_object_or_404
from .models import SiteVisitReport

def pdf_editor_page(request, report_id):
    """
    Renders the PDF Editor with data pre-loaded (Server Side Rendering).
    This makes the page load instantly without waiting for a second API call.
    """
    # 1. Fetch the report from the database
    report = get_object_or_404(SiteVisitReport, id=report_id)
    
    # 2. Prepare the data
    # Ensure form_data is a Dictionary, even if stored as a String in DB
    context_data = report.form_data
    if isinstance(context_data, str):
        try:
            context_data = json.loads(context_data)
        except json.JSONDecodeError:
            context_data = {}
            
    if not context_data:
        context_data = {}

    # 3. Pass data directly to the template
    context = {
        'report_id': report_id,
        'data': context_data,  # <--- This carries all text & sketches
        'target_folder': report.target_folder
    }
    
    return render(request, "pdf_editor.html", context)

@require_GET
def get_report_data(request, report_id):
    """API called by the PDF Editor JS to load data"""
    report = get_object_or_404(SiteVisitReport, id=report_id)
    return JsonResponse(report.form_data)
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

        # 2. Update DB
        db_payload = {k: v for k, v in payload.items() if k != 'html_content'}
        report = SiteVisitReport.objects.get(id=report_id)
        report.form_data = db_payload
        report.save()

        # 3. Determine Save Directory
        if not target_path or target_path == "/":
            save_dir = settings.DOCUMENTS_ROOT
        else:
            clean_target = target_path.lstrip('/')
            save_dir = os.path.join(settings.DOCUMENTS_ROOT, clean_target)
        
        if not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        # 4. Versioning Logic
        checklist = payload.get('Valuers_Checklist', {})
        raw_file_no = checklist.get('Office_file_no') or 'Draft'
        raw_name = checklist.get('applicant_name') or 'Report'
        safe_file_no = str(raw_file_no).strip().replace(' ', '_').replace('/', '-')
        safe_name = str(raw_name).strip().replace(' ', '_').replace('/', '-')
        base_filename = f"{safe_file_no}_{safe_name}"
        
        counter = 1
        while True:
            pdf_filename = f"{base_filename}_{counter}.pdf"
            full_save_path = os.path.join(save_dir, pdf_filename)
            if not os.path.exists(full_save_path):
                break
            counter += 1

        # 5. Construct HTML Wrapper with ROBUST CSS
        base_url = request.build_absolute_uri('/')
    
        
        full_html_string = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                @page {{ 
                    size: A4; 
                    margin: 0; 
                }}
                
                body {{ 
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                    background: #fff; 
                    margin: 0;
                    padding: 0;
                }}
                
                /* Layout Container */
                .pdf-sheet {{
                    width: 210mm; 
                    min-height: 297mm; 
                    background: white; 
                    padding: 15mm;
                    box-sizing: border-box; 
                    margin: 0 auto;
                    position: relative;
                    page-break-after: always;
                    overflow: visible; 
                }}

                /* Typography */
                h1 {{ margin: 0 0 10px 0; font-size: 16pt; text-transform: uppercase; text-align: center; color: #333; }}
                
                .section-title {{ 
                    background: #e0e0e0; 
                    padding: 4px 8px; 
                    font-weight: bold; 
                    border: 1px solid #999; 
                    margin-top: 15px; 
                    margin-bottom: 5px; 
                    font-size: 10pt; 
                    page-break-after: avoid; 
                }}
                
                /* --- FIX 1: UPDATED ROW & FIELD BOX --- */
                .row {{ 
                    display: flex; 
                    gap: 10px; 
                    margin-bottom: 5px; 
                    align-items: baseline; 
                }}
                
                label {{ 
                    font-weight: bold; 
                    color: #555; 
                    font-size: 9pt; 
                    margin-right: 5px; 
                    white-space: nowrap; 
                }}
                
                .field-box {{ 
                    border-bottom: 1px dotted #000; 
                    min-height: 18px; 
                    line-height: 1.4;
                    background: transparent; 
                    color: #000; 
                    flex-grow: 1; 
                    font-size: 9pt;
                    white-space: pre-wrap; 
                    overflow-wrap: break-word; 
                    word-break: break-word;
                    display: block;
                    padding-bottom: 2px;
                    overflow: visible; /* ALLOWS EXPANSION */
                }}
                
                /* --- FIX 2: STRICT TABLE LAYOUT --- */
                .report-table {{ 
                    width: 100%; 
                    border-collapse: collapse; 
                    margin-top: 5px; 
                    font-size: 8pt; 
                    table-layout: fixed; /* STRICT WIDTHS */
                    page-break-inside: avoid; 
                }}
                
                .report-table th, .report-table td {{ 
                    border: 1px solid #999; 
                    padding: 4px; 
                    text-align: center; 
                    vertical-align: middle; 
                    overflow-wrap: break-word;
                    word-break: break-word;
                }}
                
                .report-table th {{ background: #f0f0f0; font-weight: bold; }}
                .report-table .field-box {{ border-bottom: none; }}
                
                /* --- FIX 3: HEADER INPUT WRAPPER --- */
                .header-input-wrapper {{
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 2px;
                    width: 100%;
                }}

                .header-input {{
                    border-bottom: 1px solid #ccc !important;
                    background: transparent;
                    width: 100%; 
                    min-height: 18px;
                    font-weight: bold;
                    text-align: center;
                    font-size: 8pt;
                    outline: none;
                }}

                /* --- FIX 4: STACKED ROWS FOR NOTES --- */
                .row-stacked {{
                    display: flex;
                    flex-direction: column;
                    gap: 5px;
                    margin-bottom: 10px;
                    width: 100%;
                }}
                
                .row-stacked .field-box {{
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    padding: 8px;
                    min-height: 50px;
                }}

                /* Checkboxes & Grids */
                .checkbox-group {{ display: flex; flex-wrap: wrap; gap: 10px; }}
                .checkbox-item {{ display: flex; align-items: center; gap: 3px; font-size: 8pt; }}
                .checkbox-grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2px; text-align: left; }}

                /* Images & Sketches */
                .img-wrapper {{ 
                    border: none; 
                    margin: 10px 0; 
                    display: flex; 
                    justify-content: center; 
                    align-items: center; 
                    page-break-inside: avoid; 
                }}
                
                .img-wrapper img {{ 
                    max-width: 100%; 
                    max-height: 400px; 
                    display: block; 
                    object-fit: contain;
                }}
                
                /* Hide UI elements */
                .floating-save, .nav-left, button, .btn-save {{ display: none !important; }}
            </style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """
        # 6. Generate PDF
        HTML(string=full_html_string, base_url=base_url).write_pdf(full_save_path)

        # Backup Logic
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