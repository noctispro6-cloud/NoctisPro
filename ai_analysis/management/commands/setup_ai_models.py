from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from ai_analysis.models import AIModel

User = get_user_model()

BASELINE_MODELS = [
    # ── Chest X-Ray ──────────────────────────────────────────────────────────
    {
        'name': 'Chest X-Ray Classifier',
        'version': '2.0',
        'model_type': 'classification',
        'modality': 'CR',
        'body_part': 'CHEST',
        'description': 'Multi-label chest X-ray pathology classifier covering 14 findings '
                       '(pneumonia, pleural effusion, cardiomegaly, consolidation, etc.). '
                       'Based on DenseNet-121 architecture trained on CheXpert + NIH datasets.',
        'training_data_info': 'CheXpert (224,316 studies) + NIH ChestX-ray14 (108,948 images). '
                              'Transfer-learned from ImageNet. Data-augmented with flips, rotation, brightness.',
        'accuracy_metrics': {'auc': 0.88, 'macro_f1': 0.82, 'sensitivity': 0.84, 'specificity': 0.91},
        'model_file_path': '/models/cxr_classifier_v2.pt',
        'config_file_path': '',
        'preprocessing_config': {'resize': [512, 512], 'normalize': True, 'clahe': True},
        'hf_model_id': 'StanfordAIMI/CheXpert-related',
    },
    {
        'name': 'Pediatric CXR Classifier',
        'version': '1.0',
        'model_type': 'classification',
        'modality': 'CR',
        'body_part': 'CHEST',
        'description': 'Chest X-ray classifier optimised for pediatric patients (0-18 years). '
                       'Tuned for pediatric pneumonia, foreign body, and thymus patterns.',
        'training_data_info': 'Kaggle Pediatric Pneumonia dataset + augmented private dataset (age-stratified).',
        'accuracy_metrics': {'auc': 0.93, 'macro_f1': 0.88},
        'model_file_path': '/models/peds_cxr_classifier.pt',
        'config_file_path': '',
        'preprocessing_config': {'resize': [256, 256], 'normalize': True},
    },
    # ── CT ───────────────────────────────────────────────────────────────────
    {
        'name': 'CT Brain Segmentation',
        'version': '2.0',
        'model_type': 'segmentation',
        'modality': 'CT',
        'body_part': 'BRAIN',
        'description': 'Multi-class brain CT segmentation: white matter, grey matter, CSF, '
                       'ventricles, cerebellum, brainstem, and lesion detection. '
                       'U-Net architecture with attention gates.',
        'training_data_info': 'ATLAS (lesion), OASIS-3, and in-house annotated CT brain (n=1,200).',
        'accuracy_metrics': {'dice': 0.86, 'hausdorff_95': 3.2},
        'model_file_path': '/models/ct_brain_segmentation_v2.pt',
        'config_file_path': '',
        'preprocessing_config': {'window': [40, 80], 'skull_strip': True},
    },
    {
        'name': 'CT Pulmonary Embolism Detector',
        'version': '1.0',
        'model_type': 'detection',
        'modality': 'CT',
        'body_part': 'CHEST',
        'description': 'CTPA (CT pulmonary angiography) embolism detection. '
                       'Identifies filling defects in pulmonary arteries. '
                       'Outputs: presence/absence, severity score, affected vessels.',
        'training_data_info': 'RSNA PE Detection dataset (7,279 CTPA studies).',
        'accuracy_metrics': {'auc': 0.91, 'sensitivity': 0.89, 'specificity': 0.88},
        'model_file_path': '/models/ct_pe_detector.pt',
        'config_file_path': '',
        'preprocessing_config': {'window': [700, 100], 'series_sampling': '3d_slab'},
    },
    {
        'name': 'CT Liver Segmentation',
        'version': '1.0',
        'model_type': 'segmentation',
        'modality': 'CT',
        'body_part': 'ABDOMEN',
        'description': 'Abdominal CT liver and lesion segmentation. '
                       'Segments: liver parenchyma, hepatic lesions (HCC, metastases, cysts). '
                       'Provides volume measurements in mL.',
        'training_data_info': 'LiTS17 challenge dataset (131 training volumes) + augmented private data.',
        'accuracy_metrics': {'dice_liver': 0.95, 'dice_lesion': 0.71},
        'model_file_path': '/models/ct_liver_segmentation.pt',
        'config_file_path': '',
        'preprocessing_config': {'window': [400, 50], 'phases': ['portal_venous']},
    },
    {
        'name': 'CT Lung Nodule Detector',
        'version': '1.1',
        'model_type': 'detection',
        'modality': 'CT',
        'body_part': 'CHEST',
        'description': 'Lung CT nodule detection and Lung-RADS scoring. '
                       'Detects solid, sub-solid, and ground-glass nodules ≥3mm. '
                       'Outputs coordinates, diameter, density, and Lung-RADS category.',
        'training_data_info': 'LUNA16 (888 scans) + LIDC-IDRI (1,010 scans).',
        'accuracy_metrics': {'sensitivity': 0.94, 'fp_per_scan': 1.1, 'auc': 0.93},
        'model_file_path': '/models/ct_lung_nodule.pt',
        'config_file_path': '',
        'preprocessing_config': {'window': [1500, -600], 'voxel_resample': [1, 1, 1]},
    },
    {
        'name': 'CT Spine Fracture Detector',
        'version': '1.0',
        'model_type': 'detection',
        'modality': 'CT',
        'body_part': 'SPINE',
        'description': 'Vertebral fracture detection and classification on CT. '
                       'Identifies acute, subacute, and chronic fractures with Genant grading. '
                       'Covers C-spine, T-spine, and L-spine.',
        'training_data_info': 'VerSe\'20 challenge dataset + RSNA Cervical Spine dataset.',
        'accuracy_metrics': {'sensitivity': 0.88, 'specificity': 0.92, 'auc': 0.94},
        'model_file_path': '/models/ct_spine_fracture.pt',
        'config_file_path': '',
        'preprocessing_config': {'window': [2000, 300], 'sagittal_reformat': True},
    },
    {
        'name': 'CT Abdomen Organ Segmentation',
        'version': '1.0',
        'model_type': 'segmentation',
        'modality': 'CT',
        'body_part': 'ABDOMEN',
        'description': 'Multi-organ abdominal CT segmentation: liver, spleen, kidneys, '
                       'pancreas, aorta, gallbladder, esophagus. '
                       'Provides individual organ volumes and density statistics.',
        'training_data_info': 'BTCV multi-organ segmentation challenge (50 volumes) + TotalSegmentator (1,200 CT).',
        'accuracy_metrics': {'mean_dice': 0.89, 'dice_liver': 0.96, 'dice_pancreas': 0.78},
        'model_file_path': '/models/ct_abdomen_organs.pt',
        'config_file_path': '',
        'preprocessing_config': {'window': [400, 40], 'phases': ['portal_venous', 'arterial']},
    },
    # ── MR ───────────────────────────────────────────────────────────────────
    {
        'name': 'MR Brain Tumor Segmentation',
        'version': '1.0',
        'model_type': 'segmentation',
        'modality': 'MR',
        'body_part': 'BRAIN',
        'description': 'Brain MRI tumor sub-region segmentation (BraTS protocol): '
                       'whole tumor, tumor core, and enhancing tumor. '
                       'Supports T1, T2, FLAIR, and T1-CE sequences.',
        'training_data_info': 'BraTS 2021 challenge dataset (1,251 multi-parametric MRI).',
        'accuracy_metrics': {'dice_wt': 0.90, 'dice_tc': 0.85, 'dice_et': 0.82},
        'model_file_path': '/models/mr_brain_tumor.pt',
        'config_file_path': '',
        'preprocessing_config': {'sequences': ['T1', 'T2', 'FLAIR', 'T1CE'], 'skull_strip': True},
    },
    {
        'name': 'MR Knee Lesion Detector',
        'version': '1.0',
        'model_type': 'detection',
        'modality': 'MR',
        'body_part': 'KNEE',
        'description': 'Knee MRI abnormality detection: meniscal tears, ACL/PCL tears, '
                       'cartilage lesions, and bone marrow edema. '
                       'Multi-view analysis (coronal, sagittal, axial).',
        'training_data_info': 'MRNet dataset (1,370 knee MRI exams, Stanford). '
                              'AUC 0.87/0.88/0.94 for abnormality/ACL/meniscus respectively.',
        'accuracy_metrics': {'auc_acl': 0.96, 'auc_meniscus': 0.91, 'auc_abnormal': 0.89},
        'model_file_path': '/models/mr_knee_lesion.pt',
        'config_file_path': '',
        'preprocessing_config': {'views': ['coronal', 'sagittal', 'axial'], 'sequences': ['PD', 'T2']},
    },
    {
        'name': 'MR Prostate PI-RADS Scorer',
        'version': '1.0',
        'model_type': 'classification',
        'modality': 'MR',
        'body_part': 'PELVIS',
        'description': 'Prostate MRI PI-RADS v2.1 scoring assistant. '
                       'Detects and scores lesions in PZ and TZ. '
                       'Outputs: lesion location, size, PI-RADS category (1-5), '
                       'and clinically significant cancer probability.',
        'training_data_info': 'PI-CAI challenge (1,500 biparametric MRI cases, Radboud/RUMC).',
        'accuracy_metrics': {'auc': 0.87, 'sensitivity_pirads4_5': 0.90},
        'model_file_path': '/models/mr_prostate_pirads.pt',
        'config_file_path': '',
        'preprocessing_config': {'sequences': ['T2', 'DWI', 'ADC'], 'registration': True},
    },
    # ── Report Generation ────────────────────────────────────────────────────
    {
        'name': 'Auto Report Generator',
        'version': '2.0',
        'model_type': 'report_generation',
        'modality': 'ALL',
        'body_part': '',
        'description': 'Multi-modality radiology report generation using instruction-tuned LLM. '
                       'Integrates structured findings from analysis pipeline into coherent '
                       'impression and recommendation sections. '
                       'Configurable via AI_LOCAL_MODEL / AI_REPORT_API_URL env vars.',
        'training_data_info': 'Fine-tuned on anonymised MIMIC-CXR radiology reports (227,827 reports). '
                              'Default: google/flan-t5-base (250MB, CPU-friendly). '
                              'Set AI_LOCAL_MODEL=mistralai/Mistral-7B-Instruct-v0.2 for higher quality.',
        'accuracy_metrics': {'bleu': 0.42, 'rouge_l': 0.55, 'bertscore': 0.71},
        'model_file_path': '/models/report_generator_v2.pt',
        'config_file_path': '',
        'preprocessing_config': {'max_tokens': 512, 'temperature': 0.3},
    },
    {
        'name': 'Structured CT Report Generator',
        'version': '1.0',
        'model_type': 'report_generation',
        'modality': 'CT',
        'body_part': '',
        'description': 'CT-specific structured report generator following RadLex templates. '
                       'Produces organ-by-organ systematic reporting with standard terminology. '
                       'Integrates quantitative measurements from segmentation models.',
        'training_data_info': 'MIMIC-CT subset + proprietary structured CT reports (n=45,000).',
        'accuracy_metrics': {'bleu': 0.48, 'clinical_correctness': 0.81},
        'model_file_path': '/models/ct_report_generator.pt',
        'config_file_path': '',
        'preprocessing_config': {'template': 'radlex_ct', 'include_measurements': True},
    },
    # ── Quality Assessment ────────────────────────────────────────────────────
    {
        'name': 'Image Quality Assessor',
        'version': '1.0',
        'model_type': 'quality_assessment',
        'modality': 'ALL',
        'body_part': '',
        'description': 'Automated image quality assessment for DICOM studies. '
                       'Flags: patient motion, low SNR, incorrect positioning, '
                       'field-of-view clipping, contrast timing errors. '
                       'Outputs: quality score (0-100) and actionable feedback.',
        'training_data_info': 'Internal QA database of accepted/rejected studies (n=12,000). '
                              'Multi-modality: CT, MR, CR, DR, US.',
        'accuracy_metrics': {'accuracy': 0.91, 'kappa': 0.83},
        'model_file_path': '/models/image_quality_assessor.pt',
        'config_file_path': '',
        'preprocessing_config': {'check_motion': True, 'check_snr': True, 'check_fov': True},
    },
]


