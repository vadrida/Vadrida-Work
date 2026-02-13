import re
import os
from datetime import datetime

def check_submission_date(folder_path):
    """
    Scans the folder for any file containing '.dsc' or '_dsc' 
    and returns its creation date.
    """
    try:
        if not os.path.exists(folder_path): return "Pending"
        
        with os.scandir(folder_path) as it:
            for entry in it:
                if entry.is_file() and ('.dsc' in entry.name.lower() or '_dsc' in entry.name.lower()):
                    # Use creation time (Windows) or metadata change time (Unix)
                    timestamp = entry.stat().st_ctime
                    return datetime.fromtimestamp(timestamp).strftime("%d.%m.%Y")
    except:
        pass
    return "Pending"

def parse_sbi_folder(folder_data):
    """
    Specific Parser for 6000.SBI
    Pattern: 6099_ALP_RASMECCALA_30.07.2025_109NNU_103VIS_N.A_CONS_VISHNU PRASAD
    Index:   0    1   2           3          4      5      6   7    8
    """
    name = folder_data['name']
    path = folder_data['path']
    parts = name.split('_')
    
    row = {
        'office_file_no': parts[0] if parts else '---',
        'bank_file_no': '---', # SBI often doesn't have a Bank File No in the name like SIB
        'applicant_name': '---',
        'product': '---',
        'amount': 2000,
        'district': '---',
        'submission_date': 'Pending',
        'office_staff': '---',
        'site_staff': '---',
        'full_path': path
    }

    # 1. Staff Codes (Indices 4 & 5)
    # Heuristic: 3 Digits + 3 Letters (e.g. 109NNU)
    staff_regex = r'^\d{3}[A-Z]{3}$'
    
    # Try to find them by position first (Pattern is strict)
    if len(parts) > 5:
        if re.match(staff_regex, parts[4]):
            row['office_staff'] = parts[4]
        if re.match(staff_regex, parts[5]):
            row['site_staff'] = parts[5]

    # 2. Product (Index 7)
    if len(parts) > 7:
        row['product'] = parts[7]
        # Amount Logic
        if 'PD' in row['product'].upper():
            row['amount'] = 1000
        else:
            row['amount'] = 2000

    # 3. Applicant Name (Last Part)
    if len(parts) > 8:
        # Join everything after product index just in case name has underscores
        row['applicant_name'] = " ".join(parts[8:]).replace('.pdf', '')

    # 4. District (Index 1)
    if len(parts) > 1:
        row['district'] = parts[1]

    # 5. Submission Date (Scan Disk)
    row['submission_date'] = check_submission_date(path)

    return row

def parse_hdfc_folder(folder_data):
    """
    Parser for 1000.HDFC
    Pattern: 1011714_#AJITH_KUMAR_B_S#_TVM_06.02.2026_118XXX_117VMJ_704759274_CONS
    Index:   0       1                 2   3          4      5      6          7
    """
    name = folder_data['name']
    path = folder_data['path']
    parts = name.split('_')
    
    row = {
        'office_file_no': '---',
        'bank_file_no': '---',
        'applicant_name': '---',
        'product': '---',
        'amount': 2000,
        'district': '---',
        'submission_date': 'Pending',
        'office_staff': '---',
        'site_staff': '---',
        'full_path': path
    }

    # 1. Office File No (Index 0)
    if len(parts) > 0 and parts[0].isdigit():
        row['office_file_no'] = parts[0]

    # 2. Applicant Name (Regex for #Name#)
    # This handles names with underscores like #AJITH_KUMAR# correctly
    name_match = re.search(r'#([^#]+)#', name)
    if name_match:
        row['applicant_name'] = name_match.group(1).replace('_', ' ').strip()

    # 3. District (Index 2 - typically after the name block)
    # Since the name might contain underscores, we can't always rely on fixed index 2 if splitting by _.
    # However, your pattern shows the name is wrapped in #..#, effectively separating it.
    # Let's find the part that matches a date pattern, the district is usually before it.
    
    # Robust approach: Find the date, index relative to that.
    date_index = -1
    for i, part in enumerate(parts):
        if re.match(r'\d{2}\.\d{2}\.\d{4}', part):
            date_index = i
            break
            
    if date_index > 0:
        # District is usually immediately before the date
        row['district'] = parts[date_index - 1]
        
        # Staff Codes are usually immediately after the date
        if date_index + 1 < len(parts):
            row['office_staff'] = parts[date_index + 1]
        if date_index + 2 < len(parts):
            row['site_staff'] = parts[date_index + 2]

    # 4. Bank File No & Product (Last 2 parts)
    if len(parts) >= 2:
        row['product'] = parts[-1] # Last item (CONS)
        row['bank_file_no'] = parts[-2] # Second to last (704759274)

    # 5. Amount Calculation
    if 'PD' in row['product'].upper():
        row['amount'] = 1000
    else:
        row['amount'] = 2000

    # 6. Submission Date (Scan Disk for .dsc)
    row['submission_date'] = check_submission_date(path)

    return row

