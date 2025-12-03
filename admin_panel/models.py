from django.db import models
from django.utils import timezone
from accounts.models import User, Facility
from worklist.models import Study, Modality
from decimal import Decimal
import uuid

class InvoicingRule(models.Model):
    """Rules for calculating invoices based on modality and study count"""
    modality = models.ForeignKey(Modality, on_delete=models.CASCADE)
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, null=True, blank=True)  # Null for global rules
    price_per_study = models.DecimalField(max_digits=10, decimal_places=2)
    minimum_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    bulk_discount_threshold = models.IntegerField(default=0)  # Studies count for bulk discount
    bulk_discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['modality', 'facility', 'effective_from']

    def __str__(self):
        facility_name = self.facility.name if self.facility else "Global"
        return f"{self.modality.code} - {facility_name} - ${self.price_per_study}"

class Invoice(models.Model):
    """Invoice model for billing facilities"""
    INVOICE_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    ]

    invoice_number = models.CharField(max_length=50, unique=True)
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name='invoices')
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    
    # Invoice amounts
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Invoice details
    status = models.CharField(max_length=20, choices=INVOICE_STATUS_CHOICES, default='draft')
    issue_date = models.DateField(auto_now_add=True)
    due_date = models.DateField()
    payment_terms = models.CharField(max_length=100, default="Net 30")
    
    # Notes and references
    notes = models.TextField(blank=True)
    reference_number = models.CharField(max_length=100, blank=True)
    
    # Payment tracking
    paid_date = models.DateField(null=True, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)
    
    # Audit trail
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_invoices')
    sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_invoices')
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.facility.name}"

    def calculate_total(self):
        """Calculate total amount based on line items"""
        self.subtotal = sum(item.total_amount for item in self.line_items.all())
        self.tax_amount = self.subtotal * (self.tax_rate / 100)
        self.total_amount = self.subtotal + self.tax_amount - self.discount_amount
        self.save()

    def mark_as_paid(self, payment_date=None, payment_ref=''):
        """Mark invoice as paid"""
        self.status = 'paid'
        self.paid_date = payment_date or timezone.now().date()
        self.payment_reference = payment_ref
        self.save()

class InvoiceLineItem(models.Model):
    """Individual line items in an invoice"""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='line_items')
    modality = models.ForeignKey(Modality, on_delete=models.CASCADE)
    description = models.CharField(max_length=200)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Reference to studies included
    studies = models.ManyToManyField(Study, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.description} - {self.quantity} x ${self.unit_price}"

    def save(self, *args, **kwargs):
        self.total_amount = self.quantity * self.unit_price
        super().save(*args, **kwargs)

class SystemConfiguration(models.Model):
    """System-wide configuration settings"""
    CONFIG_TYPES = [
        ('string', 'String'),
        ('integer', 'Integer'),
        ('float', 'Float'),
        ('boolean', 'Boolean'),
        ('json', 'JSON'),
    ]

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    data_type = models.CharField(max_length=20, choices=CONFIG_TYPES, default='string')
    description = models.TextField(blank=True)
    category = models.CharField(max_length=50, default='general')
    is_sensitive = models.BooleanField(default=False)  # For passwords, API keys, etc.
    
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.key} = {self.value[:50]}..."

    def get_value(self):
        """Get typed value based on data_type"""
        if self.data_type == 'integer':
            return int(self.value)
        elif self.data_type == 'float':
            return float(self.value)
        elif self.data_type == 'boolean':
            return self.value.lower() in ('true', '1', 'yes', 'on')
        elif self.data_type == 'json':
            import json
            return json.loads(self.value)
        return self.value

class AuditLog(models.Model):
    """Audit log for tracking important system actions"""
    ACTION_TYPES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('view', 'View'),
        ('download', 'Download'),
        ('upload', 'Upload'),
        ('export', 'Export'),
        ('import', 'Import'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=20, choices=ACTION_TYPES)
    model_name = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    object_repr = models.CharField(max_length=200, blank=True)
    
    # Additional details
    description = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Context data
    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)
    
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        user_name = self.user.username if self.user else 'Anonymous'
        return f"{user_name} {self.action} {self.model_name} at {self.timestamp}"

class SystemUsageStatistics(models.Model):
    """Track system usage statistics"""
    date = models.DateField()
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, null=True, blank=True)
    
    # Study statistics
    studies_uploaded = models.IntegerField(default=0)
    studies_reported = models.IntegerField(default=0)
    studies_by_modality = models.JSONField(default=dict)  # {modality: count}
    
    # User activity
    active_users = models.IntegerField(default=0)
    new_users = models.IntegerField(default=0)
    total_logins = models.IntegerField(default=0)
    
    # Storage statistics
    storage_used_gb = models.FloatField(default=0)
    files_uploaded = models.IntegerField(default=0)
    
    # Performance metrics
    avg_upload_time = models.FloatField(default=0)  # in seconds
    avg_report_time = models.FloatField(default=0)  # in hours
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['date', 'facility']
        ordering = ['-date']

    def __str__(self):
        facility_name = self.facility.name if self.facility else "System-wide"
        return f"Stats for {facility_name} on {self.date}"

class MaintenanceWindow(models.Model):
    """Scheduled maintenance windows"""
    title = models.CharField(max_length=200)
    description = models.TextField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    
    # Affected services
    affects_uploads = models.BooleanField(default=False)
    affects_viewer = models.BooleanField(default=False)
    affects_reports = models.BooleanField(default=False)
    affects_chat = models.BooleanField(default=False)
    
    # Notifications
    notify_users = models.BooleanField(default=True)
    notification_sent = models.BooleanField(default=False)
    
    # Status
    is_completed = models.BooleanField(default=False)
    actual_end_time = models.DateTimeField(null=True, blank=True)
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return f"{self.title} - {self.start_time}"

class LicenseInfo(models.Model):
    """Software license information"""
    component_name = models.CharField(max_length=100)
    license_type = models.CharField(max_length=50)
    license_key = models.TextField(blank=True)
    max_users = models.IntegerField(null=True, blank=True)
    max_facilities = models.IntegerField(null=True, blank=True)
    max_storage_gb = models.IntegerField(null=True, blank=True)
    
    issue_date = models.DateField()
    expiry_date = models.DateField(null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.component_name} - {self.license_type}"

    def is_expired(self):
        """Check if license is expired"""
        if self.expiry_date:
            return timezone.now().date() > self.expiry_date
        return False
