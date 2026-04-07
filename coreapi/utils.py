import os
import re
from datetime import datetime, timedelta
from django.conf import settings

def get_case_folder_info(abs_path, db_created_at=None):
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
            # If no files, we still want to show something if we have a DB date
            if not db_created_at: return None
            download_dt = db_created_at
        else:
            if db_created_at:
                download_dt = db_created_at
            else:
                earliest_ts = min(f.stat().st_mtime for f in files)
                download_dt = datetime.fromtimestamp(earliest_ts)

        # Ensure download_dt is TZ-naive for comparison with datetime.now()
        if hasattr(download_dt, 'tzinfo') and download_dt.tzinfo is not None:
            download_dt = download_dt.replace(tzinfo=None)

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
        now = datetime.now()
        
        if abs_path.lower().endswith('_hold'):
            status_color = "grey"
            status_label = "ON HOLD"
        elif final_report_dt:
            status_color = "green"
            status_label = "COMPLETED"
        elif now > tat_dt:
            status_color = "red"
            status_label = "OUT OF TAT"
        else:
            status_color = "yellow"
            status_label = "PENDING"

        def fmt(dt): return dt.strftime('%d/%m/%Y') if dt else "N/A"

        # Calculate Duration Metrics
        days_taken = None
        days_overdue = 0
        
        if final_report_dt:
            days_taken = (final_report_dt - download_dt).days
        else:
            days_taken = (now - download_dt).days
            if now > tat_dt:
                days_overdue = (now - tat_dt).days

        return {
            "download_date": fmt(download_dt),
            "tat_date": fmt(tat_dt),
            "site_report_date": fmt(site_report_dt),
            "final_report_date": fmt(final_report_dt),
            "status_color": status_color,
            "status_label": status_label,
            "days_taken": days_taken,
            "days_overdue": days_overdue
        }

    except Exception as e:
        print(f"Error calculating stats: {e}")
        return None