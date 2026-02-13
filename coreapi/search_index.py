import os
from django.conf import settings
import time

FILE_INDEX = None
LAST_UPDATED = 0

def build_index():
    """
    Scans the drive to build a search index including timestamps.
    """
    global FILE_INDEX, LAST_UPDATED

    base_dir = settings.DOCUMENTS_ROOT
    if not os.path.exists(base_dir):
        return {"folders": [], "files": []}

    folders = []
    files = []
    
    # ✅ INCREASED LIMIT: 200,000
    MAX_FILES = 200000 
    file_count = 0

    print("--- STARTING INDEX BUILD (With Dates) ---") 

    try:
        for root, dirnames, filenames in os.walk(base_dir):
            # 1. Skip hidden system folders (.git, .venv, etc)
            dirnames[:] = [d for d in dirnames if not d.startswith('.') and not d.startswith('$')]

            # --- PROCESS FOLDERS ---
            for d in dirnames:
                try:
                    full_dir_path = os.path.join(root, d)
                    rel_path = os.path.relpath(full_dir_path, base_dir).replace("\\", "/")
                    
                    # ✅ CAPTURE TIME FOR FOLDERS TOO
                    try:
                        stat = os.stat(full_dir_path)
                        mtime = stat.st_mtime
                    except:
                        mtime = 0

                    folders.append({ 
                        "name": d, 
                        "path": rel_path,
                        "mtime": mtime  # <--- Added
                    })
                except ValueError: continue

            # --- PROCESS FILES ---
            for f in filenames:
                # Skip hidden files
                if f.startswith('.'): continue 
                
                try:
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, base_dir).replace("\\", "/")
                    
                    # ✅ CRITICAL FIX: CAPTURE MODIFIED TIME HERE
                    # This allows us to sort instanty without touching the disk later
                    try:
                        stat = os.stat(full_path)
                        mtime = stat.st_mtime
                    except Exception:
                        mtime = 0 # Default if file is locked/unreadable

                    files.append({
                        "name": f,
                        "path": rel_path,
                        "mtime": mtime # <--- Added
                    })
                    
                    file_count += 1
                    if file_count >= MAX_FILES:
                        print(f"⚠️ LIMIT REACHED: Stopped at {MAX_FILES} files.")
                        break 
                except OSError: continue

            if file_count >= MAX_FILES:
                break 

        FILE_INDEX = { "folders": folders, "files": files }
        LAST_UPDATED = time.time()
        
        print(f"--- INDEX COMPLETE: Found {len(files)} files and {len(folders)} folders ---")
        
        return FILE_INDEX

    except Exception as e:
        print(f"Error building index: {e}")
        return {"folders": [], "files": []}


# In coreapi/search_index.py

def get_index():
    global FILE_INDEX
    
    # If index is not ready yet (Background thread still running)
    if FILE_INDEX is None:
        print("⚠️ Search attempted before Index was ready. Returning empty results.")
        # Return empty list so the server doesn't freeze/rebuild
        return {"folders": [], "files": []}
        
    return FILE_INDEX
def refresh_index():
    return build_index()