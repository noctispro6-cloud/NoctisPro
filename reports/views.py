from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.html import escape
from .models import Report, ReportTemplate
from worklist.models import Study
from accounts.models import User
import io
from django.core.files.base import ContentFile
from django.utils.text import slugify
from django.urls import reverse
from django.conf import settings
import io
import base64

# Optional PDF/Docx libs
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None
try:
    from docx import Document
except Exception:
    Document = None

# QR code support
try:
    import qrcode
except Exception:
    qrcode = None


def _qr_png_bytes(url: str, box_size: int = 6, border: int = 2) -> bytes:
    """Return PNG bytes for a QR code for the given URL."""
    if not qrcode:
        return b''
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white').convert('RGB')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _data_url_from_png(png_bytes: bytes) -> str:
    if not png_bytes:
        return ''
    return 'data:image/png;base64,' + base64.b64encode(png_bytes).decode('ascii')


@login_required
def report_list(request):
    # Restrict to admin and radiologist
    if not getattr(request.user, 'can_edit_reports', None) or not request.user.can_edit_reports():
        return HttpResponse(status=403)
    """List all reports"""
    # Get filter parameters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    modality_filter = request.GET.get('modality', '')
    
    # Base queryset
    reports = Report.objects.select_related('study', 'study__patient', 'study__modality', 'radiologist').all()
    
    # Apply filters
    if search_query:
        reports = reports.filter(
            Q(study__patient__first_name__icontains=search_query) |
            Q(study__patient__last_name__icontains=search_query) |
            Q(study__accession_number__icontains=search_query) |
            Q(radiologist__first_name__icontains=search_query) |
            Q(radiologist__last_name__icontains=search_query)
        )
    
    if status_filter:
        reports = reports.filter(status=status_filter)
    
    if modality_filter:
        reports = reports.filter(study__modality__code=modality_filter)
    
    # Order by most recent
    reports = reports.order_by('-report_date')
    
    # Calculate statistics
    total_reports = Report.objects.count()
    draft_reports = Report.objects.filter(status='draft').count()
    pending_reports = Report.objects.filter(status='preliminary').count()
    final_reports = Report.objects.filter(status='final').count()
    
    context = {
        'reports': reports,
        'total_reports': total_reports,
        'draft_reports': draft_reports,
        'pending_reports': pending_reports,
        'final_reports': final_reports,
        'search_query': search_query,
        'status_filter': status_filter,
        'modality_filter': modality_filter,
    }
    
    return render(request, 'reports/report_list.html', context)


@login_required
def write_report(request, study_id):
    # Restrict to admin and radiologist
    if not getattr(request.user, 'can_edit_reports', None) or not request.user.can_edit_reports():
        return HttpResponse(status=403)
    """Write report for study"""
    study = get_object_or_404(Study, id=study_id)
    
    # When opening editor, mark study as in progress for editors
    if study.status in ['scheduled', 'suspended']:
        study.status = 'in_progress'
        study.save(update_fields=['status'])
    
    # Try to get existing report or create new one
    try:
        report = Report.objects.get(study=study)
        is_new_report = False
    except Report.DoesNotExist:
        report = None
        is_new_report = True
    
    if request.method == 'POST':
        # Get form data
        clinical_history = request.POST.get('clinical_history', '')
        technique = request.POST.get('technique', '')
        comparison = request.POST.get('comparison', '')
        findings = request.POST.get('findings', '')
        impression = request.POST.get('impression', '')
        recommendations = request.POST.get('recommendations', '')
        status = request.POST.get('status', 'draft')
        action = request.POST.get('action', 'save')
        
        if is_new_report:
            # Create new report
            report = Report.objects.create(
                study=study,
                radiologist=request.user,
                clinical_history=clinical_history,
                technique=technique,
                comparison=comparison,
                findings=findings,
                impression=impression,
                recommendations=recommendations,
                status=status
            )
            messages.success(request, 'Report created successfully!')
        else:
            # Update existing report
            report.clinical_history = clinical_history
            report.technique = technique
            report.comparison = comparison
            report.findings = findings
            report.impression = impression
            report.recommendations = recommendations
            report.status = status
            report.last_modified = timezone.now()
            
            # If finalizing the report
            if status == 'final' or (action == 'submit' and status == 'final'):
                report.signed_date = timezone.now()
            
            report.save()
            messages.success(request, 'Report updated successfully!')
        
        # Update study status when report finalized
        if status == 'final' or (action == 'submit' and status == 'final'):
            study.status = 'completed'
            study.save(update_fields=['status'])
        
        # Redirect based on action
        if action == 'submit':
            messages.success(request, 'Report submitted successfully!')
            return redirect('reports:report_list')
        else:
            # Stay on the same page for continued editing
            return redirect('reports:write_report', study_id=study_id)
    
    context = {
        'study': study,
        'report': report,
        'is_new_report': is_new_report,
    }
    
    return render(request, 'reports/write_report.html', context)


