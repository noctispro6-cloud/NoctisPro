from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from ai_analysis.models import AIModel
from django.utils import timezone


User = get_user_model()


BASELINE_MODELS = [
    {
        'name': 'Chest X-Ray Classifier',
        'version': '1.0',
        'model_type': 'classification',
        'modality': 'CR',
        'body_part': 'CHEST',
        'description': 'Baseline chest X-ray classification model (placeholder).',
        'training_data_info': 'Pretrained on public CXR datasets (placeholder metadata).',
        'accuracy_metrics': {'auc': 0.85, 'macro_f1': 0.78},
        'model_file_path': '/models/cxr_classifier.pt',
        'config_file_path': '',
        'preprocessing_config': {'resize': [512, 512], 'normalize': True},
    },
    {
        'name': 'CT Brain Segmentation',
        'version': '1.0',
        'model_type': 'segmentation',
        'modality': 'CT',
        'body_part': 'BRAIN',
        'description': 'Baseline CT brain segmentation model (placeholder).',
        'training_data_info': 'Trained on public CT brain datasets (placeholder).',
        'accuracy_metrics': {'dice': 0.82},
        'model_file_path': '/models/ct_brain_segmentation.pt',
        'config_file_path': '',
        'preprocessing_config': {'window': [40, 80]},
    },
    {
        'name': 'Auto Report Generator',
        'version': '1.0',
        'model_type': 'report_generation',
        'modality': 'CT',
        'body_part': '',
        'description': 'Baseline report generation (template-assisted, placeholder).',
        'training_data_info': 'Uses templates and rules; can integrate with LLM if configured.',
        'accuracy_metrics': {'bleu': 0.3},
        'model_file_path': '/models/report_generator.pt',
        'config_file_path': '',
        'preprocessing_config': {},
    },
]


class Command(BaseCommand):
    help = 'Setup baseline AI models (placeholders) so AI pages work without heavy downloads.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🤖 Setting up baseline AI models...'))

        created = 0
        for m in BASELINE_MODELS:
            obj, was_created = AIModel.objects.get_or_create(
                name=m['name'], version=m['version'], defaults={
                    'model_type': m['model_type'],
                    'modality': m['modality'],
                    'body_part': m['body_part'],
                    'description': m['description'],
                    'training_data_info': m['training_data_info'],
                    'accuracy_metrics': m['accuracy_metrics'],
                    'model_file_path': m['model_file_path'],
                    'config_file_path': m['config_file_path'],
                    'preprocessing_config': m['preprocessing_config'],
                    'is_active': True,
                    'is_trained': False,
                }
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f'✅ Created AI model: {obj.name}'))
            else:
                self.stdout.write(self.style.WARNING(f'⚠️  Model already exists: {obj.name}'))

        self.stdout.write(self.style.SUCCESS(f'📊 Baseline models created: {created}'))
        self.stdout.write(self.style.SUCCESS(f'🧠 Total AI models available: {AIModel.objects.count()}'))
        self.stdout.write(self.style.SUCCESS('🎉 AI model setup complete.'))

