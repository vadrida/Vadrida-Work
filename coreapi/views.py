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
from django.views.decorators.http import require_http_methods, require_POST
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
import base64
from django.db.models import Q, Max
import uuid
from django.contrib.auth.decorators import login_required
from .models import SiteVisitReport


def refresh_files(request):
    refresh_index()
    return JsonResponse({"status": "ok"})

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
    if role in ["office", "IT"]:
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

def office_dashboard(request):
    """Main dashboard view"""
    folders, files = scan_folder_tree(DOCUMENTS_FOLDER)

    context = {
        "folders": folders,
        "files": files,
    }
    return render(request, "office_dashboard.html", context)

def scan_folder_tree(base_folder):
    folders = []
    files = []

    for root, dirnames, filenames in os.walk(base_folder):
        rel_root = os.path.relpath(root, base_folder)
        if rel_root == ".":
            rel_root = ""

        for d in dirnames:
            folders.append({
                "id": os.path.join(rel_root, d),
                "name": d,
                "path": os.path.join(rel_root, d)
            })

        for f in filenames:
            full_path = os.path.join(root, f)
            stat = os.stat(full_path)
            ext = os.path.splitext(f)[1].lower()
            mime, _ = mimetypes.guess_type(f)

            files.append({
                "id": f,
                "name": f,
                "path": os.path.join(rel_root, f),
                "folder": rel_root,
                "extension": ext,
                "mime_type": mime or "application/octet-stream",
                "size": format_file_size(stat.st_size),
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
                "type": get_file_type_description(ext),
            })

    return folders, files



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
    folders, _ = scan_folder_tree(DOCUMENTS_FOLDER)

    if q:
        folders = [f for f in folders if q in f["name"].lower() or q in f["id"].lower()]

    return JsonResponse({"folders": folders})

# search files-----------------

def search_files(request):
    q = request.GET.get("q", "").strip().lower()

    if not q:
        return JsonResponse({"folders": [], "files": []})

    index = get_index()

    folders = [f for f in index["folders"] if q in f["name"].lower()]
    files = [f for f in index["files"] if q in f["name"].lower()]

    return JsonResponse({
        "folders": folders[:100],  # limit for safety
        "files": files[:100]
    })


@require_http_methods(["GET"])
def get_folder_contents_api(request):
    rel_path = request.GET.get("path", "")
    base = os.path.realpath(DOCUMENTS_FOLDER)
    abs_path = os.path.realpath(os.path.join(base, rel_path))
    print("DOCUMENTS_ROOT =", settings.DOCUMENTS_ROOT)
    print("ABS PATH =", abs_path)
    print("EXISTS =", os.path.exists(abs_path))
    print("IS DIR =", os.path.isdir(abs_path))

    # Security check
    if not abs_path.startswith(base) or not os.path.isdir(abs_path):
        return JsonResponse({"folders": [], "files": []})

    folders = []
    files = []

    for entry in os.listdir(abs_path):
        full = os.path.join(abs_path, entry)
        rel = os.path.join(rel_path, entry).replace("\\", "/")

        if os.path.isdir(full):
            folders.append({
                "name": entry,
                "path": rel,
                "type": "folder"
            })
        else:
            stat = os.stat(full)
            ext = os.path.splitext(entry)[1].lower()
            mime, _ = mimetypes.guess_type(entry)

            files.append({
                "name": entry,
                "path": rel,
                "type": "file",
                "extension": ext,
                "mime_type": mime or "application/octet-stream",
                "size": format_file_size(stat.st_size),
            })

    return JsonResponse({
        "folders": sorted(folders, key=lambda x: x["name"].lower()),
        "files": sorted(files, key=lambda x: x["name"].lower())
    })




@require_http_methods(["GET"])
def serve_file(request):
    rel_path = request.GET.get("path")
    if not rel_path:
        raise Http404("File path not provided")

    rel_path = rel_path.replace("#", "")
    full_path = os.path.realpath(os.path.join(DOCUMENTS_FOLDER, rel_path))

    if not full_path.startswith(os.path.realpath(DOCUMENTS_FOLDER)):
        raise Http404("Invalid file path")

    if not os.path.exists(full_path):
        raise Http404("File not found")

    mime_type, _ = mimetypes.guess_type(full_path)
    mime_type = mime_type or "application/octet-stream"

    download = request.GET.get("download") == "true"

    response = FileResponse(
        open(full_path, "rb"),
        content_type=mime_type,
        as_attachment=download,
        filename=os.path.basename(full_path),
    )

    response["Accept-Ranges"] = "bytes"

    # OPTIONAL — only if iframe embedding is required
    response["Content-Security-Policy"] = "frame-ancestors *"

    return response


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
    # 1. IMMEDIATE CHECK: Is the user logged in?
    user_id = request.session.get("user_id")
    print(f"Debug: User id : {user_id}")

    if not user_id:
        return JsonResponse({
            'success': False, 
            'error': 'Authentication failed. No user_id in session.'
        }, status=401)

    # --- Fetch the actual User Object ---
    try:
        # Assuming UserProfile is linked to a generic User or is the primary model
        # Adjust 'id' to 'user_id' or 'pk' depending on your model definition
        current_user = UserProfile.objects.get(id=user_id)
    except UserProfile.DoesNotExist:
        return JsonResponse({
            'success': False, 
            'error': 'User record not found in database.'
        }, status=401)
    # -----------------------------------------------

    try:
        # 2. Parse the JSON body
        payload = json.loads(request.body)
        
        # Safe extraction helper
        def get_nested(data, key_path):
            keys = key_path.split('.')
            val = data
            for k in keys:
                val = val.get(k)
                if val is None: return None
            return val

        # Handle lowercase/uppercase mix safely
        office_file_no = get_nested(payload, 'Valuers_Checklist.Office_file_no') or get_nested(payload, 'valuers.Office_file_no')
        applicant_name = get_nested(payload, 'Valuers_Checklist.applicant_name') or get_nested(payload, 'valuers.applicant_name')

        # 3. Handle the Sketch
        sketch_file = None
        sketch_b64 = payload.get('sketch_data')

        if sketch_b64 and 'base64,' in sketch_b64:
            format_str, imgstr = sketch_b64.split(';base64,')
            ext = format_str.split('/')[-1]
            # Use UUID to prevent filename collisions
            filename = f"sketch_{office_file_no or 'unknown'}_{uuid.uuid4()}.{ext}"
            sketch_file = ContentFile(base64.b64decode(imgstr), name=filename)
            
            # Update payload to indicate file is saved, removing the massive base64 string
            payload['sketch_data'] = "Saved as ImageField"

        # 4. Save to Database
        # The 'form_data' field will contain the entire JSON, including 
        # the Survey columns and Boundary dropdown selections.
        report = SiteVisitReport.objects.create(
            user=current_user,  
            office_file_no=office_file_no,
            applicant_name=applicant_name,
            form_data=payload, 
            sketch=sketch_file
        )

        return JsonResponse({
            'success': True, 
            'message': 'Report saved successfully',
            'report_id': report.id
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        print(f"Error saving report: {str(e)}") 
        return JsonResponse({'success': False, 'error': str(e)}, status=500)