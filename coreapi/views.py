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
def pdf_editor_page(request, report_id):
    return render(request, "pdf_editor.html", {'report_id': report_id})
def pdf_editor_page(request, report_id):
    """Renders the HTML Editor page you provided"""
    # Verify report exists to prevent 404s later
    get_object_or_404(SiteVisitReport, id=report_id)
    return render(request, "pdf_editor.html", {'report_id': report_id})

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

        # =========================================================
        # 4. VERSIONING LOGIC (OfficeFile_Name_1.pdf)
        # =========================================================
        checklist = payload.get('Valuers_Checklist', {})
        
        # Get raw values and fallback if empty
        raw_file_no = checklist.get('Office_file_no') or 'Draft'
        raw_name = checklist.get('applicant_name') or 'Report'

        # Sanitize strings (remove spaces, slashes, etc. to prevent path errors)
        safe_file_no = str(raw_file_no).strip().replace(' ', '_').replace('/', '-')
        safe_name = str(raw_name).strip().replace(' ', '_').replace('/', '-')

        # Create the base name: "123_JohnDoe"
        base_filename = f"{safe_file_no}_{safe_name}"
        
        counter = 1
        while True:
            # Construct: "123_JohnDoe_1.pdf"
            pdf_filename = f"{base_filename}_{counter}.pdf"
            full_save_path = os.path.join(save_dir, pdf_filename)
            
            # Check if this exact file already exists on disk
            if not os.path.exists(full_save_path):
                # If it doesn't exist, this is our file! Break the loop.
                break
            
            # If it exists, increment counter and try again (e.g., try _2.pdf)
            counter += 1
        # =========================================================

        # 5. Construct HTML Wrapper
        base_url = request.build_absolute_uri('/')
        
        full_html_string = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                @page {{ size: A4; margin: 0; }}
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #fff; }}
                
                /* Layout Styles */
                .pdf-sheet {{
                    width: 210mm; min-height: 297mm; background: white; padding: 15mm;
                    page-break-after: always; box-sizing: border-box; margin: 0 auto;
                }}
                
                h1 {{ margin: 0 0 10px 0; font-size: 16pt; text-transform: uppercase; text-align: center; color: #333; }}
                .section-title {{ background: #e0e0e0; padding: 4px 8px; font-weight: bold; border: 1px solid #999; margin-top: 15px; margin-bottom: 5px; font-size: 10pt; }}
                
                .row {{ display: flex; gap: 10px; margin-bottom: 5px; align-items: flex-start; }}
                label {{ font-weight: bold; color: #555; font-size: 8pt; margin-right: 5px; white-space: nowrap; }}
                
                .field-box {{ 
                    border-bottom: 1px dotted #000; min-height: 18px; line-height: 1.4;
                    background: #fcfcfc; color: #000; flex-grow: 1; 
                    white-space: pre-wrap; overflow-wrap: break-word; display: block;
                }}
                
                .report-table {{ width: 100%; border-collapse: collapse; margin-top: 5px; font-size: 8pt; table-layout: fixed; }}
                .report-table th, .report-table td {{ border: 1px solid #999; padding: 3px; text-align: center; vertical-align: top; overflow-wrap: break-word; }}
                .report-table th {{ background: #f0f0f0; }}
                .report-table .field-box {{ border-bottom: none; }}
                
                .checkbox-group {{ display: flex; flex-wrap: wrap; gap: 10px; }}
                .checkbox-item {{ display: flex; align-items: center; gap: 3px; font-size: 8pt; }}
                
                .img-wrapper {{ border: 2px dashed #ddd; margin: 10px 0; min-height: 150px; display:flex; justify-content:center; align-items: center; }}
                .img-wrapper img {{ max-width: 100%; max-height: 400px; display: block; }}
                
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

        try:
            # Define backup directory: Project Root / generated_pdfs
            backup_dir = os.path.join(settings.BASE_DIR, 'generated_pdfs')
            
            # Ensure folder exists
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)
            
            # Define backup path
            backup_save_path = os.path.join(backup_dir, pdf_filename)
            
            # Copy the newly created file to the backup folder
            shutil.copy2(full_save_path, backup_save_path)
            
            print(f"Backup saved to: {backup_save_path}")
            
        except Exception as copy_error:
            print(f"Warning: Could not save backup copy: {copy_error}")
            # We don't stop the response, just log the error
        # =========================================================
        
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