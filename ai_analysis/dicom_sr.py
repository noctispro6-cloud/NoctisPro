import logging
import datetime
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
from highdicom.sr import (
    Comprehensive3DSR,
    PlanarROIMeasurementsAndQualitativeEvaluations,
    MeasurementReport,
    TextContentItem,
    CodeContentItem,
    ContainerContentItem,
    ObservationContext,
    PersonObserverIdentifyingAttributes,
    DeviceObserverIdentifyingAttributes,
    CodingSchemeIdentification,
)
from highdicom import (
    UID,
    CodedConcept,
)

logger = logging.getLogger(__name__)

def create_ai_findings_sr(analysis, ai_model, study_dataset=None):
    """
    Create a DICOM Structured Report (SR) from AI analysis results.
    """
    try:
        # Define codes
        # In production, these should be standard SNOMED-CT or DCM codes
        procedure_reported_code = CodedConcept(
            value="11528-7",
            meaning="Radiology Report",
            scheme_designator="LN"
        )
        
        # Observer Context (The AI Model)
        observer_context = ObservationContext(
            observer_person_context=None,
            observer_device_context=DeviceObserverIdentifyingAttributes(
                uid=generate_uid(),
                manufacturer="Noctis Pro",
                model_name=ai_model.name,
                device_serial_number=f"{ai_model.id}-{ai_model.version}"
            )
        )

        # Content Tree
        finding_text = analysis.findings or "No findings"
        
        findings_item = TextContentItem(
            name=CodedConcept(value="121071", meaning="Findings", scheme_designator="DCM"),
            value=finding_text,
            relationship_type="CONTAINS"
        )
        
        impression_text = "AI Analysis Complete"
        if analysis.abnormalities_detected:
            impression_text = f"Abnormalities detected: {len(analysis.abnormalities_detected)}"
            
        impression_item = TextContentItem(
            name=CodedConcept(value="121073", meaning="Impression", scheme_designator="DCM"),
            value=impression_text,
            relationship_type="CONTAINS"
        )
        
        # Probability/Confidence
        confidence = analysis.confidence_score or 0.0
        confidence_item = TextContentItem(
            name=CodedConcept(value="PROB", meaning="Probability", scheme_designator="99NOCTIS"),
            value=f"{confidence:.2f}",
            relationship_type="CONTAINS"
        )

        # Create Report
        # If we have the original study dataset, we copy patient/study module
        # Otherwise we need to construct it from DB (harder to make valid DICOM)
        
        if study_dataset:
            sr_dataset = MeasurementReport(
                observation_context=observer_context,
                procedure_reported=procedure_reported_code,
                imaging_measurements=[findings_item, impression_item, confidence_item],
                # Patient/Study Module copied from study_dataset
                patient_name=study_dataset.PatientName,
                patient_id=study_dataset.PatientId,
                patient_sex=getattr(study_dataset, 'PatientSex', 'O'),
                patient_birth_date=getattr(study_dataset, 'PatientBirthDate', None),
                study_instance_uid=study_dataset.StudyInstanceUID,
                accession_number=getattr(study_dataset, 'AccessionNumber', None),
                study_id=getattr(study_dataset, 'StudyID', None),
                study_date=getattr(study_dataset, 'StudyDate', None),
                study_time=getattr(study_dataset, 'StudyTime', None),
                referring_physician_name=getattr(study_dataset, 'ReferringPhysicianName', None),
            )
            return sr_dataset
        else:
            logger.warning("No reference study dataset provided for SR creation.")
            return None

    except Exception as e:
        logger.error(f"Failed to create DICOM SR: {e}")
        return None
