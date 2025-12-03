from django.db import models
from django.utils import timezone
from accounts.models import User, Facility
from worklist.models import Study
import os

class ReportTemplate(models.Model):
    """Report templates for different study types"""
    name = models.CharField(max_length=200)
    modality = models.CharField(max_length=10)  # CT, MR, XR, etc.
    body_part = models.CharField(max_length=100)
    template_html = models.TextField()
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.modality}"

class Report(models.Model):
    """Medical report model"""
    REPORT_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('preliminary', 'Preliminary'),
        ('final', 'Final'),
        ('amended', 'Amended'),
        ('cancelled', 'Cancelled'),
    ]

    study = models.OneToOneField(Study, on_delete=models.CASCADE, related_name='report')
    template = models.ForeignKey(ReportTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    radiologist = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reports')
    
    # Report content
    findings = models.TextField(blank=True)
    impression = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    clinical_history = models.TextField(blank=True)
    technique = models.TextField(blank=True)
    comparison = models.TextField(blank=True)
    
    # Report metadata
    status = models.CharField(max_length=20, choices=REPORT_STATUS_CHOICES, default='draft')
    report_date = models.DateTimeField(auto_now_add=True)
    signed_date = models.DateTimeField(null=True, blank=True)
    last_modified = models.DateTimeField(auto_now=True)
    
    # Digital signature
    digital_signature = models.TextField(blank=True)  # Base64 encoded signature
    signature_timestamp = models.DateTimeField(null=True, blank=True)
    
    # AI assistance
    ai_generated = models.BooleanField(default=False)
    ai_confidence = models.FloatField(null=True, blank=True)
    ai_findings = models.TextField(blank=True)
    
    # Version control
    version = models.IntegerField(default=1)
    previous_version = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-report_date']

    def __str__(self):
        return f"Report for {self.study.accession_number} - {self.status}"

    def sign_report(self, signature_data=None):
        """Sign the report and mark as final"""
        self.status = 'final'
        self.signed_date = timezone.now()
        if signature_data:
            self.digital_signature = signature_data
            self.signature_timestamp = timezone.now()
        self.save()

    def create_amendment(self, new_findings=None, new_impression=None):
        """Create an amended version of the report"""
        if self.status != 'final':
            raise ValueError("Only final reports can be amended")
        
        amended_report = Report.objects.create(
            study=self.study,
            template=self.template,
            radiologist=self.radiologist,
            findings=new_findings or self.findings,
            impression=new_impression or self.impression,
            recommendations=self.recommendations,
            clinical_history=self.clinical_history,
            technique=self.technique,
            comparison=self.comparison,
            status='amended',
            version=self.version + 1,
            previous_version=self
        )
        return amended_report

class ReportSection(models.Model):
    """Individual sections of a report for structured reporting"""
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='sections')
    section_name = models.CharField(max_length=100)
    content = models.TextField()
    order = models.IntegerField(default=0)
    is_required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.section_name} - {self.report.study.accession_number}"

class ReportAttachment(models.Model):
    """Files attached to reports"""
    ATTACHMENT_TYPES = [
        ('image', 'Image'),
        ('measurement', 'Measurement'),
        ('annotation', 'Annotation'),
        ('reference', 'Reference'),
        ('other', 'Other'),
    ]

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='report_attachments/')
    attachment_type = models.CharField(max_length=20, choices=ATTACHMENT_TYPES)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.report.study.accession_number}"

class ReportComment(models.Model):
    """Comments and discussions on reports"""
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.TextField()
    is_internal = models.BooleanField(default=True)  # Internal to radiologists only
    parent_comment = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Comment by {self.user.username} on {self.report.study.accession_number}"

class ReportAccess(models.Model):
    """Track who has accessed reports for audit purposes"""
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='access_logs')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    access_type = models.CharField(max_length=20, choices=[
        ('view', 'Viewed'),
        ('edit', 'Edited'),
        ('print', 'Printed'),
        ('download', 'Downloaded'),
        ('share', 'Shared'),
    ])
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    accessed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} {self.access_type} {self.report.study.accession_number}"

class MacroText(models.Model):
    """Pre-defined text snippets for report writing"""
    name = models.CharField(max_length=100)
    text = models.TextField()
    category = models.CharField(max_length=50)
    modality = models.CharField(max_length=10, blank=True)
    is_global = models.BooleanField(default=False)  # Available to all users
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
