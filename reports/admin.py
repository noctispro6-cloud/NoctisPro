from django.contrib import admin
from .models import Report, ReportTemplate, ReportComment, ReportAccess, MacroText, ReportAmendment


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ['study', 'radiologist', 'status', 'report_date', 'ai_generated']
    list_filter = ['status', 'ai_generated', 'report_date']
    search_fields = ['study__accession_number', 'radiologist__username', 'findings', 'impression']
    readonly_fields = ['report_date', 'signed_date', 'last_modified', 'signature_timestamp']


@admin.register(ReportTemplate)
class ReportTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'modality', 'is_active']
    list_filter = ['modality', 'is_active']


@admin.register(MacroText)
class MacroTextAdmin(admin.ModelAdmin):
    list_display = ['name', 'section', 'modality']
    list_filter = ['section', 'modality']


@admin.register(ReportComment)
class ReportCommentAdmin(admin.ModelAdmin):
    list_display = ['report', 'user', 'created_at']


@admin.register(ReportAccess)
class ReportAccessAdmin(admin.ModelAdmin):
    list_display = ['report', 'user', 'access_type', 'accessed_at']
    list_filter = ['access_type']


@admin.register(ReportAmendment)
class ReportAmendmentAdmin(admin.ModelAdmin):
    list_display = ['original_report', 'radiologist', 'amended_at']
    list_filter = ['amended_at']
    readonly_fields = ['amended_at']
