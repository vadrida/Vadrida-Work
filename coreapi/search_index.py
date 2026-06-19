import os
from django.conf import settings
import time

FILE_INDEX = None
LAST_UPDATED = 0

def build_index():
    """
    Scans the drive to build a search index including timestamps.
    Uses os.scandir for efficiency and yields control between directories
    to avoid choking Google Drive's virtual filesystem.
    """
    global FILE_INDEX, LAST_UPDATED

    base_dir = settings.DOCUMENTS_ROOT
    if not os.path.exists(base_dir):
        return {"folders": [], "files": []}

    folders = []
    files = []
    
    MAX_FILES = 200000 
    file_count = 0

    print("--- STARTING INDEX BUILD (With Dates) ---") 

    try:
        def scan_dir(path):
            nonlocal file_count
            if file_count >= MAX_FILES:
                return
            subdirs = []
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        if entry.name.startswith('.') or entry.name.startswith('$'):
                            continue
                            
                        if entry.is_dir(follow_symlinks=False):
                            try:
                                mtime = entry.stat().st_mtime
                            except:
                                mtime = 0
                            rel_path = os.path.relpath(entry.path, base_dir).replace("\\", "/")
                            folders.append({
                                "name": entry.name,
                                "path": rel_path,
                                "mtime": mtime
                            })
                            subdirs.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            try:
                                mtime = entry.stat().st_mtime
                            except:
                                mtime = 0
                            rel_path = os.path.relpath(entry.path, base_dir).replace("\\", "/")
                            files.append({
                                "name": entry.name,
                                "path": rel_path,
                                "mtime": mtime
                            })
                            file_count += 1
                            
                            if file_count >= MAX_FILES:
                                print(f"LIMIT REACHED: Stopped at {MAX_FILES} files.")
                                break
            except OSError:
                pass

            for subdir in subdirs:
                if file_count >= MAX_FILES:
                    break
                # Yield control briefly between directories to avoid
                # saturating Google Drive's virtual filesystem
                time.sleep(0.005)
                scan_dir(subdir)

        scan_dir(base_dir)

        FILE_INDEX = { "folders": folders, "files": files }
        LAST_UPDATED = time.time()
        
        print(f"--- INDEX COMPLETE: Found {len(files)} files and {len(folders)} folders ---")
        
        return FILE_INDEX

    except Exception as e:
        print(f"Error building index: {e}")
        return {"folders": [], "files": []}


def get_index():
    global FILE_INDEX
    
    # If index is not ready yet (Background thread still running)
    if FILE_INDEX is None:
        print("Search attempted before Index was ready. Returning empty results.")
        # Return empty list so the server doesn't freeze/rebuild
        return {"folders": [], "files": []}
        
    return FILE_INDEX

def refresh_index():
    return build_index()