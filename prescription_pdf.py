"""
prescription_pdf.py — Generates clean, professional PDF e-prescriptions using ReportLab.
"""
import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

def create_prescription_pdf(prescription, doctor_info=None, patient_info=None):
    """
    Generates a PDF BytesIO stream for the given prescription document.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'ClinicTitle',
        parent=styles['Heading1'],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1e3a8a'),
        fontName='Helvetica-Bold'
    )
    subtitle_style = ParagraphStyle(
        'ClinicSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#475569')
    )
    header_right_style = ParagraphStyle(
        'HeaderRight',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        alignment=TA_RIGHT,
        textColor=colors.HexColor('#1e293b')
    )
    section_title = ParagraphStyle(
        'SectionTitle',
        parent=styles['Heading2'],
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#1e3a8a'),
        fontName='Helvetica-Bold',
        spaceAfter=6
    )
    cell_style = ParagraphStyle(
        'GridCell',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#1e293b')
    )
    cell_header = ParagraphStyle(
        'GridHeader',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        fontName='Helvetica-Bold',
        textColor=colors.white
    )
    disclaimer_style = ParagraphStyle(
        'Disclaimer',
        parent=styles['Normal'],
        fontSize=8,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#64748b')
    )

    story = []

    # 1. Header / Letterhead
    doc_name = prescription.get('doctor_name') or (doctor_info.get('name') if doctor_info else 'Dr. Medical Specialist')
    doc_spec = doctor_info.get('specialization', 'General Physician') if doctor_info else 'General Physician'
    doc_reg  = prescription.get('doctor_reg_no') or (doctor_info.get('registration_number') if doctor_info else 'REG-MED-100234')

    left_header = [
        Paragraph("MEDIGUIDE HEALTHCARE CLINIC", title_style),
        Paragraph("123 Health Avenue, Medical District | Phone: +1 800-MEDIGUIDE", subtitle_style)
    ]
    
    right_header = [
        Paragraph(f"<b>{doc_name}</b>", header_right_style),
        Paragraph(f"{doc_spec}", header_right_style),
        Paragraph(f"Reg No: {doc_reg}", header_right_style)
    ]

    header_table = Table([[left_header, right_header]], colWidths=[320, 220])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1e3a8a'), spaceAfter=15))

    # 2. Patient & Prescription Metadata Banner
    created_at = prescription.get('created_at')
    date_str = created_at.strftime('%Y-%m-%d %H:%M') if isinstance(created_at, datetime) else str(created_at or datetime.utcnow().strftime('%Y-%m-%d'))
    pat_name = prescription.get('patient_name') or (patient_info.get('name') if patient_info else 'Patient')
    pat_age = prescription.get('patient_age') or (patient_info.get('age') if patient_info else 'N/A')
    pat_gender = prescription.get('patient_gender') or 'N/A'
    presc_status = (prescription.get('status') or 'finalized').upper()

    meta_data = [
        [
            Paragraph(f"<b>Patient Name:</b> {pat_name}", cell_style),
            Paragraph(f"<b>Age/Gender:</b> {pat_age} yrs / {pat_gender}", cell_style),
            Paragraph(f"<b>Date:</b> {date_str}", cell_style)
        ],
        [
            Paragraph(f"<b>Prescription ID:</b> {prescription.get('_id', prescription.get('id', 'N/A'))}", cell_style),
            Paragraph(f"<b>Appointment ID:</b> {prescription.get('appointment_id', 'N/A')}", cell_style),
            Paragraph(f"<b>Status:</b> {presc_status}", cell_style)
        ]
    ]
    meta_table = Table(meta_data, colWidths=[200, 170, 170])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f1f5f9')),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 15))

    # 3. Rx Symbol & Drug Table Header
    rx_style = ParagraphStyle('RxStyle', parent=styles['Heading1'], fontSize=22, leading=26, textColor=colors.HexColor('#1e3a8a'))
    story.append(Paragraph("Rx (Prescription)", rx_style))
    story.append(Spacer(1, 8))

    # Drug Table
    table_data = [[
        Paragraph("#", cell_header),
        Paragraph("Medicine Name", cell_header),
        Paragraph("Dosage", cell_header),
        Paragraph("Frequency", cell_header),
        Paragraph("Duration", cell_header),
        Paragraph("Instructions", cell_header)
    ]]

    items = prescription.get('items', [])
    if items:
        for idx, item in enumerate(items, 1):
            table_data.append([
                Paragraph(str(idx), cell_style),
                Paragraph(f"<b>{item.get('drug_name', '')}</b>", cell_style),
                Paragraph(item.get('dosage', ''), cell_style),
                Paragraph(item.get('frequency', ''), cell_style),
                Paragraph(item.get('duration', ''), cell_style),
                Paragraph(item.get('instructions', '-'), cell_style)
            ])
    else:
        table_data.append([
            Paragraph("1", cell_style),
            Paragraph("No items prescribed", cell_style),
            Paragraph("-", cell_style),
            Paragraph("-", cell_style),
            Paragraph("-", cell_style),
            Paragraph("-", cell_style)
        ])

    drug_table = Table(table_data, colWidths=[25, 145, 80, 100, 75, 115])
    drug_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')])
    ]))
    story.append(drug_table)
    story.append(Spacer(1, 15))

    # 4. Doctor Notes
    notes = prescription.get('notes')
    if notes:
        story.append(Paragraph("Doctor's Advice & Instructions:", section_title))
        notes_p = Paragraph(notes.replace('\n', '<br/>'), cell_style)
        notes_table = Table([[notes_p]], colWidths=[540])
        notes_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0')),
            ('PADDING', (0, 0), (-1, -1), 10)
        ]))
        story.append(notes_table)
        story.append(Spacer(1, 20))

    # 5. Footer & Disclaimer
    story.append(Spacer(1, 30))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#cbd5e1'), spaceAfter=10))

    footer_content = [
        Paragraph("<b>*** Digitally Generated Prescription ***</b>", disclaimer_style),
        Paragraph(f"Issued by {doc_name} on MediGuide E-Healthcare System | Valid without physical signature", disclaimer_style),
        Paragraph("Please consult your physician before altering dosage or stopping medications.", disclaimer_style)
    ]
    story.append(KeepTogether(footer_content))

    doc.build(story)
    buffer.seek(0)
    return buffer
