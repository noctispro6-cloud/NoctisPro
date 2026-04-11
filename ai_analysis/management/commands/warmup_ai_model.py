"""
Management command: warmup_ai_model

Pre-downloads and caches the local AI language model so the first report
generation request is fast. Run once after deployment:

    python manage.py warmup_ai_model

This downloads the model to ~/.cache/huggingface/ and runs a quick test.
"""
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Pre-download and cache the local AI language model for report generation'

    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            default=None,
            help='HuggingFace model ID to download (default: AI_LOCAL_MODEL setting)',
        )
        parser.add_argument(
            '--test',
            action='store_true',
            help='Run a quick test generation after download',
        )

    def handle(self, *args, **options):
        import os
        model_id = options['model'] or getattr(settings, 'AI_LOCAL_MODEL', 'google/flan-t5-base')

        self.stdout.write(f'Warming up AI model: {model_id}')
        self.stdout.write('This may take several minutes on first run (downloading model weights)...')

        try:
            from ai_analysis.llm_reporting import _load_local_model
            import ai_analysis.llm_reporting as lr

            # Override model setting for this run
            os.environ['AI_LOCAL_MODEL'] = model_id

            pipe = _load_local_model()
            if pipe is None:
                self.stderr.write(self.style.ERROR(
                    f'Failed to load model. Check logs for details. '
                    f'Error: {lr._local_pipeline_error}'
                ))
                return

            self.stdout.write(self.style.SUCCESS(f'Model loaded successfully: {model_id}'))

            if options['test']:
                self.stdout.write('Running test report generation...')
                from ai_analysis.llm_reporting import generate_llm_report
                result = generate_llm_report(
                    modality='CT',
                    body_part='chest',
                    clinical_info='Cough and fever for 3 days',
                    findings_summary='Possible lower lobe consolidation',
                    abnormalities=['consolidation', 'air bronchograms'],
                    triage_level='high',
                    confidence=0.78,
                )
                self.stdout.write('\n--- Test Report ---')
                self.stdout.write(f"Backend: {result.get('llm_used', 'unknown')}")
                self.stdout.write(f"FINDINGS: {result.get('findings', '')[:200]}...")
                self.stdout.write(f"IMPRESSION: {result.get('impression', '')}")
                self.stdout.write('--- End Test ---\n')
                self.stdout.write(self.style.SUCCESS('Test passed!'))

        except ImportError as e:
            self.stderr.write(self.style.ERROR(
                f'Import error: {e}\n'
                'Ensure transformers and torch are installed: pip install transformers torch'
            ))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Unexpected error: {e}'))
