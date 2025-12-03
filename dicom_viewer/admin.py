from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.db.models import Count
from worklist.models import Study, Series, DicomImage, Patient
from .models import (
    ViewerSession, Measurement, Annotation, ReconstructionJob,
    HangingProtocol, WindowLevelPreset, HounsfieldCalibration,
    HounsfieldQAPhantom
)

# Enhanced Study Admin with DICOM Viewer integration
class SeriesInline(admin.TabularInline):
    model = Series
    fields = ['series_number', 'series_description', 'modality', 'image_count']
    readonly_fields = ['image_count']
    extra = 0
    
    def image_count(self, obj):
        return obj.images.count() if obj.id else 0
    image_count.short_description = 'Images'

# Enhanced DICOM Image Admin
class DicomImageInline(admin.TabularInline):
    model = DicomImage
    fields = ['instance_number', 'sop_instance_uid', 'file_size_display', 'processed']
    readonly_fields = ['sop_instance_uid', 'file_size_display']
    extra = 0
    
    def file_size_display(self, obj):
        if obj.file_size:
            if obj.file_size < 1024:
                return f"{obj.file_size} B"
            elif obj.file_size < 1024 * 1024:
                return f"{obj.file_size / 1024:.1f} KB"
            else:
                return f"{obj.file_size / (1024 * 1024):.1f} MB"
        return "Unknown"
    file_size_display.short_description = 'File Size'

# Viewer Session Admin
@admin.register(ViewerSession)
class ViewerSessionAdmin(admin.ModelAdmin):
    list_display = ['user', 'study_info', 'updated_at', 'session_duration']
    list_filter = ['created_at', 'updated_at']
    search_fields = ['user__username', 'study__accession_number']
    readonly_fields = ['created_at', 'updated_at', 'session_preview']
    
    def study_info(self, obj):
        return format_html(
            '<strong>{}</strong><br><small>{}</small>',
            obj.study.accession_number,
            obj.study.patient.full_name if obj.study.patient else 'Unknown'
        )
    study_info.short_description = 'Study'
    
    def session_duration(self, obj):
        if obj.created_at and obj.updated_at:
            duration = obj.updated_at - obj.created_at
            return str(duration).split('.')[0]  # Remove microseconds
        return 'Unknown'
    session_duration.short_description = 'Duration'
    
    def session_preview(self, obj):
        data = obj.get_session_data()
        if data:
            preview = []
            for key, value in data.items():
                if key in ['current_image_index', 'window_width', 'window_level', 'zoom']:
                    preview.append(f"{key}: {value}")
            return format_html('<br>'.join(preview))
        return 'No session data'
    session_preview.short_description = 'Session Data Preview'

# Measurement Admin
@admin.register(Measurement)
class MeasurementAdmin(admin.ModelAdmin):
    list_display = ['user', 'image_info', 'measurement_type', 'value_display', 'created_at']
    list_filter = ['measurement_type', 'unit', 'created_at']
    search_fields = ['user__username', 'notes', 'image__sop_instance_uid']
    readonly_fields = ['created_at']
    
    def image_info(self, obj):
        return format_html(
            '<strong>Series {}</strong><br><small>{}</small>',
            obj.image.series.series_number,
            obj.image.series.study.accession_number
        )
    image_info.short_description = 'Image'
    
    def value_display(self, obj):
        if obj.value:
            return f"{obj.value:.2f} {obj.unit}"
        return 'N/A'
    value_display.short_description = 'Value'

# Annotation Admin
@admin.register(Annotation)
class AnnotationAdmin(admin.ModelAdmin):
    list_display = ['user', 'image_info', 'text_preview', 'color_display', 'created_at']
    list_filter = ['created_at', 'color']
    search_fields = ['user__username', 'text', 'image__sop_instance_uid']
    readonly_fields = ['created_at']
    
    def image_info(self, obj):
        return format_html(
            '<strong>Series {}</strong><br><small>{}</small>',
            obj.image.series.series_number,
            obj.image.series.study.accession_number
        )
    image_info.short_description = 'Image'
    
    def text_preview(self, obj):
        return obj.text[:50] + '...' if len(obj.text) > 50 else obj.text
    text_preview.short_description = 'Text'
    
    def color_display(self, obj):
        return format_html(
            '<div style="width: 20px; height: 20px; background-color: {}; border: 1px solid #ccc; display: inline-block;"></div> {}',
            obj.color, obj.color
        )
    color_display.short_description = 'Color'

