import os
import base64
import io
import uuid
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as ReportLabImage, PageBreak
from django.conf import settings

def generate_site_report_pdf(data, images_dict, target_folder_path, filename):
    """
    Generates a complete Site Feedback Report PDF matching the provided format.
    """
    # --- 1. SETUP PATHS ---
    if not target_folder_path or target_folder_path == "/":
        save_dir = settings.DOCUMENTS_ROOT
    else:
        save_dir = os.path.join(settings.DOCUMENTS_ROOT, target_folder_path)
    
    if not os.path.exists(save_dir):
        os.makedirs(save_dir, exist_ok=True)
        
    full_path = os.path.join(save_dir, filename)

    # --- 2. STYLES & HELPERS ---
    doc = SimpleDocTemplate(full_path, pagesize=A4, 
                            rightMargin=20, leftMargin=20, 
                            topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()
    
    # Custom Styles to match the form look
    styleH1 = ParagraphStyle('Header1', parent=styles['Heading1'], fontSize=14, spaceAfter=10, alignment=1) # Center
    styleH2 = ParagraphStyle('Header2', parent=styles['Heading2'], fontSize=11, spaceBefore=10, spaceAfter=5, textColor=colors.black, backColor=colors.lightgrey, borderPadding=2)
    styleNormal = ParagraphStyle('Normal', parent=styles['Normal'], fontSize=9, leading=11)
    styleBold = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=9, leading=11, fontName='Helvetica-Bold')
    styleSmall = ParagraphStyle('Small', parent=styles['Normal'], fontSize=7, leading=8)

    def get_image(key, width=450, height=200):
        """Decodes Base64 image and returns a ReportLab Image flowable."""
        b64_data = images_dict.get(key)
        if not b64_data or 'base64,' not in b64_data:
            return None
        try:
            img_data = base64.b64decode(b64_data.split('base64,')[1])
            img_io = io.BytesIO(img_data)
            img = ReportLabImage(img_io)
            # Scaling
            img_width = img.imageWidth
            img_height = img.imageHeight
            factor = min(width/img_width, height/img_height)
            img.drawWidth = img_width * factor
            img.drawHeight = img_height * factor
            return img
        except:
            return None

    def make_checkbox(label, is_checked):
        """Returns a string representation of a checkbox."""
        mark = "X" if is_checked else " "
        return f"[{mark}] {label}"

    # ================== PDF CONTENT GENERATION ==================

    # --- PAGE 1 ---
    # [cite: 1-6] Valuers Checklist Header
    story.append(Paragraph("VALUERS CHECKLIST", styleH1))
    
    vc = data.get('Valuers_Checklist', {})
    
    # [cite: 1-4] Basic Info Grid
    info_data = [
        [Paragraph("<b>1. Office File No:</b>", styleNormal), vc.get('Office_file_no', ''),
         Paragraph("<b>2. Applicant Name:</b>", styleNormal), vc.get('applicant_name', '')],
        [Paragraph("<b>3. Inspection Date:</b>", styleNormal), vc.get('inspection_date', ''),
         Paragraph("<b>4. Person Met:</b>", styleNormal), vc.get('person_met', '')]
    ]
    t = Table(info_data, colWidths=[80, 150, 80, 200])
    t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
    story.append(t)
    story.append(Spacer(1, 10))

    # [cite: 7, 11-19] 5. Product (Checkboxes)
    prod_val = vc.get('product', '').lower()
    products = [
        "1st purchase", "Construction", "Topup", "PD", "Resale",
        "Renovation", "Takeover", "LAP", "Extension", "NPA"
    ]
    prod_items = []
    for p in products:
        checked = (p.lower() == prod_val)
        prod_items.append(make_checkbox(p, checked))
    
    story.append(Paragraph("<b>5. Product:</b> " + "   ".join(prod_items), styleNormal))
    story.append(Spacer(1, 8))

    # [cite: 8, 20-36] 6. Documents Received (Checkboxes)
    story.append(Paragraph("<b>6. Documents Received:</b>", styleNormal))
    docs_received = vc.get('documents_received', [])
    doc_options = [
        "Agreement", "Declaration", "Title Deed", "Encumbrance", "Location Sketch",
        "Survey Sketch", "Building Tax receipt", "LTR", "Possession", "Building Permit",
        "Development Permit", "Building Certificate", "Approved Plan", "Engineers Plan"
    ]
    doc_flowables = []
    for d in doc_options:
        checked = d in docs_received
        doc_flowables.append(make_checkbox(d, checked))
    
    # Wrap documents in a table for grid layout
    doc_grid = [doc_flowables[i:i+4] for i in range(0, len(doc_flowables), 4)]
    t_docs = Table(doc_grid, colWidths=[130]*4)
    story.append(t_docs)
    story.append(Spacer(1, 10))

    # [cite: 9] I. Ownership Analysis
    oa = data.get('Ownership_Analysis', {})
    story.append(Paragraph("I. Ownership Analysis", styleH2))
    
    # [cite: 10, 37-38]
    doc_verif = oa.get('document_verification', [])
    check_same = make_checkbox("Same in all documents", "same in all documents" in doc_verif)
    check_diff = make_checkbox("Discrepancy noted", "discrepancy noted" in doc_verif)
    
    oa_data = [
        [Paragraph("<b>1. Owner(s) Name:</b>", styleNormal), oa.get('owners_name', '')],
        [Paragraph(f"<b>Verification:</b> {check_same}   {check_diff}", styleNormal), ""]
    ]
    story.append(Table(oa_data, colWidths=[100, 400]))
    
    # Notes & Image
    story.append(Paragraph(f"<b>Notes:</b> {oa.get('Ownership_Analysis_notes', '-')}", styleNormal))
    img_oa = get_image('Ownership_Analysis.Ownership_Analysis_notes')
    if img_oa: story.append(img_oa)
    story.append(Spacer(1, 10))

    # [cite: 39-49] II. Survey Analysis
    sv = data.get('Survey', {})
    story.append(Paragraph("II. Survey Number and Land Extent Analysis", styleH2))
    
    survey_headers = ["Doc Name", "Re-Sy Blk", "Re-Sy No", "Re-Sy Sub", "Sy Blk", "Sy No", "Sy Sub", "Extent (Ares)", "Class"]
    survey_rows = [[Paragraph(h, styleSmall) for h in survey_headers]]
    
    for doc in sv.get('docs', []):
        if not doc.get('name'): continue
        row = [
            Paragraph(doc.get('name', ''), styleSmall),
            doc.get('re_sy_block_no', ''), doc.get('re_sy_no', ''), doc.get('re_sy_subdiv_no', ''),
            doc.get('sy_block_no', ''), doc.get('sy_no', ''), doc.get('sy_subdiv_no', ''),
            doc.get('land_extent', ''), Paragraph(doc.get('land_classification', ''), styleSmall)
        ]
        survey_rows.append(row)
        
    t_sv = Table(survey_rows, colWidths=[70, 35, 35, 40, 35, 35, 40, 50, 80])
    t_sv.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey)]))
    story.append(t_sv)
    
    story.append(Paragraph(f"<b>Notes/Wetland:</b> {sv.get('survey_notes', '-')}", styleNormal))
    img_sv = get_image('Survey.survey_notes')
    if img_sv: story.append(img_sv)
    story.append(PageBreak())

    # --- PAGE 2 ---
    # [cite: 50-52] III. Boundary Analysis
    ba = data.get('Boundary_analysis_property_identification', {})
    story.append(Paragraph("III. Boundary Analysis and Property Identification", styleH2))
    
    bound_headers = ["", "Doc 1", "Doc 2", "Translation Reason", "Site"]
    bound_rows = [[Paragraph(h, styleBold) for h in bound_headers]]
    
    for direction in ["North", "East", "South", "West"]:
        d_lower = direction.lower()
        bound_rows.append([
            direction,
            ba.get(f'{d_lower}_doc1', ''),
            ba.get(f'{d_lower}_doc2', ''),
            ba.get(f'{d_lower}_translation', ''),
            ba.get(f'{d_lower}_site', '')
        ])
        
    t_ba = Table(bound_rows, colWidths=[50, 100, 100, 120, 100])
    t_ba.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black)]))
    story.append(t_ba)
    
    story.append(Paragraph(f"<b>Notes:</b> {ba.get('Boundary_property_notes', '-')}", styleNormal))
    img_ba = get_image('Boundary_analysis_property_identification.Boundary_property_notes')
    if img_ba: story.append(img_ba)
    story.append(Spacer(1, 10))

    # [cite: 53-89] IV. Demarcations
    dem = data.get('Demarcation', {})
    story.append(Paragraph("IV. Demarcations", styleH2))
    
    dem_options = ["no demarcation", "gi sheet fence", "barbed wire", "steel pegs", "compound wall", "bio fence", "survey stone", "wooden pegs"]
    
    dem_rows = []
    for direction in ["North", "East", "South", "West"]:
        selected = dem.get(direction.lower(), [])
        row_str = f"<b>{direction}:</b> "
        items = [make_checkbox(opt.title(), opt in selected) for opt in dem_options]
        # Split into 2 lines for readability
        row_str += "  ".join(items[:4]) + "<br/>" + "  ".join(items[4:])
        dem_rows.append([Paragraph(row_str, styleNormal)])
        
    t_dem = Table(dem_rows, colWidths=[500])
    t_dem.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
    story.append(t_dem)
    
    story.append(Paragraph(f"<b>Notes:</b> {dem.get('demarcation_notes', '-')}", styleNormal))
    img_dem = get_image('Demarcation.demarcation_notes')
    if img_dem: story.append(img_dem)
    story.append(Spacer(1, 10))

    # [cite: 91-165] V. Access Nature
    acc = data.get('Access', {})
    story.append(Paragraph("V. Access Nature / Right of Access", styleH2))
    
    # We construct this section as a list of paragraphs to match layout
    story.append(Paragraph(f"<b>1. Type (Title Deed):</b> {', '.join(acc.get('typeofaccess_titledeed', []))}", styleNormal))
    story.append(Paragraph(f"<b>2. Type (Site Visit):</b> {', '.join(acc.get('typeofaccess_sitevisit', []))}", styleNormal))
    story.append(Paragraph(f"<b>3. Private Way Users:</b> {', '.join(acc.get('private_no_user', []))}", styleNormal))
    story.append(Paragraph(f"<b>4. Private Rd Demarcation:</b> {', '.join(acc.get('private_rd_demarcation', []))}", styleNormal))
    story.append(Paragraph(f"<b>5. Main Access Width:</b> {acc.get('main_access_width', '-')} m", styleNormal))
    story.append(Paragraph(f"<b>6. Vehicular Access:</b> {', '.join(acc.get('vehicular_access', []))}", styleNormal))
    story.append(Paragraph(f"<b>9. Material:</b> {', '.join(acc.get('road_material', []))}", styleNormal))
    
    story.append(Paragraph(f"<b>Notes:</b> {acc.get('access_notes', '-')}", styleNormal))
    img_acc = get_image('Access.access_notes')
    if img_acc: story.append(img_acc)
    story.append(PageBreak())

    # --- PAGE 3 ---
    # [cite: 166-168] VI. Purchase and Resale
    pr = data.get('Purchase_resale', {})
    story.append(Paragraph("VI. For Purchase and Resale Cases", styleH2))
    
    pr_data = [
        ["1. Buyer Name", pr.get('buyer_name', ''), "5. Duration up for sale", pr.get('property_sale_duration', '')],
        ["2. Seller Name", pr.get('seller_name', ''), "6. Land Extent", pr.get('purchase_land_extent', '')],
        ["3. Relation", pr.get('buyer_seller_relation', ''), "7. Price Asked", pr.get('price_asked', '')],
        ["4. Brokers/Trans.", pr.get('transaction_method', ''), "8. Deal Breaker", pr.get('deal_breaker_value', '')]
    ]
    t_pr = Table(pr_data, colWidths=[100, 150, 120, 150])
    t_pr.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.grey)]))
    story.append(t_pr)
    
    # [cite: 169] Notes
    story.append(Paragraph(f"<b>Notes:</b> {pr.get('purchase_resale_notes', '-')}", styleNormal))
    img_pr = get_image('Purchase_resale.purchase_resale_notes')
    if img_pr: story.append(img_pr)
    story.append(Spacer(1, 10))

    # [cite: 170-191] VII. Building Analysis
    bld = data.get('Building_analysis', {})
    story.append(Paragraph("VII. Building Analysis", styleH2))
    
    # Matrix Table
    b_headers = ["Floor", "Area", "Rooms", "Kitchen", "Bath", "Usage", "Occupancy"]
    b_rows = [[Paragraph(f"<b>{h}</b>", styleSmall) for h in b_headers]]
    
    floors = [("BF-2", "BF_2"), ("BF-1", "BF_1"), ("GF", "GF"), 
              ("1st Floor", "first_flr"), ("2nd Floor", "second_flr"), 
              ("3rd Floor", "third_flr"), ("4th Floor", "fourth_flr"), ("5th Floor", "fifth_flr")]
    
    for label, key in floors:
        area = bld.get(f"{key}_Builtup_area", "")
        if not area: continue
        row = [
            label, area,
            bld.get(f"{key}_Rooms_no", ""), bld.get(f"{key}_Kitchen_no", ""),
            bld.get(f"{key}_Bathrooms_no", ""), bld.get(f"{key}_Usage", ""),
            bld.get(f"{key}_Occupancy", "")
        ]
        b_rows.append(row)
        
    t_bld = Table(b_rows, colWidths=[60, 60, 40, 40, 40, 80, 80])
    t_bld.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.lightgrey), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
    story.append(t_bld)
    story.append(Spacer(1, 5))

    # Roof & Setbacks
    roofs = bld.get('roof_type', [])
    story.append(Paragraph(f"<b>Roof Type:</b> {', '.join(roofs)}   <b>%</b> {bld.get('RCC_Percentage', '')}", styleNormal))
    story.append(Paragraph(f"<b>Setback (m):</b> {bld.get('setback', '')}   <b>Construction Year:</b> {bld.get('construction_year', '')}", styleNormal))
    
    # Building Notes
    story.append(Paragraph(f"<b>Building Notes:</b> {bld.get('Building_analysis_notes', '-')}", styleNormal))
    img_bld = get_image('Building_analysis.Building_analysis_notes')
    if img_bld: story.append(img_bld)
    
    # Amenities
    story.append(Paragraph(f"<b>Amenities:</b> {bld.get('amenities_notes', '-')}", styleNormal))
    img_am = get_image('Building_analysis.amenities_notes')
    if img_am: story.append(img_am)
    story.append(PageBreak())

    # [cite: 192-193] IV. Landmark Sketch (Naming duplication in PDF source, handled as separate section)
    sk = data.get('Sketch', {})
    story.append(Paragraph("IV. Landmark and Layout (Handsketch)", styleH2))
    
    story.append(Paragraph(f"<b>Landmark Description:</b> {sk.get('landmark_description', '-')}", styleNormal))
    img_lm = get_image('Sketch.landmark_description')
    if img_lm: story.append(img_lm)
    story.append(Spacer(1, 10))
    
    story.append(Paragraph("<b>Main Site Layout:</b>", styleNormal))
    story.append(Spacer(1, 5))
    img_main = get_image('Sketch.main_layout', width=500, height=600)
    if img_main: story.append(img_main)

    # BUILD
    doc.build(story)
    return full_path