def parse_muthoot_folder(folder_data):
    """
    Parser for 2000.Muthoot
    Pattern: 2425_999OTR_103VIS_ALP_RESL_..._Date_Name
    Index:   0    1      2      3   4        (Date) (Last)
    """
    name = folder_data['name']
    path = folder_data['path']
    parts = name.split('_')
    
    row = {
        'office_file_no': '---',
        'bank_file_no': '---', # Explicitly ignored as requested
        'applicant_name': '---',
        'product': '---',
        'amount': 2000,
        'district': '---',
        'submission_date': 'Pending',
        'office_staff': '---',
        'site_staff': '---',
        'full_path': path
    }

    # 1. Fixed Position Data
    if len(parts) > 4:
        row['office_file_no'] = parts[0]
        row['office_staff'] = parts[1]
        row['site_staff'] = parts[2]
        row['district'] = parts[3]
        row['product'] = parts[4]

    # 2. Amount Calculation
    if 'PD' in row['product'].upper():
        row['amount'] = 1000
    else:
        row['amount'] = 2000

    # 3. Applicant Name (Everything after the Date)
    # We look for the date format 17.01.2026 to separate the tail end
    date_index = -1
    for i, part in enumerate(parts):
        if re.match(r'\d{2}\.\d{2}\.\d{4}', part):
            date_index = i
            break
    
    if date_index != -1 and date_index + 1 < len(parts):
        # Join everything after date (handles names like "SARATH_DAS")
        row['applicant_name'] = " ".join(parts[date_index+1:]).strip()
    elif len(parts) > 0:
        # Fallback: take the last item
        row['applicant_name'] = parts[-1].strip()

    # 4. Submission Date (Scan Disk)
    row['submission_date'] = check_submission_date(path)

    return row

def parse_bajaj_folder(folder_data):
    """
    Parser for 3000.Bajaj
    Pattern: 3112_KNR_10.04.2025_999OTR_106JOJ_SME000015535590_LAPL_NANDA DAIRY
    Index:   0    1   2          3      4      5               6    7
    """
    name = folder_data['name']
    path = folder_data['path']
    parts = name.split('_')
    
    row = {
        'office_file_no': '---',
        'bank_file_no': '---',
        'applicant_name': '---',
        'product': '---',
        'amount': 2000,
        'district': '---',
        'submission_date': 'Pending',
        'office_staff': '---',
        'site_staff': '---',
        'full_path': path
    }

    # 1. Office File No (Index 0)
    if len(parts) > 0 and parts[0].isdigit():
        row['office_file_no'] = parts[0]

    # 2. District (Index 1)
    if len(parts) > 1:
        row['district'] = parts[1]

    # 3. Staff Codes (Indices 3 & 4)
    # The date is at index 2, so staff codes follow immediately
    if len(parts) > 3:
        row['office_staff'] = parts[3]
    if len(parts) > 4:
        row['site_staff'] = parts[4]

    # 4. Bank File No (Index 5)
    if len(parts) > 5:
        row['bank_file_no'] = parts[5]

    # 5. Product (Index 6)
    if len(parts) > 6:
        row['product'] = parts[6]

    # 6. Amount Calculation
    if 'PD' in row['product'].upper():
        row['amount'] = 1000
    else:
        row['amount'] = 2000

    # 7. Applicant Name (Last Part, or join if spaces/underscores exist)
    # Since name is last, we take everything from index 7 onwards
    if len(parts) > 7:
        row['applicant_name'] = " ".join(parts[7:]).strip()

    # 8. Submission Date (Scan Disk)
    row['submission_date'] = check_submission_date(path)

    return row

