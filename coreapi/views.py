from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.hashers import check_password
from .models import UserProfile
import json
from django.shortcuts import render, redirect
from django.middleware.csrf import get_token
from django_ratelimit.decorators import ratelimit
import os,io
import mimetypes
from django.http import JsonResponse, FileResponse, Http404
from django.views.decorators.http import require_http_methods
from PyPDF2 import PdfMerger
from PIL import Image
from datetime import datetime
from django.conf import settings
from coreapi.search_index import get_index
from coreapi.search_index import refresh_index

def refresh_files(request):
    refresh_index()
    return JsonResponse({"status": "ok"})

# ----------------------------
# Login / Logout / Dashboard
# ----------------------------
def login_page(request):
    if request.session.get("user_id"):
        return redirect("coreapi:dashboard")
    return render(request, "login.html")


def admin_dashboard(request):
    users = UserProfile.objects.all()
    return render(request, "admin_dashboard.html", {"users": users})


def dashboard(request):
    role = request.session.get("user_role")
    if role == "admin":
        return redirect("coreapi:admin_dashboard")
    if role in ["office", "IT"]:
        return redirect("coreapi:office_dashboard")
    return JsonResponse({"error": "Invalid"}, status=401)


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
DOCUMENTS_FOLDER = r"C:\Users\asus\Desktop\2025-2026_Invoices"

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


# all folder contents =============


def folder_contents(request):
    rel_path = request.GET.get("path", "")
    base = settings.DOCUMENTS_ROOT
    abs_path = os.path.normpath(os.path.join(base, rel_path))

    if not abs_path.startswith(base):
        return JsonResponse({"folders": [], "files": []})

    folders, files = [], []

    for name in os.listdir(abs_path):
        full = os.path.join(abs_path, name)
        if os.path.isdir(full):
            folders.append({"name": name, "path": os.path.join(rel_path, name)})
        else:
            files.append({
                "name": name,
                "path": os.path.join(rel_path, name),
                "extension": os.path.splitext(name)[1].lower(),
                "size": os.path.getsize(full)
            })

    return JsonResponse({"folders": folders, "files": files})


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
    rel_path = request.GET.get("path", "")
    if not rel_path:
        raise Http404("File path not provided")

    rel_path = rel_path.replace("#", "")
    full_path = os.path.realpath(os.path.join(DOCUMENTS_FOLDER, rel_path))

    if not full_path.startswith(os.path.realpath(DOCUMENTS_FOLDER)):
        raise Http404("Invalid file path")

    if not os.path.exists(full_path):
        raise Http404(f"File not found: {rel_path}")

    mime_type, _ = mimetypes.guess_type(full_path)
    mime_type = mime_type or "application/pdf"
    download = request.GET.get("download", "false").lower() == "true"

    response = FileResponse(open(full_path, "rb"), content_type=mime_type)
    if download:
        response["Content-Disposition"] = f'attachment; filename="{os.path.basename(full_path)}"'
    else:
        response["Content-Disposition"] = f'inline; filename="{os.path.basename(full_path)}"'

    response["Accept-Ranges"] = "bytes"
    response["X-Frame-Options"] = "ALLOWALL"
    response["Content-Security-Policy"] = "frame-ancestors *"
    response["Access-Control-Allow-Origin"] = "*"
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

        # ---------------------------
        # STEP 1: Create TEMP merged PDF
        # ---------------------------
        merger = PdfMerger()

        for f in files:
            rel_path = f.get("file_path")
            if not rel_path:
                continue

            abs_path = os.path.normpath(os.path.join(settings.DOCUMENTS_ROOT, rel_path))

            # Security: prevent ../ traversal
            if not abs_path.startswith(settings.DOCUMENTS_ROOT):
                return JsonResponse({"success": False, "error": "Invalid file path"})

            if not os.path.exists(abs_path):
                continue

            if abs_path.lower().endswith(".pdf"):
                merger.append(abs_path)
            else:
                img = Image.open(abs_path).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="PDF")
                buf.seek(0)
                merger.append(buf)

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        temp_pdf_path = os.path.join(
            settings.GENERATED_PDFS_ROOT, f"temp_{timestamp}.pdf"
        )

        merger.write(temp_pdf_path)
        merger.close()

        # ---------------------------
        # STEP 2: Google Vision OCR
        # ---------------------------
        from google.cloud import vision

        client = vision.ImageAnnotatorClient()

        with open(temp_pdf_path, "rb") as f:
            pdf_content = f.read()

        input_config = vision.InputConfig(
            content=pdf_content,
            mime_type="application/pdf"
        )

        feature = vision.Feature(
            type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION
        )

        request_vision = vision.AnnotateFileRequest(
            input_config=input_config,
            features=[feature]
        )

        response = client.batch_annotate_files(
            requests=[request_vision]
        )

        # ---------------------------
        # STEP 3: Extract text
        # ---------------------------
        extracted_text = []

        for file_response in response.responses:
            for page_response in file_response.responses:
                if page_response.full_text_annotation:
                    extracted_text.append(
                        page_response.full_text_annotation.text
                    )

        full_text = "\n".join(extracted_text).strip()

        if not full_text:
            return JsonResponse({
                "success": False,
                "error": "No text detected in documents"
            })

        # ---------------------------
        # STEP 4: Save TXT to user folder
        # ---------------------------
        txt_filename = f"extracted_{timestamp}.txt"
        txt_path = os.path.join(user_folder, txt_filename)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(full_text)

        # ---------------------------
        # STEP 5: Cleanup TEMP PDF
        # ---------------------------
        os.remove(temp_pdf_path)

        return JsonResponse({
            "success": True,
            "message": "Text extracted successfully",
            "output_file": txt_filename
        })

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})
