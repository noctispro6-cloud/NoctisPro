from django.urls import path
from . import views
from . import api_cpp

app_name = 'dicom_viewer'

urlpatterns = [
    # Main viewer interface - MASTERPIECE IS THE MAIN VIEWER
    path('', views.masterpiece_viewer, name='viewer'),
    path('legacy/', views.viewer, name='legacy_viewer'),
    path('masterpiece/', views.masterpiece_viewer, name='masterpiece_viewer'),
    # path('standalone/', views.standalone_viewer, name='standalone_viewer'),
    # path('advanced/', views.advanced_standalone_viewer, name='advanced_standalone_viewer'),
    path('launch-desktop/', views.launch_standalone_viewer, name='launch_standalone_viewer'),
    path('launch-desktop/<int:study_id>/', views.launch_study_in_desktop_viewer, name='launch_study_in_desktop_viewer'),
    # path('study/<int:study_id>/', views.view_study, name='view_study'),
    
    # API endpoints
    path('api/studies/', views.api_studies_redirect, name='api_studies_redirect'),
    path('api/study/<int:study_id>/data/', views.api_study_data, name='api_study_data'),
    path('api/image/<int:image_id>/data/', views.api_image_data, name='api_image_data'),
    path('api/image/<int:image_id>/display/', views.api_dicom_image_display, name='api_dicom_image_display'),
    
    # Advanced reconstruction endpoints
    path('api/series/<int:series_id>/mpr/', views.api_mpr_reconstruction, name='api_mpr_reconstruction'),
    path('api/series/<int:series_id>/mip/', views.api_mip_reconstruction, name='api_mip_reconstruction'),
    path('api/series/<int:series_id>/bone/', views.api_bone_reconstruction, name='api_bone_reconstruction'),
    path('api/series/<int:series_id>/sr-export/', views.api_series_sr_export, name='api_series_sr_export'),
    path('api/hu/', views.api_hu_value, name='api_hu_value'),
    path('api/hounsfield-units/', views.api_hounsfield_units, name='api_hounsfield_units'),
    path('api/auto-window/<int:image_id>/', views.api_auto_window, name='api_auto_window'),
    
    # Hounsfield Unit Calibration
    path('hu-calibration/', views.hu_calibration_dashboard, name='hu_calibration_dashboard'),
    path('hu-calibration/validate/<int:study_id>/', views.validate_hu_calibration, name='validate_hu_calibration'),
    path('hu-calibration/report/<int:calibration_id>/', views.hu_calibration_report, name='hu_calibration_report'),
    path('hu-calibration/phantoms/', views.manage_qa_phantoms, name='manage_qa_phantoms'),
    
    # Real-time features
    path('api/realtime/studies/', views.api_realtime_studies, name='api_realtime_studies'),
    path('api/study/<int:study_id>/progress/', views.api_study_progress, name='api_study_progress'),
    
    # Measurements and annotations
    path('api/study/<int:study_id>/measurements/', views.api_measurements, name='api_measurements'),
    path('api/measurements/', views.api_measurements, name='api_measurements_standalone'),
    path('api/calculate-distance/', views.api_calculate_distance, name='api_calculate_distance'),
    path('api/study/<int:study_id>/annotations/', views.api_annotations, name='api_annotations'),
    # Presets and hanging protocols
    path('api/presets/', views.api_user_presets, name='api_user_presets'),
    path('api/hanging/', views.api_hanging_protocols, name='api_hanging_protocols'),
    # DICOM SR export
    path('api/study/<int:study_id>/export-sr/', views.api_export_dicom_sr, name='api_export_dicom_sr'),
    # Volume endpoint for GPU VR
    path('api/series/<int:series_id>/volume/', views.api_series_volume_uint8, name='api_series_volume_uint8'),
    
    # DICOM file upload and processing (consolidated with worklist upload)
    # path('upload/', views.upload_dicom, name='upload_dicom'),  # Moved to worklist
    # path('load-directory/', views.load_from_directory, name='load_from_directory'),  # Consolidated with worklist upload
    path('api/mounts/', views.api_list_mounted_media, name='api_list_mounted_media'),
    path('api/upload/progress/<str:upload_id>/', views.api_upload_progress, name='api_upload_progress'),
    path('api/process/study/<int:study_id>/', views.api_process_study, name='api_process_study'),

    # C++ desktop viewer integration endpoints (compat layer)
    path('api/worklist/', api_cpp.api_cpp_worklist, name='api_cpp_worklist'),
    path('api/study-status/', api_cpp.api_cpp_study_status, name='api_cpp_study_status'),
    path('api/series/<str:study_id>/', api_cpp.api_cpp_series, name='api_cpp_series'),
    path('api/dicom-file/<str:instance_uid>/', api_cpp.api_cpp_dicom_file, name='api_cpp_dicom_file'),
    path('api/dicom-info/<str:instance_uid>/', api_cpp.api_cpp_dicom_info, name='api_cpp_dicom_info'),
    path('api/viewer-sessions/', api_cpp.api_cpp_viewer_sessions, name='api_cpp_viewer_sessions'),
]

urlpatterns += [
    # Web viewer pages
    path('web/', views.web_index, name='index'),
    path('web/viewer/', views.web_viewer, name='web_viewer'),


    # Web viewer JSON APIs
    path('study/<int:study_id>/', views.web_study_detail, name='web_study_detail'),
    path('series/<int:series_id>/images/', views.web_series_images, name='web_series_images'),
    path('image/<int:image_id>/', views.web_dicom_image, name='web_dicom_image'),

    # Measurements and annotations
    path('measurements/save/', views.web_save_measurement, name='web_save_measurement'),
    path('annotations/save/', views.web_save_annotation, name='web_save_annotation'),
    path('measurements/<int:image_id>/', views.web_get_measurements, name='web_get_measurements'),
    path('annotations/<int:image_id>/', views.web_get_annotations, name='web_get_annotations'),

    # Viewer session
    path('session/save/', views.web_save_viewer_session, name='web_save_viewer_session'),
    path('session/<int:study_id>/', views.web_load_viewer_session, name='web_load_viewer_session'),

    # Reconstructions
    path('reconstruction/start/', views.web_start_reconstruction, name='web_start_reconstruction'),
    path('reconstruction/status/<int:job_id>/', views.web_reconstruction_status, name='web_reconstruction_status'),
    path('reconstruction/result/<int:job_id>/', views.web_reconstruction_result, name='web_reconstruction_result'),
    
    # Printing functionality
    path('print/image/', views.print_dicom_image, name='print_dicom_image'),
    path('print/printers/', views.get_available_printers, name='get_available_printers'),
    path('print/layouts/', views.get_print_layouts, name='get_print_layouts'),
    path('print/settings/', views.print_settings_view, name='print_settings'),
    
    # AI and Advanced Features
    path('api/ai-3d-print/<int:series_id>/', views.ai_3d_print_api, name='ai_3d_print_api'),
    path('api/advanced-reconstruction/<int:series_id>/', views.advanced_reconstruction_api, name='advanced_reconstruction_api'),
    
    # Fast Reconstruction APIs
    path('api/fast-reconstruction/<int:series_id>/', views.fast_reconstruction_api, name='fast_reconstruction_api'),
    path('api/mpr-slice/<int:series_id>/<str:plane>/<int:slice_index>/', views.mpr_slice_api, name='mpr_slice_api'),
]
