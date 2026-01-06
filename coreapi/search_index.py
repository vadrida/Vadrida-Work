import os
from django.conf import settings
import time

FILE_INDEX = None
LAST_UPDATED = 0

def build_index():
    """
    Scans the drive to build a search index.
    """
    global FILE_INDEX, LAST_UPDATED

    base_dir = settings.DOCUMENTS_ROOT
    if not os.path.exists(base_dir):
        return {"folders": [], "files": []}

    folders = []
    files = []
    
    # ✅ INCREASED LIMIT: 10,000 -> 100,000
    MAX_FILES = 150000 
    file_count = 0

    print("--- STARTING INDEX BUILD ---") # Debug print

    try:
        for root, dirnames, filenames in os.walk(base_dir):
            # 1. Skip hidden system folders (.git, .venv, etc)
            dirnames[:] = [d for d in dirnames if not d.startswith('.') and not d.startswith('$')]

            for d in dirnames:
                try:
                    rel_path = os.path.relpath(os.path.join(root, d), base_dir).replace("\\", "/")
                    folders.append({ "name": d, "path": rel_path })
                except ValueError: continue

            for f in filenames:
                # Skip hidden files
                if f.startswith('.'): continue 
                
                try:
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, base_dir).replace("\\", "/")
                    
                    files.append({
                        "name": f,
                        "path": rel_path,
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
        
        # ✅ DEBUG PRINT: Check your terminal for this line!
        print(f"--- INDEX COMPLETE: Found {len(files)} files and {len(folders)} folders ---")
        
        return FILE_INDEX

    except Exception as e:
        print(f"Error building index: {e}")
        return {"folders": [], "files": []}


def get_index():
    global FILE_INDEX
    # If index is empty, build it
    if FILE_INDEX is None:
        return build_index()
    return FILE_INDEX

def refresh_index():
    return build_index()