@login_required
def print_report_stub(request, study_id):
    """Printable HTML that mirrors facility letterhead, includes author signature and QR/link footer."""
    study = get_object_or_404(Study, id=study_id)
    report = Report.objects.filter(study=study).first()

    # Build absolute URLs
    viewer_url = request.build_absolute_uri(reverse('dicom_viewer:web_viewer')) + f"?study_id={study.id}"
    report_url = request.build_absolute_uri(reverse('reports:print_report', args=[study.id]))

    # Generate QR codes
    qr_viewer_b64 = _data_url_from_png(_qr_png_bytes(viewer_url))
    qr_report_b64 = _data_url_from_png(_qr_png_bytes(report_url))

    # Embed letterhead directly to avoid relying on public /media/ URLs.
    # This keeps the printable report working even when MEDIA is not served publicly.
    letterhead_url = ''
    try:
        lh = getattr(study.facility, 'letterhead', None)
        if lh and getattr(lh, 'name', ''):
            import mimetypes
            ctype, _ = mimetypes.guess_type(lh.name)
            ctype = ctype or 'image/png'
            with lh.open('rb') as f:
                b = f.read()
            letterhead_url = f"data:{ctype};base64," + base64.b64encode(b).decode('ascii')
    except Exception:
        letterhead_url = ''
    facility_name = escape(getattr(study.facility, 'name', '') or '')
    facility_address = escape(getattr(study.facility, 'address', '') or '')
    patient_name = escape(getattr(study.patient, 'full_name', '') or '')
    patient_id = escape(getattr(study.patient, 'patient_id', '') or '')
    accession_number = escape(getattr(study, 'accession_number', '') or '')
    modality_code = escape(getattr(getattr(study, 'modality', None), 'code', '') or '')
    study_date_display = escape(str(getattr(study, 'study_date', '') or ''))

    clinical_text = escape(((report.clinical_history if report else (study.clinical_info or '')) or '-') or '-')
    technique_text = escape(((report.technique if report else '') or '-') or '-')
    comparison_text = escape(((report.comparison if report else '') or '-') or '-')
    findings_text = escape(((report.findings if report else '') or '-') or '-')
    impression_text = escape(((report.impression if report else '') or '-') or '-')
    recommendations_text = escape(((report.recommendations if report else '') or '-') or '-')
    report_status = escape(getattr(report, 'status', '') or '')

    author_name = ''
    author_license = ''
    signed_date = ''
    if report and getattr(report, 'radiologist', None):
        try:
            author_name = report.radiologist.get_full_name() or report.radiologist.username
            author_license = getattr(report.radiologist, 'license_number', '') or ''
        except Exception:
            pass
    if report and report.signed_date:
        signed_date = report.signed_date.strftime('%Y-%m-%d %H:%M')

    # Optional signature image from Base64 (data URL or raw b64)
    sig_img_html = ''
    if report and (report.digital_signature or '').strip():
        ds = report.digital_signature.strip()
        if not ds.startswith('data:image'):
            try:
                ds = 'data:image/png;base64,' + ds
            except Exception:
                ds = ''
        if ds:
            sig_img_html = f'<img src="{ds}" alt="Signature" style="height:60px;" />'

    html = f"""
    <html>
      <head>
        <title>Report {study.accession_number}</title>
        <style>
          body {{ font-family: Arial, sans-serif; color: #000; margin: 24px; }}
          .letterhead {{ text-align:center; margin-bottom: 12px; }}
          .letterhead img {{ max-width: 100%; height: auto; }}
          .header {{ border-bottom:1px solid #000; padding-bottom:6px; margin-bottom:10px; }}
          .section {{ margin-bottom: 12px; }}
          .label {{ font-weight:bold; }}
          pre {{ white-space: pre-wrap; font-family: inherit; }}
          .footer {{ border-top:1px solid #000; padding-top:8px; margin-top:12px; display:flex; justify-content: space-between; align-items:center; gap: 16px; }}
          .qr {{ text-align:center; font-size: 11px; }}
          .sign {{ margin-top: 8px; }}
          @media print {{ .noprint {{ display:none; }} }}
        </style>
      </head>
      <body>
        <div class="letterhead">{f'<img src="{letterhead_url}" alt="Letterhead" />' if letterhead_url else f'<h2 style="margin:0">{facility_name}</h2><div>{facility_address}</div>'}</div>
        <div class="header">
          <div style="display:flex; justify-content: space-between;">
            <div>
              <div class="label">Patient:</div>
              <div>{patient_name} ({patient_id})</div>
            </div>
            <div style="text-align:right">
              <div><span class="label">Accession:</span> {accession_number}</div>
              <div><span class="label">Modality:</span> {modality_code} &nbsp; <span class="label">Date:</span> {study_date_display}</div>
              {f'<div><span class="label">Status:</span> {report_status}</div>' if report_status else ''}
            </div>
          </div>
        </div>
        <div class="section"><span class="label">Clinical Information:</span><br/><pre>{clinical_text}</pre></div>
        <div class="section"><span class="label">Technique:</span><br/><pre>{technique_text}</pre></div>
        <div class="section"><span class="label">Comparison:</span><br/><pre>{comparison_text}</pre></div>
        <div class="section"><span class="label">Findings:</span><br/><pre>{findings_text}</pre></div>
        <div class="section"><span class="label">Impression:</span><br/><pre>{impression_text}</pre></div>
        <div class="section"><span class="label">Recommendations:</span><br/><pre>{recommendations_text}</pre></div>
        <div class="sign">
          <div class="label">Signed by:</div>
          <div>{author_name}{(' - ' + author_license) if author_license else ''}{(' on ' + signed_date) if signed_date else ''}</div>
          {sig_img_html}
        </div>
        <div class="footer">
          <div class="qr">
            {f'<img src="{qr_viewer_b64}" alt="QR Images" style="height:100px;" />' if qr_viewer_b64 else ''}
            <div>Scan to view images</div>
            <div style="word-break: break-all; max-width: 260px;">{viewer_url}</div>
          </div>
          <div class="qr">
            {f'<img src="{qr_report_b64}" alt="QR Report" style="height:100px;" />' if qr_report_b64 else ''}
            <div>Scan to view report</div>
            <div style="word-break: break-all; max-width: 260px;">{report_url}</div>
          </div>
        </div>
        <div class="noprint" style="margin-top: 12px;"><button onclick="window.print()">Print</button></div>
      </body>
    </html>
    """
    return HttpResponse(html)


