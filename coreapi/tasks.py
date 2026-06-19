import os
import time
import threading
import re
from django.conf import settings
from django.core.cache import cache
from .utils import get_case_folder_info

class FolderStatusMonitor:
    def __init__(self):
        self.root_folder = settings.DOCUMENTS_ROOT
        self.interval = 600  # Run every 10 minutes (was 60s - too aggressive for Google Drive)
        self._stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)

    def start(self):
        if not self.thread.is_alive():
            self.thread.start()
            print(">> Background Task: Folder Monitor Thread Started")

    def _run_loop(self):
        """
        Continuously scans folders and updates cache.
        """
        # Wait for the Search Index to finish first
        print(">> Background Task: Monitor waiting 120s for Search Index...")
        time.sleep(120)
        
        # Now start the loop
        self._scan_all()
        
        while not self._stop_event.is_set():
            time.sleep(self.interval)
            self._scan_all()

    def _scan_all(self):
        try:
            scanned = 0
            for root, dirs, files in os.walk(self.root_folder):
                # Throttle heavily - Google Drive can't handle rapid I/O
                time.sleep(0.1)
                
                folder_name = os.path.basename(root)
                
                has_hash = "#" in folder_name
                is_case_folder = re.search(r'^\d+_.*\d{2}\.\d{2}\.\d{4}', folder_name)
                
                if has_hash or is_case_folder:
                    info = get_case_folder_info(root)
                    if info:
                        cache_key = f"folder_status_{root}"
                        cache.set(cache_key, info, timeout=None)
                    scanned += 1
                    # Longer pause after actually processing a folder
                    time.sleep(0.2)
                else:
                    # Skip descending into non-relevant deep directories
                    # Only descend into top-level bank folders and their immediate children
                    depth = root.replace(self.root_folder, '').count(os.sep)
                    if depth > 3:
                        dirs.clear()
            
            print(f">> Background Task: Monitor scan complete. {scanned} case folders cached.")
            
        except Exception as e:
            print(f"Error in background scan: {e}")

monitor = FolderStatusMonitor()