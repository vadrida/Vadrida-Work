import os
from django.conf import settings

FILE_INDEX = None

def build_index():
    global FILE_INDEX

    base_dir = r"C:\Users\asus\Desktop\2025-2026_Invoices"
    folders = []
    files = []

    for root, dirnames, filenames in os.walk(base_dir):
        for d in dirnames:
            folders.append({
                "name": d,
                "path": os.path.relpath(os.path.join(root, d), base_dir)
            })

        for f in filenames:
            full = os.path.join(root, f)
            files.append({
                "name": f,
                "path": os.path.relpath(full, base_dir),
                "extension": os.path.splitext(f)[1].lower(),
                "size": os.path.getsize(full)
            })

    FILE_INDEX = {
        "folders": folders,
        "files": files
    }

    return FILE_INDEX


def get_index():
    global FILE_INDEX
    if FILE_INDEX is None:
        return build_index()
    return FILE_INDEX


def refresh_index():
    return build_index()
