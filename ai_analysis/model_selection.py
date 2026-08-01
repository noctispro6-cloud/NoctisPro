"""
Body-part-aware AI model routing.

Auto-triggered analysis (on upload, and the notification-signal trigger) used
to filter candidate AIModel rows by `modality` only. Since several models in
the seed catalogue (ai_analysis/management/commands/setup_ai_models.py) share
a modality but target different anatomy -- e.g. Chest X-Ray Classifier and
Pediatric CXR Classifier are both modality='CR' -- a study of any body part
sharing that modality (a foot X-ray, say) would still get queued against a
chest-specific model just because nothing checked body part.

This maps a study's actual body region (detected from DICOM/study metadata,
reusing the same region-keyword engine the report generator already uses) onto
the coarse AIModel.body_part taxonomy from the seed catalogue, so only models
trained for that body part -- plus body-part-agnostic ones like the report
generators and the quality assessor (body_part='') -- are ever candidates.
Regions with no dedicated model yet (e.g. foot, wrist, shoulder) fall back to
body-part-agnostic models only, never to an unrelated specific one.
"""
from __future__ import annotations

from django.db.models import Q, QuerySet

from ai_analysis.llm_reporting import _identify_study_type

# Fine-grained body_region keys (see llm_reporting._REGION_KEYWORDS) mapped to
# the coarse AIModel.body_part values used by the seed catalogue. Regions with
# no entry here have no dedicated model -- only body-part-agnostic models
# (body_part='') should run for them.
_REGION_TO_AI_BODY_PART = {
    'chest': 'CHEST', 'chest_pe': 'CHEST', 'cardiac': 'CHEST', 'aorta': 'CHEST',
    'brain': 'BRAIN', 'head': 'BRAIN',
    'abdomen': 'ABDOMEN', 'abdomen_pelvis': 'ABDOMEN', 'liver': 'ABDOMEN',
    'pancreas': 'ABDOMEN', 'kidney': 'ABDOMEN', 'adrenal': 'ABDOMEN',
    'bowel': 'ABDOMEN', 'stomach': 'ABDOMEN',
    'spine': 'SPINE', 'cervical_spine': 'SPINE', 'thoracic_spine': 'SPINE',
    'lumbar_spine': 'SPINE', 'sacrum_coccyx': 'SPINE',
    'knee': 'KNEE',
    'pelvis': 'PELVIS', 'prostate': 'PELVIS', 'uterus_ovary': 'PELVIS', 'bladder': 'PELVIS',
}


def detect_ai_body_part(study) -> str:
    """
    Return the coarse AIModel.body_part value (e.g. 'CHEST', 'KNEE') this
    study's actual anatomy maps to, or '' if there's no dedicated model for
    that region.
    """
    try:
        modality_code = getattr(study.modality, 'code', '') or ''
        series_descriptions = list(
            study.series_set.exclude(series_description='')
            .values_list('series_description', flat=True)[:5]
        )
        result = _identify_study_type(
            modality=str(modality_code),
            body_part=study.body_part or '',
            study_description=study.study_description or '',
            series_descriptions=series_descriptions,
            clinical_info=study.clinical_info or '',
        )
        return _REGION_TO_AI_BODY_PART.get(result.get('body_region', ''), '')
    except Exception:
        return ''


def filter_models_for_study(queryset: QuerySet, study) -> QuerySet:
    """
    Narrow an AIModel queryset (already filtered by modality) down to models
    matching this study's specific body part, so e.g. a foot X-ray never
    triggers the Chest X-Ray Classifier just because both are modality=CR.

    Body-part-agnostic models (body_part='', e.g. report generators, the
    quality assessor) always stay eligible regardless of detected region.
    """
    detected = detect_ai_body_part(study)
    if detected:
        return queryset.filter(Q(body_part=detected) | Q(body_part=''))
    # No dedicated model for this region -- only generic ones apply.
    return queryset.filter(body_part='')