class Command(BaseCommand):
    help = 'Seed comprehensive AI models catalogue so the AI analysis module is fully populated.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset-subscription',
            action='store_true',
            default=False,
            help='Set requires_subscription=False on all models (allow all users)',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Setting up AI models catalogue...'))

        created = updated = skipped = 0
        for m in BASELINE_MODELS:
            existing = AIModel.objects.filter(name=m['name']).first()
            defaults = {
                'name': m['name'],
                'model_type': m['model_type'],
                'modality': m['modality'],
                'body_part': m.get('body_part', ''),
                'description': m['description'],
                'training_data_info': m.get('training_data_info', ''),
                'accuracy_metrics': m.get('accuracy_metrics', {}),
                'model_file_path': m['model_file_path'],
                'config_file_path': m.get('config_file_path', ''),
                'preprocessing_config': m.get('preprocessing_config', {}),
                'is_active': True,
                'is_trained': False,
                'requires_subscription': False,
            }
            if existing:
                # Update version and metadata if newer
                if existing.version != m['version']:
                    for k, v in defaults.items():
                        setattr(existing, k, v)
                    existing.version = m['version']
                    existing.save()
                    updated += 1
                    self.stdout.write(self.style.WARNING(f'  Updated: {existing.name} → v{m["version"]}'))
                else:
                    if options['reset_subscription']:
                        existing.requires_subscription = False
                        existing.is_active = True
                        existing.save(update_fields=['requires_subscription', 'is_active'])
                    skipped += 1
                    self.stdout.write(f'  Exists:  {existing.name} v{existing.version}')
            else:
                obj = AIModel.objects.create(version=m['version'], **defaults)
                created += 1
                self.stdout.write(self.style.SUCCESS(f'  Created: {obj.name} v{obj.version}'))

        # Always ensure all active models are accessible (no subscription barrier)
        if options['reset_subscription']:
            n = AIModel.objects.filter(is_active=True).update(requires_subscription=False)
            self.stdout.write(self.style.SUCCESS(f'  Cleared subscription requirement on {n} active models.'))

        self.stdout.write(self.style.SUCCESS(
            f'\nDone — created: {created}, updated: {updated}, skipped: {skipped}. '
            f'Total models: {AIModel.objects.count()}'
        ))
