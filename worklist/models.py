from django.db import models
from django.utils import timezone
from accounts.models import User, Facility
import os

class Patient(models.Model):
    """Patient information model"""
    patient_id = models.CharField(max_length=50, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=1, choices=[('M', 'Male'), ('F', 'Female'), ('O', 'Other')])
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    emergency_contact = models.CharField(max_length=200, blank=True)
    medical_record_number = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.patient_id})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

class Modality(models.Model):
    """Imaging modality types"""
    code = models.CharField(max_length=10, unique=True)  # CT, MR, XR, etc.
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Modalities"

    def __str__(self):
        return f"{self.code} - {self.name}"

class Study(models.Model):
    """Medical study/examination model"""
    STUDY_STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('suspended', 'Suspended'),
        ('cancelled', 'Cancelled'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    study_instance_uid = models.CharField(max_length=100, unique=True)
    accession_number = models.CharField(max_length=50, db_index=True)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE)
    modality = models.ForeignKey(Modality, on_delete=models.CASCADE)
    study_description = models.CharField(max_length=200)
    study_date = models.DateTimeField()
    referring_physician = models.CharField(max_length=100)
    radiologist = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                                   related_name='assigned_studies')
    status = models.CharField(max_length=20, choices=STUDY_STATUS_CHOICES, default='scheduled')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    body_part = models.CharField(max_length=100, blank=True)
    clinical_info = models.TextField(blank=True)
    study_comments = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                   related_name='uploaded_studies')
    upload_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-study_date']

    def __str__(self):
        return f"{self.accession_number} - {self.patient.full_name} ({self.modality.code})"

    def get_series_count(self):
        # Efficient and accurate count
        return Series.objects.filter(study=self).count()

    def get_image_count(self, force_refresh=False):
        # Avoid N+1 queries and ensure correctness
        if force_refresh:
            # Force a fresh query by clearing any potential caches
            from django.db import connection
            connection.queries_log.clear()
        return DicomImage.objects.filter(series__study=self).count()

class Series(models.Model):
    """DICOM Series model"""
    series_instance_uid = models.CharField(max_length=100, unique=True)
    study = models.ForeignKey(Study, on_delete=models.CASCADE)
    series_number = models.IntegerField()
    series_description = models.CharField(max_length=200, blank=True)
    modality = models.CharField(max_length=10)
    body_part = models.CharField(max_length=100, blank=True)
    slice_thickness = models.FloatField(null=True, blank=True)
    pixel_spacing = models.CharField(max_length=50, blank=True)
    image_orientation = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Series"
        ordering = ['series_number']

    def __str__(self):
        return f"Series {self.series_number} - {self.series_description}"

class DicomImage(models.Model):
    """Individual DICOM image model"""
    sop_instance_uid = models.CharField(max_length=100, unique=True)
    series = models.ForeignKey(Series, on_delete=models.CASCADE, related_name='images')
    instance_number = models.IntegerField()
    image_position = models.CharField(max_length=100, blank=True)
    slice_location = models.FloatField(null=True, blank=True)
    file_path = models.FileField(upload_to='dicom/images/')
    file_size = models.BigIntegerField()
    thumbnail = models.ImageField(upload_to='dicom/thumbnails/', null=True, blank=True)
    processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['instance_number']

    def __str__(self):
        return f"Image {self.instance_number} - {self.sop_instance_uid}"

    def get_file_name(self):
        return os.path.basename(self.file_path.name) if self.file_path else ''

class StudyAttachment(models.Model):
    """Additional files attached to studies (reports, etc.)"""
    ATTACHMENT_TYPES = [
        ('report', 'Report'),
        ('previous_study', 'Previous Study'),
        ('dicom_study', 'DICOM Study'),
        ('word_document', 'Word Document'),
        ('pdf_document', 'PDF Document'),
        ('image', 'Image'),
        ('document', 'Document'),
        ('other', 'Other'),
    ]

    study = models.ForeignKey(Study, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='study_attachments/')
    file_type = models.CharField(max_length=20, choices=ATTACHMENT_TYPES)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Enhanced metadata
    file_size = models.BigIntegerField(default=0)
    mime_type = models.CharField(max_length=100, blank=True)
    thumbnail = models.ImageField(upload_to='attachment_thumbnails/', null=True, blank=True)
    
    # For DICOM study attachments
    attached_study = models.ForeignKey('Study', on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='referenced_by_attachments')
    study_date = models.DateTimeField(null=True, blank=True)
    modality = models.CharField(max_length=10, blank=True)
    
    # Metadata for documents
    page_count = models.IntegerField(null=True, blank=True)
    author = models.CharField(max_length=200, blank=True)
    creation_date = models.DateTimeField(null=True, blank=True)
    
    # Access and permissions
    is_public = models.BooleanField(default=True)
    allowed_roles = models.JSONField(default=list, blank=True)  # ['admin', 'radiologist', 'facility']
    
    # Version control
    version = models.CharField(max_length=20, default='1.0')
    replaced_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    is_current_version = models.BooleanField(default=True)
    
    # Audit fields
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    upload_date = models.DateTimeField(auto_now_add=True)
    last_accessed = models.DateTimeField(null=True, blank=True)
    access_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-upload_date']

    def __str__(self):
        return f"{self.name} - {self.study.accession_number}"

    def get_file_extension(self):
        return os.path.splitext(self.file.name)[1].lower()
    
    def is_viewable_in_browser(self):
        """Check if file can be viewed directly in browser"""
        viewable_types = ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.txt']
        return self.get_file_extension() in viewable_types
    
    def is_dicom_file(self):
        """Check if attachment is a DICOM file"""
        return self.file_type == 'dicom_study' or self.get_file_extension() == '.dcm'
    
    def increment_access_count(self):
        """Increment access count and update last accessed time"""
        self.access_count += 1
        self.last_accessed = timezone.now()
        self.save(update_fields=['access_count', 'last_accessed'])

class AttachmentComment(models.Model):
    """Comments on study attachments"""
    attachment = models.ForeignKey(StudyAttachment, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Comment on {self.attachment.name} by {self.user.username}"

class AttachmentVersion(models.Model):
    """Track versions of attachments"""
    attachment = models.ForeignKey(StudyAttachment, on_delete=models.CASCADE, related_name='versions')
    version_number = models.CharField(max_length=20)
    file = models.FileField(upload_to='attachment_versions/')
    change_description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['attachment', 'version_number']
    
    def __str__(self):
        return f"{self.attachment.name} v{self.version_number}"

class StudyNote(models.Model):
    """Notes and comments on studies"""
    study = models.ForeignKey(Study, on_delete=models.CASCADE, related_name='notes')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    note = models.TextField()
    is_private = models.BooleanField(default=False)  # Private to facility/radiologist
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Note by {self.user.username} on {self.study.accession_number}"
