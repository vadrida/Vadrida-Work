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
import shutil

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
DOCUMENTS_FOLDER = r"G:\My Drive\1005.FOR_IT"

def office_dashboard(request):
    """Main dashboard view"""
    data = get_folders_and_files(DOCUMENTS_FOLDER)
    context = {
        "folders": data['folders'],
        "files": data['files'],
    }
    return render(request, "office_dashboard.html", context)


def get_folders_and_files(base_folder, selected_folder=None):
    """Return folders and files from base folder or selected subfolder"""
    result = {"folders": [], "files": []}

    if not os.path.exists(base_folder):
        os.makedirs(base_folder)
        return result

    # Folders
    for entry in os.listdir(base_folder):
        full_path = os.path.join(base_folder, entry)
        if os.path.isdir(full_path):
            result['folders'].append(entry)

    # Files
    folder_to_scan = os.path.join(base_folder, selected_folder) if selected_folder else base_folder
    if not os.path.exists(folder_to_scan):
        return result

    files_list = []
    for filename in os.listdir(folder_to_scan):
        file_path = os.path.join(folder_to_scan, filename)
        if os.path.isfile(file_path):
            file_stat = os.stat(file_path)
            file_size = file_stat.st_size
            modified_time = file_stat.st_mtime
            file_extension = os.path.splitext(filename)[1].lower()
            mime_type, _ = mimetypes.guess_type(filename)
            category = categorize_file(file_extension)

            files_list.append({
                "id": filename,
                "name": filename,
                "path": os.path.relpath(file_path, base_folder),
                "full_path": file_path,
                "size": format_file_size(file_size),
                "size_bytes": file_size,
                "extension": file_extension,
                "mime_type": mime_type or 'application/octet-stream',
                "category": category,
                "modified": modified_time,
                "type": get_file_type_description(file_extension),
            })

    result['files'] = sorted(files_list, key=lambda x: x['modified'], reverse=True)
    return result


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
def get_folders_api(request):
    """Return all folders"""
    data = get_folders_and_files(DOCUMENTS_FOLDER)
    return JsonResponse({"folders": data['folders']})


@require_http_methods(["GET"])
def get_files_in_folder_api(request):
    """Return files from selected folder"""
    folder = request.GET.get("folder", "")
    data = get_folders_and_files(DOCUMENTS_FOLDER, selected_folder=folder)
    return JsonResponse({"files": data['files']})


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


@csrf_protect
@require_http_methods(["POST"])
def analyze_file(request):
    try:
        data = json.loads(request.body)

        files = data.get("files", [])
        
        selected_folder = data.get("folder")  
        full_user_folder = os.path.join(settings.DOCUMENTS_ROOT, selected_folder)

        if not selected_folder:
            return JsonResponse({"success": False, "error": "User folder not provided"})

        if not os.path.isdir(full_user_folder):
            return JsonResponse({"success": False, "error": "User-selected folder does not exist"})

        if not files:
            return JsonResponse({"success": False, "error": "No files selected"})

        merger = PdfMerger()

        for f in files:
            relative_path = f["file_path"]     # "NewLogo/file1.pdf"
            abs_path = os.path.join(settings.DOCUMENTS_ROOT, relative_path)

            if not os.path.exists(abs_path):
                print("Missing file:", abs_path)
                continue

            if abs_path.lower().endswith(".pdf"):
                merger.append(abs_path)
            else:
                img = Image.open(abs_path).convert("RGB")
                pdf_bytes = io.BytesIO()
                img.save(pdf_bytes, format="PDF")
                pdf_bytes.seek(0)
                merger.append(pdf_bytes)


        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"combined_{timestamp}.pdf"

        # Save only once to project folder
        project_pdf_path = os.path.join(settings.GENERATED_PDFS_ROOT, filename)
        merger.write(project_pdf_path)
        merger.close()

        # Copy the finished file to user folder
        user_pdf_path = os.path.join(full_user_folder, filename)
        shutil.copy(project_pdf_path, user_pdf_path)

        merger.close()

        return JsonResponse({"success": True, "message": "PDF created successfully"})

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})