def parse_dcb_folder(folder_data):
    """
    Parser for 4000.DCB
    Pattern: 40147_KOT_KURUP_31.01.2026_999OTR_114JAY_APPL01487309_LAPL_Suresh M K
    Strategy: Locate the Date, then map fields relative to it.
    """
    name = folder_data['name']
    path = folder_data['path']
    parts = name.split('_')
    
    row = {
        'office_file_no': '---',
        'bank_file_no': '---',
        'applicant_name': '---',
        'product': '---',
        'amount': 2000,
        'district': '---',
        'submission_date': 'Pending',
        'office_staff': '---',
        'site_staff': '---',
        'full_path': path
    }

    # 1. Office File No (Index 0)
    if len(parts) > 0 and parts[0].isdigit():
        row['office_file_no'] = parts[0]

    # 2. District (Index 1)
    if len(parts) > 1:
        row['district'] = parts[1]

    # 3. Dynamic Parsing via Date Anchor
    # We look for the date (31.01.2026) to orient ourselves
    date_index = -1
    for i, part in enumerate(parts):
        if re.match(r'\d{2}\.\d{2}\.\d{4}', part):
            date_index = i
            break
            
    if date_index != -1:
        # Staff Codes are typically immediately after the date
        if date_index + 1 < len(parts):
            row['office_staff'] = parts[date_index + 1]
        if date_index + 2 < len(parts):
            row['site_staff'] = parts[date_index + 2]
            
        # Bank File No is usually 3 steps after date
        if date_index + 3 < len(parts):
            row['bank_file_no'] = parts[date_index + 3]
            
        # Product is usually 4 steps after date
        if date_index + 4 < len(parts):
            row['product'] = parts[date_index + 4]
            
        # Applicant Name is everything after the Product
        if date_index + 5 < len(parts):
            row['applicant_name'] = " ".join(parts[date_index + 5:]).strip()
    
    else:
        # Fallback if no date found (try fixed positions based on your example)
        # 40147_KOT_KURUP_Date_999OTR_114JAY_APPL..._LAPL_Name
        if len(parts) > 7:
            row['office_staff'] = parts[4]
            row['site_staff'] = parts[5]
            row['bank_file_no'] = parts[6]
            row['product'] = parts[7]
            row['applicant_name'] = " ".join(parts[8:]).strip()

    # 4. Amount Calculation
    if 'PD' in row['product'].upper():
        row['amount'] = 1000
    else:
        row['amount'] = 2000

    # 5. Submission Date (Scan Disk)
    row['submission_date'] = check_submission_date(path)

    return row