# Reconstruction Job Admin
@admin.register(ReconstructionJob)
class ReconstructionJobAdmin(admin.ModelAdmin):
    list_display = ['user', 'series_info', 'job_type', 'status_display', 'progress', 'created_at']
    list_filter = ['job_type', 'status', 'created_at']
    search_fields = ['user__username', 'series__series_description']
    readonly_fields = ['created_at', 'completed_at', 'progress_bar']
    
    def series_info(self, obj):
        return format_html(
            '<strong>Series {}</strong><br><small>{}</small>',
            obj.series.series_number,
            obj.series.study.accession_number
        )
    series_info.short_description = 'Series'
    
    def status_display(self, obj):
        colors = {
            'pending': 'warning',
            'processing': 'info',
            'completed': 'success',
            'failed': 'danger'
        }
        color = colors.get(obj.status, 'secondary')
        return format_html(
            '<span class="badge badge-{}">{}</span>',
            color, obj.get_status_display()
        )
    status_display.short_description = 'Status'
    
    def progress(self, obj):
        if obj.status == 'completed':
            return '100%'
        elif obj.status == 'processing':
            return '50%'  # Simplified progress
        elif obj.status == 'failed':
            return 'Failed'
        return '0%'
    progress.short_description = 'Progress'
    
    def progress_bar(self, obj):
        progress = 0
        if obj.status == 'completed':
            progress = 100
        elif obj.status == 'processing':
            progress = 50
        
        return format_html(
            '<div style="width: 200px; height: 20px; background: #f0f0f0; border-radius: 10px; overflow: hidden;">'
            '<div style="width: {}%; height: 100%; background: #007cba; transition: width 0.3s ease;"></div>'
            '</div>',
            progress
        )
    progress_bar.short_description = 'Progress Bar'

# Hanging Protocol Admin
@admin.register(HangingProtocol)
class HangingProtocolAdmin(admin.ModelAdmin):
    list_display = ['name', 'modality', 'body_part', 'layout', 'is_default']
    list_filter = ['modality', 'layout', 'is_default']
    search_fields = ['name', 'modality', 'body_part']

# Window Level Preset Admin
@admin.register(WindowLevelPreset)
class WindowLevelPresetAdmin(admin.ModelAdmin):
    list_display = ['user', 'name', 'modality', 'window_display', 'inverted']
    list_filter = ['modality', 'inverted', 'user']
    search_fields = ['name', 'user__username', 'modality']
    
    def window_display(self, obj):
        return f"WW: {obj.window_width}, WL: {obj.window_level}"
    window_display.short_description = 'Window/Level'

# Hounsfield Calibration Admin
@admin.register(HounsfieldCalibration)
class HounsfieldCalibrationAdmin(admin.ModelAdmin):
    list_display = [
        'study_info', 'station_name', 'calibration_status_display',
        'water_hu', 'air_hu', 'is_valid', 'calibration_date'
    ]
    list_filter = ['calibration_status', 'is_valid', 'calibration_date', 'manufacturer']
    search_fields = ['station_name', 'manufacturer', 'model', 'study__accession_number']
    readonly_fields = ['created_at', 'updated_at', 'validation_summary']
    
    fieldsets = (
        ('Scanner Information', {
            'fields': ('manufacturer', 'model', 'station_name', 'device_serial_number')
        }),
        ('Study Reference', {
            'fields': ('study', 'series')
        }),
        ('Calibration Parameters', {
            'fields': ('rescale_slope', 'rescale_intercept', 'rescale_type')
        }),
        ('Measured Values', {
            'fields': ('water_hu', 'air_hu', 'noise_level')
        }),
        ('Validation Results', {
            'fields': ('calibration_status', 'is_valid', 'validation_issues', 'validation_warnings')
        }),
        ('Quality Metrics', {
            'fields': ('water_deviation', 'air_deviation', 'linearity_check')
        }),
        ('Metadata', {
            'fields': ('calibration_date', 'phantom_type', 'notes', 'validated_by'),
            'classes': ('collapse',)
        }),
        ('Tracking', {
            'fields': ('created_at', 'updated_at', 'validation_summary'),
            'classes': ('collapse',)
        })
    )
    
    def study_info(self, obj):
        return format_html(
            '<strong>{}</strong><br><small>{}</small>',
            obj.study.accession_number,
            obj.study.patient.full_name if obj.study.patient else 'Unknown'
        )
    study_info.short_description = 'Study'
    
    def calibration_status_display(self, obj):
        colors = {
            'valid': 'success',
            'invalid': 'danger',
            'warning': 'warning',
            'not_applicable': 'secondary',
            'error': 'danger'
        }
        color = colors.get(obj.calibration_status, 'secondary')
        return format_html(
            '<span class="badge badge-{}">{}</span>',
            color, obj.get_calibration_status_display()
        )
    calibration_status_display.short_description = 'Status'
    
    def validation_summary(self, obj):
        summary = []
        if obj.validation_issues:
            summary.append(f"Issues: {len(obj.validation_issues)}")
        if obj.validation_warnings:
            summary.append(f"Warnings: {len(obj.validation_warnings)}")
        if obj.water_deviation:
            summary.append(f"Water deviation: {obj.water_deviation:.2f} HU")
        if obj.air_deviation:
            summary.append(f"Air deviation: {obj.air_deviation:.2f} HU")
        
        return format_html('<br>'.join(summary)) if summary else 'No validation data'
    validation_summary.short_description = 'Validation Summary'

# QA Phantom Admin
@admin.register(HounsfieldQAPhantom)
class HounsfieldQAPhantomAdmin(admin.ModelAdmin):
    list_display = ['name', 'manufacturer', 'model', 'is_active', 'created_at']
    list_filter = ['manufacturer', 'is_active', 'created_at']
    search_fields = ['name', 'manufacturer', 'model']
    readonly_fields = ['created_at']

# Custom admin site configuration
admin.site.site_header = "Noctis Pro DICOM Administration"
admin.site.site_title = "DICOM Admin"
admin.site.index_title = "Welcome to Noctis Pro DICOM Administration"