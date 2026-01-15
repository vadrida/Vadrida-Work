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
        self.interval = 60 # Run every 60 seconds
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
        # --- FIX: WAIT 60 SECONDS BEFORE FIRST SCAN ---
        # This gives the Search Index time to finish building
        # so we don't kill the hard drive speed.
        print(">> Background Task: Monitor waiting 60s for Search Index...")
        time.sleep(60) 
        
        # Now start the loop
        self._scan_all()
        
        while not self._stop_event.is_set():
            time.sleep(self.interval)
            self._scan_all()
    def _scan_all(self):
            try:
                for root, dirs, files in os.walk(self.root_folder):
                    time.sleep(0.01) 
                    folder_name = os.path.basename(root)
                    
                    has_hash = "#" in folder_name
                    is_case_folder = re.search(r'^\d+_.*\d{2}\.\d{2}\.\d{4}', folder_name)
                    
                    if has_hash or is_case_folder:
                        info = get_case_folder_info(root)
                        if info:
                            cache_key = f"folder_status_{root}"
                            cache.set(cache_key, info, timeout=None)
                
            except Exception as e:
                print(f"Error in background scan: {e}")

monitor = FolderStatusMonitor()