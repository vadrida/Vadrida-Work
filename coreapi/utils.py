import os
import re
from datetime import datetime, timedelta
from django.conf import settings

def get_case_folder_info(abs_path):
    """
    Calculates TAT, Report Dates, and Status.
    MOVED here so background tasks can use it.
    """
    try:
        files = []
        try:
            with os.scandir(abs_path) as it:
                for entry in it:
                    if entry.is_file():
                        files.append(entry)
        except OSError:
            return None

        if not files:
            return None

        earliest_ts = min(f.stat().st_mtime for f in files)
        download_dt = datetime.fromtimestamp(earliest_ts)
        tat_dt = download_dt + timedelta(days=3)

        site_report_dt = None
        final_report_dt = None
        
        for f in files:
            name_lower = f.name.lower()
            
            # Check Site Report
            if "site_report" in name_lower:
                ts = f.stat().st_mtime
                if site_report_dt is None or ts > site_report_dt.timestamp():
                    site_report_dt = datetime.fromtimestamp(ts)
            
            # Check Final Report (.DSC or _DSC)
            if ".dsc" in name_lower or "_dsc" in name_lower:
                ts = f.stat().st_mtime
                if final_report_dt is None or ts > final_report_dt.timestamp():
                    final_report_dt = datetime.fromtimestamp(ts)

        # Status Logic
        status_color = "grey"
        status_label = "Pending"
        now = datetime.now()

        if final_report_dt:
            status_color = "green"
            status_label = "Completed"
        else:
            if now <= tat_dt:
                if site_report_dt:
                    status_color = "yellow"
                    status_label = "Site report submitted"
                else:
                    status_color = "grey"
                    status_label = "Pending"
            else:
                status_color = "red"
                status_label = "Out of TAT"

        def fmt(dt): return dt.strftime('%d/%m/%Y') if dt else "N/A"

        return {
            "download_date": fmt(download_dt),
            "tat_date": fmt(tat_dt),
            "site_report_date": fmt(site_report_dt),
            "final_report_date": fmt(final_report_dt),
            "status_color": status_color,
            "status_label": status_label
        }

    except Exception as e:
        print(f"Error calculating stats: {e}")
        return None