@login_required
def export_report_pdf(request, study_id):
    # Restrict to admin and radiologist
    if not getattr(request.user, 'can_edit_reports', None) or not request.user.can_edit_reports():
        return HttpResponse(status=403)
    study = get_object_or_404(Study, id=study_id)
    report = Report.objects.filter(study=study).first()

    # Prepare absolute URLs
    viewer_url = request.build_absolute_uri(reverse('dicom_viewer:web_viewer')) + f"?study_id={study.id}"
    report_url = request.build_absolute_uri(reverse('reports:print_report', args=[study.id]))

    filename = f"report_{slugify(study.accession_number)}.pdf"
    if fitz is None:
        return JsonResponse({'error': 'PDF export not available (PyMuPDF missing).'}, status=500)
    try:
        doc = fitz.open()
        page = doc.new_page()
        margin = 36
        y = margin

        # Insert facility letterhead image if available
        try:
            if getattr(study.facility, 'letterhead', None) and study.facility.letterhead.name:
                with open(study.facility.letterhead.path, 'rb') as f:
                    img_bytes = f.read()
                rect = fitz.Rect(margin, y, page.rect.width - margin, y + 90)
                page.insert_image(rect, stream=img_bytes, keep_proportion=True)
                y = rect.y1 + 12
            else:
                page.insert_text((margin, y), study.facility.name, fontsize=14, fontname="helv", fill=(0, 0, 0))
                y += 22
                page.insert_text((margin, y), study.facility.address or '', fontsize=10, fontname="helv", fill=(0, 0, 0))
                y += 18
        except Exception:
            # Fallback to text header if image fails
            page.insert_text((margin, y), study.facility.name, fontsize=14, fontname="helv", fill=(0, 0, 0))
            y += 22

        # Horizontal rule
        page.draw_line((margin, y), (page.rect.width - margin, y), color=(0, 0, 0), width=0.6)
        y += 10

        # Patient and study header
        header_lines = [
            f"Radiology Report",
            f"Patient: {study.patient.full_name} ({study.patient.patient_id})",
            f"Accession: {study.accession_number}    Modality: {study.modality.code}    Date: {study.study_date}",
            f"Priority: {study.priority.upper()}",
        ]
        for line in header_lines:
            page.insert_text((margin, y), line, fontsize=12 if line == 'Radiology Report' else 10, fontname="helv", fill=(0, 0, 0))
            y += 16 if line != 'Radiology Report' else 20

        y += 4
        # Sections
        def add_section(title: str, content: str):
            nonlocal y, page
            if y > page.rect.height - 180:
                page = doc.new_page(); y = margin
            page.insert_text((margin, y), title, fontsize=11, fontname="helv", fill=(0, 0, 0))
            y += 14
            # simple wrap
            max_width = page.rect.width - margin * 2
            words = (content or '-').split()
            line = ''
            while words:
                nxt = words.pop(0)
                test = (line + ' ' + nxt).strip()
                # crude width estimation (6px per char at 10pt)
                if len(test) * 6 > max_width:
                    page.insert_text((margin, y), line, fontsize=10, fontname="helv", fill=(0, 0, 0))
                    y += 13
                    line = nxt
                else:
                    line = test
            if line:
                page.insert_text((margin, y), line, fontsize=10, fontname="helv", fill=(0, 0, 0))
                y += 16
            y += 2

        add_section('Clinical History', (report.clinical_history if report else (study.clinical_info or '')) or '-')
        add_section('Technique', (report.technique if report else '') or '-')
        add_section('Comparison', (report.comparison if report else '') or '-')
        add_section('Findings', (report.findings if report else '') or '-')
        add_section('Impression', (report.impression if report else '') or '-')
        add_section('Recommendations', (report.recommendations if report else '') or '-')

        # Signature block
        author_name = ''
        author_license = ''
        if report and getattr(report, 'radiologist', None):
            try:
                author_name = report.radiologist.get_full_name() or report.radiologist.username
                author_license = getattr(report.radiologist, 'license_number', '') or ''
            except Exception:
                pass
        sig_line = f"Signed by: {author_name}{(' - ' + author_license) if author_license else ''}"
        if report and report.signed_date:
            sig_line += f" on {report.signed_date.strftime('%Y-%m-%d %H:%M')}"
        if y > page.rect.height - 150:
            page = doc.new_page(); y = margin
        page.insert_text((margin, y), sig_line, fontsize=10, fontname="helv", fill=(0, 0, 0))
        y += 14
        # Optional signature image
        if report and (report.digital_signature or '').strip():
            ds = report.digital_signature.strip()
            try:
                if ds.startswith('data:image'):
                    b64 = ds.split(',', 1)[1]
                else:
                    b64 = ds
                img_bytes = base64.b64decode(b64)
                rect = fitz.Rect(margin, y, margin + 180, y + 60)
                page.insert_image(rect, stream=img_bytes, keep_proportion=True)
                y = rect.y1 + 8
            except Exception:
                pass

        # Footer with QR codes
        if y < page.rect.height - 130:
            footer_y = page.rect.height - 130
        else:
            footer_y = y + 10
        # line
        page.draw_line((margin, footer_y), (page.rect.width - margin, footer_y), color=(0, 0, 0), width=0.6)
        footer_y += 8

        try:
            qr1 = _qr_png_bytes(viewer_url)
            qr2 = _qr_png_bytes(report_url)
            left_rect = fitz.Rect(margin, footer_y, margin + 110, footer_y + 110)
            right_rect = fitz.Rect(page.rect.width - margin - 110, footer_y, page.rect.width - margin, footer_y + 110)
            if qr1:
                page.insert_image(left_rect, stream=qr1, keep_proportion=True)
                page.insert_text((left_rect.x0, left_rect.y1 + 2), 'Scan to view images', fontsize=8, fontname='helv', fill=(0,0,0))
            if qr2:
                page.insert_image(right_rect, stream=qr2, keep_proportion=True)
                page.insert_text((right_rect.x0, right_rect.y1 + 2), 'Scan to view report', fontsize=8, fontname='helv', fill=(0,0,0))
        except Exception:
            pass

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        resp = HttpResponse(buf.getvalue(), content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="{filename}"'
        return resp
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def export_report_docx(request, study_id):
    # Restrict to admin and radiologist
    if not getattr(request.user, 'can_edit_reports', None) or not request.user.can_edit_reports():
        return HttpResponse(status=403)
    if Document is None:
        return JsonResponse({'error': 'DOCX export not available (python-docx missing).'}, status=500)
    study = get_object_or_404(Study, id=study_id)
    report = Report.objects.filter(study=study).first()
    doc = Document()
    # Letterhead as image if available
    try:
        if getattr(study.facility, 'letterhead', None) and study.facility.letterhead.name:
            doc.add_picture(study.facility.letterhead.path, width=None)
    except Exception:
        doc.add_heading(study.facility.name, 0)
    doc.add_paragraph(f"Patient: {study.patient.full_name} ({study.patient.patient_id})")
    doc.add_paragraph(f"Accession: {study.accession_number}    Modality: {study.modality.code}    Date: {study.study_date}")
    doc.add_paragraph(f"Priority: {study.priority.upper()}")
    doc.add_paragraph('')
    sections = [
        ('Clinical History', (report.clinical_history if report else (study.clinical_info or '')) or '-'),
        ('Technique', (report.technique if report else '') or '-'),
        ('Comparison', (report.comparison if report else '') or '-'),
        ('Findings', (report.findings if report else '') or '-'),
        ('Impression', (report.impression if report else '') or '-'),
        ('Recommendations', (report.recommendations if report else '') or '-'),
    ]
    for title, content in sections:
        doc.add_heading(title, level=2)
        doc.add_paragraph(content)
    # Signature
    author_name = ''
    author_license = ''
    if report and getattr(report, 'radiologist', None):
        try:
            author_name = report.radiologist.get_full_name() or report.radiologist.username
            author_license = getattr(report.radiologist, 'license_number', '') or ''
        except Exception:
            pass
    doc.add_paragraph(f"Signed by: {author_name}{(' - ' + author_license) if author_license else ''}")
    if report and report.signed_date:
        doc.add_paragraph(f"Signed on: {report.signed_date.strftime('%Y-%m-%d %H:%M')}")
    buf = io.BytesIO()
    doc.save(buf); buf.seek(0)
    resp = HttpResponse(buf.getvalue(), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    resp['Content-Disposition'] = f'attachment; filename="report_{slugify(study.accession_number)}.docx"'
    return resp
