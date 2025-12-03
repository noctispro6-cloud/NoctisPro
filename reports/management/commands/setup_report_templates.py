from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from reports.models import ReportTemplate

User = get_user_model()

class Command(BaseCommand):
    help = 'Setup initial report templates for radiologists'

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('🏥 Setting up Noctis Pro PACS Report Templates...')
        )

        templates = [
            {
                'name': 'CT Chest Template',
                'modality': 'CT',
                'body_part': 'CHEST',
                'template_html': '''
<div class="medical-report">
    <h2>CT Chest Report</h2>
    
    <section class="clinical-history">
        <h3>Clinical History:</h3>
        <p>{{ clinical_history|default:"[Enter clinical history and indication]" }}</p>
    </section>
    
    <section class="technique">
        <h3>Technique:</h3>
        <p>{{ technique|default:"Axial CT images of the chest were obtained with intravenous contrast." }}</p>
    </section>
    
    <section class="comparison">
        <h3>Comparison:</h3>
        <p>{{ comparison|default:"[Enter comparison studies if available]" }}</p>
    </section>
    
    <section class="findings">
        <h3>Findings:</h3>
        <div class="findings-content">
            <p><strong>Lungs:</strong> {{ findings_lungs|default:"[Describe lung parenchyma, pleura, airways]" }}</p>
            <p><strong>Heart and Great Vessels:</strong> {{ findings_heart|default:"[Describe cardiac and vascular findings]" }}</p>
            <p><strong>Mediastinum:</strong> {{ findings_mediastinum|default:"[Describe mediastinal structures]" }}</p>
            <p><strong>Bones and Soft Tissues:</strong> {{ findings_bones|default:"[Describe osseous and soft tissue findings]" }}</p>
        </div>
    </section>
    
    <section class="impression">
        <h3>Impression:</h3>
        <p>{{ impression|default:"[Enter radiological impression and diagnosis]" }}</p>
    </section>
    
    <section class="recommendations">
        <h3>Recommendations:</h3>
        <p>{{ recommendations|default:"[Enter follow-up recommendations if applicable]" }}</p>
    </section>
</div>
                ''',
                'is_default': True
            },
            {
                'name': 'MRI Brain Template',
                'modality': 'MR',
                'body_part': 'BRAIN',
                'template_html': '''
<div class="medical-report">
    <h2>MRI Brain Report</h2>
    
    <section class="clinical-history">
        <h3>Clinical History:</h3>
        <p>{{ clinical_history|default:"[Enter clinical history and indication]" }}</p>
    </section>
    
    <section class="technique">
        <h3>Technique:</h3>
        <p>{{ technique|default:"Multiplanar MR images of the brain were obtained including T1, T2, FLAIR, and DWI sequences. Gadolinium contrast was administered." }}</p>
    </section>
    
    <section class="comparison">
        <h3>Comparison:</h3>
        <p>{{ comparison|default:"[Enter comparison studies if available]" }}</p>
    </section>
    
    <section class="findings">
        <h3>Findings:</h3>
        <div class="findings-content">
            <p><strong>Brain Parenchyma:</strong> {{ findings_parenchyma|default:"[Describe gray and white matter, ventricles]" }}</p>
            <p><strong>Extra-axial Spaces:</strong> {{ findings_extraaxial|default:"[Describe CSF spaces, meninges]" }}</p>
            <p><strong>Vascular Structures:</strong> {{ findings_vascular|default:"[Describe major vessels, flow voids]" }}</p>
            <p><strong>Posterior Fossa:</strong> {{ findings_posterior|default:"[Describe cerebellum, brainstem]" }}</p>
        </div>
    </section>
    
    <section class="impression">
        <h3>Impression:</h3>
        <p>{{ impression|default:"[Enter radiological impression and diagnosis]" }}</p>
    </section>
    
    <section class="recommendations">
        <h3>Recommendations:</h3>
        <p>{{ recommendations|default:"[Enter follow-up recommendations if applicable]" }}</p>
    </section>
</div>
                ''',
                'is_default': True
            },
            {
                'name': 'X-Ray Chest Template',
                'modality': 'CR',
                'body_part': 'CHEST',
                'template_html': '''
<div class="medical-report">
    <h2>Chest X-Ray Report</h2>
    
    <section class="clinical-history">
        <h3>Clinical History:</h3>
        <p>{{ clinical_history|default:"[Enter clinical history and indication]" }}</p>
    </section>
    
    <section class="technique">
        <h3>Technique:</h3>
        <p>{{ technique|default:"PA and lateral chest radiographs were obtained." }}</p>
    </section>
    
    <section class="comparison">
        <h3>Comparison:</h3>
        <p>{{ comparison|default:"[Enter comparison studies if available]" }}</p>
    </section>
    
    <section class="findings">
        <h3>Findings:</h3>
        <div class="findings-content">
            <p><strong>Lungs:</strong> {{ findings_lungs|default:"[Describe lung fields, airways, pleura]" }}</p>
            <p><strong>Heart and Mediastinum:</strong> {{ findings_heart|default:"[Describe cardiac silhouette, mediastinal contours]" }}</p>
            <p><strong>Bones and Soft Tissues:</strong> {{ findings_bones|default:"[Describe visible osseous structures]" }}</p>
        </div>
    </section>
    
    <section class="impression">
        <h3>Impression:</h3>
        <p>{{ impression|default:"[Enter radiological impression and diagnosis]" }}</p>
    </section>
    
    <section class="recommendations">
        <h3>Recommendations:</h3>
        <p>{{ recommendations|default:"[Enter follow-up recommendations if applicable]" }}</p>
    </section>
</div>
                ''',
                'is_default': True
            },
            {
                'name': 'CT Abdomen Pelvis Template',
                'modality': 'CT',
                'body_part': 'ABDOMEN',
                'template_html': '''
<div class="medical-report">
    <h2>CT Abdomen and Pelvis Report</h2>
    
    <section class="clinical-history">
        <h3>Clinical History:</h3>
        <p>{{ clinical_history|default:"[Enter clinical history and indication]" }}</p>
    </section>
    
    <section class="technique">
        <h3>Technique:</h3>
        <p>{{ technique|default:"Axial CT images of the abdomen and pelvis were obtained with oral and intravenous contrast." }}</p>
    </section>
    
    <section class="comparison">
        <h3>Comparison:</h3>
        <p>{{ comparison|default:"[Enter comparison studies if available]" }}</p>
    </section>
    
    <section class="findings">
        <h3>Findings:</h3>
        <div class="findings-content">
            <p><strong>Liver:</strong> {{ findings_liver|default:"[Describe hepatic parenchyma, lesions]" }}</p>
            <p><strong>Gallbladder and Biliary Tree:</strong> {{ findings_gallbladder|default:"[Describe gallbladder, bile ducts]" }}</p>
            <p><strong>Pancreas:</strong> {{ findings_pancreas|default:"[Describe pancreatic parenchyma]" }}</p>
            <p><strong>Spleen:</strong> {{ findings_spleen|default:"[Describe splenic appearance]" }}</p>
            <p><strong>Kidneys and Adrenals:</strong> {{ findings_kidneys|default:"[Describe renal and adrenal findings]" }}</p>
            <p><strong>Bowel and Mesentery:</strong> {{ findings_bowel|default:"[Describe bowel loops, mesentery]" }}</p>
            <p><strong>Pelvis:</strong> {{ findings_pelvis|default:"[Describe pelvic organs, lymph nodes]" }}</p>
            <p><strong>Bones and Soft Tissues:</strong> {{ findings_bones|default:"[Describe osseous structures]" }}</p>
        </div>
    </section>
    
    <section class="impression">
        <h3>Impression:</h3>
        <p>{{ impression|default:"[Enter radiological impression and diagnosis]" }}</p>
    </section>
    
    <section class="recommendations">
        <h3>Recommendations:</h3>
        <p>{{ recommendations|default:"[Enter follow-up recommendations if applicable]" }}</p>
    </section>
</div>
                ''',
                'is_default': True
            }
        ]

        created_count = 0
        for template_data in templates:
            template, created = ReportTemplate.objects.get_or_create(
                name=template_data['name'],
                modality=template_data['modality'],
                body_part=template_data['body_part'],
                defaults={
                    'template_html': template_data['template_html'],
                    'is_default': template_data['is_default'],
                    'is_active': True
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'✅ Created template: {template.name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'⚠️  Template already exists: {template.name}')
                )

        self.stdout.write(
            self.style.SUCCESS(f'\n🎉 Report template setup completed!')
        )
        self.stdout.write(
            self.style.SUCCESS(f'📊 Created {created_count} new templates')
        )
        self.stdout.write(
            self.style.SUCCESS(f'📝 Total templates available: {ReportTemplate.objects.count()}')
        )
        
        self.stdout.write('\n' + '='*50)
        self.stdout.write('🏥 RADIOLOGIST REPORTING SYSTEM READY')
        self.stdout.write('='*50)
        self.stdout.write('Features available:')
        self.stdout.write('• Professional report templates for all modalities')
        self.stdout.write('• Structured reporting with predefined sections')
        self.stdout.write('• Digital signature and approval workflow')
        self.stdout.write('• PDF and DOCX export capabilities')
        self.stdout.write('• Integration with DICOM viewer')
        self.stdout.write('• Audit trail and version control')
        self.stdout.write('='*50)