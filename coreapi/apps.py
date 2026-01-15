from django.apps import AppConfig
import threading
import sys
import os

class CoreapiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'coreapi'

    def ready(self):
        ignore_commands = ['makemigrations', 'migrate', 'collectstatic', 'test', 'shell']
        if any(cmd in sys.argv for cmd in ignore_commands):
            return
        is_runserver = 'runserver' in sys.argv
        is_reloader_process = os.environ.get('RUN_MAIN') == 'true'
        should_run = (is_runserver and is_reloader_process) or (not is_runserver)

        if should_run:
            from . import search_index
            def run_indexing():
                print(">> Background Task: Pre-building Search Index...", flush=True)
                try:
                    search_index.build_index()
                    print(">> Background Task: Search Index Ready!", flush=True)
                except Exception as e:
                    print(f"!! CRITICAL ERROR building index: {e}", flush=True)

            index_thread = threading.Thread(target=run_indexing)
            index_thread.daemon = True
            index_thread.start()
            from .tasks import monitor
            monitor.start()