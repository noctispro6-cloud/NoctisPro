from django.db import models
from django.utils import timezone
from accounts.models import User, Facility
from worklist.models import Study, DicomImage
# from reports.models import Report  # Temporarily disabled
import json

class AIModel(models.Model):
    """AI models used for analysis"""
    MODEL_TYPES = [
        ('classification', 'Classification'),
        ('detection', 'Object Detection'),
        ('segmentation', 'Segmentation'),
        ('reconstruction', 'Reconstruction'),
        ('report_generation', 'Report Generation'),
        ('quality_assessment', 'Quality Assessment'),
    ]

    name = models.CharField(max_length=100)
    version = models.CharField(max_length=20)
    model_type = models.CharField(max_length=30, choices=MODEL_TYPES)
    modality = models.CharField(max_length=10)  # CT, MR, XR, etc.
    body_part = models.CharField(max_length=100, blank=True)
    
    # Model details
    description = models.TextField()
    training_data_info = models.TextField(blank=True)
    accuracy_metrics = models.JSONField(default=dict, blank=True)
    
    # Model files and configuration
    model_file_path = models.CharField(max_length=500)
    config_file_path = models.CharField(max_length=500, blank=True)
    preprocessing_config = models.JSONField(default=dict, blank=True)
    
    # Status and management
    is_active = models.BooleanField(default=True)
    is_trained = models.BooleanField(default=False)
    last_trained = models.DateTimeField(null=True, blank=True)
    
    # Performance tracking
    total_analyses = models.IntegerField(default=0)
    avg_processing_time = models.FloatField(default=0)  # in seconds
    success_rate = models.FloatField(default=0)  # percentage
    
    # Subscription Enforcement
    requires_subscription = models.BooleanField(default=True, help_text="If true, only users with active AI subscription can use this model")
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} v{self.version} - {self.modality}"

class AIAnalysis(models.Model):
    """AI analysis results for studies"""
    ANALYSIS_STATUS = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    PRIORITY_LEVELS = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    study = models.ForeignKey(Study, on_delete=models.CASCADE, related_name='ai_analyses')
    ai_model = models.ForeignKey(AIModel, on_delete=models.CASCADE)
    
    # Analysis parameters
    status = models.CharField(max_length=20, choices=ANALYSIS_STATUS, default='pending')
    priority = models.CharField(max_length=10, choices=PRIORITY_LEVELS, default='normal')
    
    # Results
    confidence_score = models.FloatField(null=True, blank=True)
    findings = models.TextField(blank=True)
    abnormalities_detected = models.JSONField(default=list, blank=True)
    measurements = models.JSONField(default=dict, blank=True)
    
    # Processing details
    processing_time = models.FloatField(null=True, blank=True)  # seconds
    error_message = models.TextField(blank=True)
    
    # Review and validation
    human_reviewed = models.BooleanField(default=False)
    reviewer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    review_notes = models.TextField(blank=True)
    accuracy_rating = models.IntegerField(null=True, blank=True)  # 1-5 scale
    
    # Timestamps
    requested_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f"AI Analysis - {self.study.accession_number} with {self.ai_model.name}"

    def start_processing(self):
        """Mark analysis as started"""
        self.status = 'processing'
        self.started_at = timezone.now()
        self.save()

    def complete_analysis(self, results):
        """Complete the analysis with results"""
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.confidence_score = results.get('confidence', 0)
        self.findings = results.get('findings', '')
        self.abnormalities_detected = results.get('abnormalities', [])
        self.measurements = results.get('measurements', {})
        
        if self.started_at:
            processing_time = (self.completed_at - self.started_at).total_seconds()
            self.processing_time = processing_time
        
        self.save()

class AutoReportTemplate(models.Model):
    """Templates for AI-generated reports"""
    name = models.CharField(max_length=200)
    modality = models.CharField(max_length=10)
    body_part = models.CharField(max_length=100)
    
    # Template structure
    findings_template = models.TextField()
    impression_template = models.TextField()
    recommendations_template = models.TextField(blank=True)
    
    # AI model associations
    ai_models = models.ManyToManyField(AIModel, blank=True)
    
    # Template rules
    confidence_threshold = models.FloatField(default=0.7)
    requires_human_review = models.BooleanField(default=True)
    
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.modality} {self.body_part}"