def parse_pnbhfl_folder(folder_data):
    """
    Parser for 5000.PNBHFL
    Pattern: 50404_EKM_06.02.2026_..._109NNU_NHL.COC..._LAPL_T S BAIJU
    Strategy: Locate the Site Staff Code (109NNU), then map relative to it.
    """
    name = folder_data['name']
    path = folder_data['path']
    parts = name.split('_')
    
    row = {
        'office_file_no': '---',
        'bank_file_no': '---',
        'applicant_name': '---',
        'product': '---',
        'amount': 2000,
        'district': '---',
        'submission_date': 'Pending',
        'office_staff': '---', # Explicitly empty as requested
        'site_staff': '---',
        'full_path': path
    }

    # 1. Office File No (Index 0)
    if len(parts) > 0 and parts[0].isdigit():
        row['office_file_no'] = parts[0]

    # 2. District (Index 1)
    if len(parts) > 1:
        row['district'] = parts[1]

    # 3. Locate Site Staff Code (Anchor Point)
    # We look for the pattern like '109NNU'
    staff_index = -1
    for i, part in enumerate(parts):
        if re.match(r'^\d{3}[A-Z]{3}$', part):
            row['site_staff'] = part
            staff_index = i
            break
            
    # 4. Map fields relative to Staff Code
    if staff_index != -1:
        # Bank File Number is immediately after Site Staff
        if staff_index + 1 < len(parts):
            row['bank_file_no'] = parts[staff_index + 1]
            
        # Product is 2 steps after Site Staff
        if staff_index + 2 < len(parts):
            row['product'] = parts[staff_index + 2]
            
        # Applicant Name is everything after Product
        if staff_index + 3 < len(parts):
            row['applicant_name'] = " ".join(parts[staff_index + 3:]).strip()
            
    else:
        # Fallback if regex fails (Use fixed indices based on your example)
        # 50404_EKM_Date_Loc1_Loc2_109NNU_NHL..._LAPL_Name
        if len(parts) > 7:
            row['bank_file_no'] = parts[-3] # 3rd from last (NHL...)
            row['product'] = parts[-2]      # 2nd from last (LAPL)
            row['applicant_name'] = parts[-1] # Last (Name)

    # 5. Amount Calculation
    if 'PD' in row['product'].upper():
        row['amount'] = 1000
    else:
        row['amount'] = 2000

    # 6. Submission Date (Scan Disk)
    row['submission_date'] = check_submission_date(path)

    return row

def parse_csb_folder(folder_data):
    """
    Parser for 7000.CSB
    Pattern: 7099_KOT_02.05.2025_999OTR_999OTR_LAPL_Joby Jacob
    Index:   0    1   2          3      4      5    6+
    """
    name = folder_data['name']
    path = folder_data['path']
    parts = name.split('_')
    
    row = {
        'office_file_no': '---',
        'bank_file_no': '---', # Not present in CSB pattern
        'applicant_name': '---',
        'product': '---',
        'amount': 2000,
        'district': '---',
        'submission_date': 'Pending',
        'office_staff': '---',
        'site_staff': '---',
        'full_path': path
    }

    # 1. Office File No (Index 0)
    if len(parts) > 0 and parts[0].isdigit():
        row['office_file_no'] = parts[0]

    # 2. District (Index 1)
    if len(parts) > 1:
        row['district'] = parts[1]

    # 3. Staff Codes (Indices 3 & 4)
    # Date is at index 2
    if len(parts) > 3:
        row['office_staff'] = parts[3]
    if len(parts) > 4:
        row['site_staff'] = parts[4]

    # 4. Product (Index 5)
    if len(parts) > 5:
        row['product'] = parts[5]

    # 5. Amount Calculation
    if 'PD' in row['product'].upper():
        row['amount'] = 1000
    else:
        row['amount'] = 2000

    # 6. Applicant Name (Everything after Product)
    if len(parts) > 6:
        row['applicant_name'] = " ".join(parts[6:]).strip()

    # 7. Submission Date (Scan Disk)
    row['submission_date'] = check_submission_date(path)

    return row

