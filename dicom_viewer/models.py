from django.conf import settings
from django.db import models

# Use existing Study/Series/DicomImage from worklist app
from worklist.models import Study, Series, DicomImage
import json


class ViewerSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    study = models.ForeignKey(Study, on_delete=models.CASCADE)
    session_data = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def set_session_data(self, data):
        self.session_data = json.dumps(data)

    def get_session_data(self):
        return json.loads(self.session_data) if self.session_data else {}


class Measurement(models.Model):
    MEASUREMENT_TYPES = [
        ("length", "Length"),
        ("area", "Area"),
        ("angle", "Angle"),
        ("cobb_angle", "Cobb Angle"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    image = models.ForeignKey(DicomImage, on_delete=models.CASCADE)
    measurement_type = models.CharField(max_length=20, choices=MEASUREMENT_TYPES)
    points = models.TextField()  # JSON array of points
    value = models.FloatField(null=True, blank=True)
    unit = models.CharField(max_length=16, default="mm")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_points(self, points_list):
        self.points = json.dumps(points_list)

    def get_points(self):
        return json.loads(self.points) if self.points else []


class Annotation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    image = models.ForeignKey(DicomImage, on_delete=models.CASCADE)
    position_x = models.FloatField()
    position_y = models.FloatField()
    text = models.TextField()
    color = models.CharField(max_length=7, default="#FFFF00")  # Hex color
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Annotation: {self.text[:50]}"


class ReconstructionJob(models.Model):
    JOB_TYPES = [
        ("mpr", "Multiplanar Reconstruction"),
        ("mip", "Maximum Intensity Projection"),
        ("bone_3d", "Bone 3D Reconstruction"),
        ("mri_3d", "MRI 3D Reconstruction"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    series = models.ForeignKey(Series, on_delete=models.CASCADE)
    job_type = models.CharField(max_length=20, choices=JOB_TYPES)
    parameters = models.TextField(blank=True)  # JSON
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    result_path = models.CharField(max_length=500, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def set_parameters(self, params):
        self.parameters = json.dumps(params)

    def get_parameters(self):
        return json.loads(self.parameters) if self.parameters else {}


class HangingProtocol(models.Model):
    """Simple hanging protocol definition per modality/body part.
    Defines default layout for the web viewer (e.g., 1x1, 2x2, tri-planar).
    """
    modality = models.CharField(max_length=16, blank=True)  # CT, MR, XR, etc.
    body_part = models.CharField(max_length=64, blank=True)
    name = models.CharField(max_length=128)
    layout = models.CharField(max_length=32, default="1x1")  # e.g., '1x1', '2x2', 'mpr-3plane'
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.modality or '*'} {self.body_part or '*'} - {self.name} ({self.layout})"


class WindowLevelPreset(models.Model):
    """Per-user window/level presets optionally scoped by modality/body part."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=64)
    modality = models.CharField(max_length=16, blank=True)
    body_part = models.CharField(max_length=64, blank=True)
    window_width = models.FloatField()
    window_level = models.FloatField()
    inverted = models.BooleanField(default=False)

    class Meta:
        unique_together = ("user", "name", "modality", "body_part")

    def __str__(self):
        return f"{self.user_id}:{self.name} ({self.modality or '*'})"


class HounsfieldCalibration(models.Model):
    """Track Hounsfield Unit calibration for CT scanners"""
    CALIBRATION_STATUS = [
        ('valid', 'Valid'),
        ('invalid', 'Invalid'),
        ('warning', 'Warning'),
        ('not_applicable', 'Not Applicable'),
        ('error', 'Error'),
    ]
    
    # Scanner identification
    manufacturer = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    station_name = models.CharField(max_length=100, blank=True)
    device_serial_number = models.CharField(max_length=100, blank=True)
    
    # Study reference
    study = models.ForeignKey(Study, on_delete=models.CASCADE, related_name='hu_calibrations')
    series = models.ForeignKey(Series, on_delete=models.CASCADE, null=True, blank=True)
    
    # Calibration parameters
    rescale_slope = models.FloatField()
    rescale_intercept = models.FloatField()
    rescale_type = models.CharField(max_length=20, blank=True)
    
    # Measured values
    water_hu = models.FloatField(null=True, blank=True)
    air_hu = models.FloatField(null=True, blank=True)
    noise_level = models.FloatField(null=True, blank=True)
    
    # Validation results
    calibration_status = models.CharField(max_length=20, choices=CALIBRATION_STATUS)
    is_valid = models.BooleanField(default=False)
    validation_issues = models.JSONField(default=list, blank=True)
    validation_warnings = models.JSONField(default=list, blank=True)
    
    # Quality metrics
    water_deviation = models.FloatField(null=True, blank=True)
    air_deviation = models.FloatField(null=True, blank=True)
    linearity_check = models.FloatField(null=True, blank=True)
    
    # Metadata
    calibration_date = models.DateField(null=True, blank=True)
    phantom_type = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    
    # Tracking
    validated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"HU Calibration for {self.station_name or 'Unknown'} - {self.calibration_status}"
    
    def get_status_color(self):
        """Get color for status display"""
        status_colors = {
            'valid': 'success',
            'invalid': 'danger',
            'warning': 'warning',
            'not_applicable': 'secondary',
            'error': 'danger'
        }
        return status_colors.get(self.calibration_status, 'secondary')
    
    def calculate_deviations(self):
        """Calculate deviations from reference values"""
        if self.water_hu is not None:
            self.water_deviation = abs(self.water_hu - 0.0)  # Water reference is 0 HU
        
        if self.air_hu is not None:
            self.air_deviation = abs(self.air_hu - (-1000.0))  # Air reference is -1000 HU


class HounsfieldQAPhantom(models.Model):
    """Define QA phantoms for Hounsfield unit calibration"""
    name = models.CharField(max_length=100)
    manufacturer = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    
    # Phantom specifications
    water_roi_coordinates = models.JSONField(help_text="ROI coordinates for water measurement")
    air_roi_coordinates = models.JSONField(help_text="ROI coordinates for air measurement")
    material_rois = models.JSONField(default=dict, help_text="Additional material ROI coordinates")
    
    # Reference values
    expected_water_hu = models.FloatField(default=0.0)
    expected_air_hu = models.FloatField(default=-1000.0)
    expected_materials = models.JSONField(default=dict, help_text="Expected HU values for materials")
    
    # Tolerances
    water_tolerance = models.FloatField(default=5.0)
    air_tolerance = models.FloatField(default=50.0)
    material_tolerances = models.JSONField(default=dict)
    
    # Metadata
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} ({self.manufacturer})"