class AutoGeneratedReport(models.Model):
    """AI-generated reports awaiting review"""
    study = models.OneToOneField(Study, on_delete=models.CASCADE, related_name='auto_report')
    template = models.ForeignKey(AutoReportTemplate, on_delete=models.SET_NULL, null=True)
    ai_analysis = models.ForeignKey(AIAnalysis, on_delete=models.CASCADE)
    
    # Generated content
    generated_findings = models.TextField()
    generated_impression = models.TextField()
    generated_recommendations = models.TextField(blank=True)
    
    # Quality metrics
    overall_confidence = models.FloatField()
    requires_review = models.BooleanField(default=True)
    
    # Review process
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='reviewed_auto_reports')
    review_status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('modified', 'Modified'),
        ('rejected', 'Rejected'),
    ], default='pending')
    
    review_comments = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    # Final report reference
    # final_report = models.OneToOneField(Report, on_delete=models.SET_NULL, 
    #                                    null=True, blank=True,
    #                                    related_name='auto_generated_source')  # Temporarily disabled
    
    generated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Auto Report for {self.study.accession_number}"

    def approve_and_create_report(self, radiologist):
        """Approve the auto-generated report and create final report"""
        # Temporarily disabled - requires reports app
        # if self.review_status == 'pending':
        #     # Create the final report
        #     report = Report.objects.create(
        #         study=self.study,
        #         radiologist=radiologist,
        #         findings=self.generated_findings,
        #         impression=self.generated_impression,
        #         recommendations=self.generated_recommendations,
        #         ai_generated=True,
        #         ai_confidence=self.overall_confidence,
        #         status='preliminary'
        #     )
        #     
        #     self.final_report = report
        #     self.review_status = 'approved'
        #     self.reviewed_by = radiologist
        #     self.reviewed_at = timezone.now()
        #     self.save()
        #     
        #     return report
        pass
        return None

class AITrainingData(models.Model):
    """Training data for AI models"""
    DATA_TYPES = [
        ('image', 'Medical Image'),
        ('report', 'Medical Report'),
        ('annotation', 'Image Annotation'),
        ('measurement', 'Measurement Data'),
    ]

    ai_model = models.ForeignKey(AIModel, on_delete=models.CASCADE, related_name='training_data')
    study = models.ForeignKey(Study, on_delete=models.CASCADE, null=True, blank=True)
    image = models.ForeignKey(DicomImage, on_delete=models.CASCADE, null=True, blank=True)
    # report = models.ForeignKey(Report, on_delete=models.CASCADE, null=True, blank=True)  # Temporarily disabled
    
    data_type = models.CharField(max_length=20, choices=DATA_TYPES)
    
    # Labels and annotations
    ground_truth_labels = models.JSONField(default=dict, blank=True)
    annotations = models.JSONField(default=list, blank=True)
    quality_score = models.FloatField(default=1.0)  # 0-1 quality rating
    
    # Data source and validation
    validated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    validation_notes = models.TextField(blank=True)
    is_validated = models.BooleanField(default=False)
    
    # Usage tracking
    used_in_training = models.BooleanField(default=False)
    training_split = models.CharField(max_length=20, choices=[
        ('train', 'Training'),
        ('validation', 'Validation'),
        ('test', 'Test'),
    ], blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Training data for {self.ai_model.name} - {self.data_type}"

class AIPerformanceMetric(models.Model):
    """Track AI model performance over time"""
    ai_model = models.ForeignKey(AIModel, on_delete=models.CASCADE, related_name='performance_metrics')
    
    # Evaluation period
    evaluation_date = models.DateField()
    sample_size = models.IntegerField()
    
    # Performance metrics
    accuracy = models.FloatField()
    precision = models.FloatField()
    recall = models.FloatField()
    f1_score = models.FloatField()
    auc_score = models.FloatField(null=True, blank=True)
    
    # Detailed metrics by category
    metrics_by_category = models.JSONField(default=dict, blank=True)
    
    # Comparison with previous version
    previous_accuracy = models.FloatField(null=True, blank=True)
    improvement_percentage = models.FloatField(null=True, blank=True)
    
    # Notes and analysis
    evaluation_notes = models.TextField(blank=True)
    recommended_actions = models.TextField(blank=True)
    
    evaluated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['ai_model', 'evaluation_date']
        ordering = ['-evaluation_date']

    def __str__(self):
        return f"Performance for {self.ai_model.name} on {self.evaluation_date}"

class AIFeedback(models.Model):
    """User feedback on AI analysis results"""
    FEEDBACK_TYPES = [
        ('accuracy', 'Accuracy Assessment'),
        ('false_positive', 'False Positive'),
        ('false_negative', 'False Negative'),
        ('suggestion', 'Improvement Suggestion'),
        ('bug_report', 'Bug Report'),
    ]

    ai_analysis = models.ForeignKey(AIAnalysis, on_delete=models.CASCADE, related_name='feedback')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    feedback_type = models.CharField(max_length=20, choices=FEEDBACK_TYPES)
    rating = models.IntegerField()  # 1-5 scale
    comments = models.TextField()
    
    # Specific feedback details
    incorrect_findings = models.JSONField(default=list, blank=True)
    missed_findings = models.JSONField(default=list, blank=True)
    suggestions = models.TextField(blank=True)
    
    # Status
    reviewed = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='reviewed_feedback')
    action_taken = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Feedback on {self.ai_analysis} by {self.user.username}"