def parse_chola_folder(folder_data):
    """
    Parser for 8000.Chola (Handles 2 Patterns)
    Pattern 1: 867_EKM_Date_..._109NNU_867_LAPL_Name
    Pattern 2: 8063_PKD_Date_..._999OTR_HL09..._CONS_Name
    """
    name = folder_data['name']
    path = folder_data['path']
    parts = name.split('_')
    
    row = {
        'office_file_no': '---',
        'bank_file_no': '---',
        'applicant_name': '---',
        'product': '---',
        'amount': 2000,
        'district': '---',
        'submission_date': 'Pending',
        'office_staff': '---',
        'site_staff': '---',
        'full_path': path
    }

    # 1. Office File No (Index 0)
    if len(parts) > 0 and parts[0].isdigit():
        row['office_file_no'] = parts[0]

    # 2. District (Index 1)
    if len(parts) > 1:
        row['district'] = parts[1]

    # 3. Locate Key Indices
    date_index = -1
    staff_index = -1
    product_index = -1

    # Find Date
    for i, part in enumerate(parts):
        if re.match(r'\d{2}\.\d{2}\.\d{4}', part):
            date_index = i
            break
            
    # Find Staff Code (After Date)
    if date_index != -1:
        for i in range(date_index + 1, len(parts)):
            if re.match(r'^\d{3}[A-Z]{3}$', parts[i]):
                staff_index = i
                # Assign to Office/Site based on pattern hints or order
                # For Chola, if only 1 code exists:
                # If it matches '999OTR', it's usually Office Staff
                # Otherwise, it's often Site Staff (like 109NNU)
                if parts[i] == '999OTR':
                    row['office_staff'] = parts[i]
                else:
                    row['site_staff'] = parts[i]
                break
    
    # Find Product (Last recognizable code before Name)
    # We scan from the end backwards, skipping the name
    known_products = ['LAPL', 'CONS', 'RESL', 'TOPU', 'PDPD', 'NPA']
    for i in range(len(parts) - 2, date_index, -1):
        if parts[i] in known_products:
            product_index = i
            row['product'] = parts[i]
            break

    # 4. Fill Gaps
    
    # Bank File No: Between Staff Code and Product
    if staff_index != -1 and product_index != -1:
        if product_index > staff_index + 1:
            potential_bank_no = parts[staff_index + 1]
            # Ignore if it's just a repeat of Office File No
            if potential_bank_no != row['office_file_no']:
                row['bank_file_no'] = potential_bank_no

    # Applicant Name: After Product
    if product_index != -1 and product_index + 1 < len(parts):
        row['applicant_name'] = " ".join(parts[product_index + 1:]).strip()

    # 5. Amount Calculation
    if 'PD' in row['product'].upper():
        row['amount'] = 1000
    else:
        row['amount'] = 2000

    # 6. Submission Date (Scan Disk)
    row['submission_date'] = check_submission_date(path)

    return row

def parse_sib_folder(folder_data):
    """
    Parser for 9000.SIB
    Pattern: 1029004_#SAHADEVAN_#_KOL_19.01.2026_112ULP_9102_LAPL_AGRI_RENEWAL
    Strategy: 
      - Index 0 -> Bank File No (Unique to SIB)
      - Date Anchor used to find District (Before), Staff (After), Office File (After Staff)
    """
    name = folder_data['name']
    path = folder_data['path']
    parts = name.split('_')
    
    row = {
        'office_file_no': '---',
        'bank_file_no': '---',
        'applicant_name': '---',
        'product': '---',
        'amount': 2000,
        'district': '---',
        'submission_date': 'Pending',
        'office_staff': '---',
        'site_staff': '---',
        'full_path': path
    }

    # 1. Bank File No (Index 0 - Specific to this SIB pattern)
    if len(parts) > 0 and parts[0].isdigit():
        row['bank_file_no'] = parts[0]

    # 2. Applicant Name (Regex for #Name#)
    name_match = re.search(r'#([^#]+)#', name)
    if name_match:
        row['applicant_name'] = name_match.group(1).replace('_', ' ').strip()

    # 3. Dynamic Parsing via Date Anchor
    date_index = -1
    for i, part in enumerate(parts):
        if re.match(r'\d{2}\.\d{2}\.\d{4}', part):
            date_index = i
            break
            
    if date_index != -1:
        # District is immediately before Date
        if date_index - 1 >= 0:
            row['district'] = parts[date_index - 1]
            
        # Site Staff is immediately after Date
        if date_index + 1 < len(parts):
            row['site_staff'] = parts[date_index + 1]
            
        # Office File No is 2 steps after Date (After Site Staff)
        if date_index + 2 < len(parts):
            row['office_file_no'] = parts[date_index + 2]
            
        # Product is 3 steps after Date (After Office File No)
        if date_index + 3 < len(parts):
            row['product'] = parts[date_index + 3]

    # 4. Amount Calculation
    if 'PD' in row['product'].upper():
        row['amount'] = 1000
    else:
        row['amount'] = 2000

    # 5. Submission Date (Scan Disk)
    row['submission_date'] = check_submission_date(path)

    return row