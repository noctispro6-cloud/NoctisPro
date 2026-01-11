import json
import re
import requests
import hashlib
import time
import logging
from django.db.models import Q
from django.utils import timezone
from worklist.models import Study
from .models import AIAnalysis

try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
except Exception:
    AutoTokenizer = None
    AutoModelForSequenceClassification = None

logger = logging.getLogger(__name__)

# Comprehensive medical book references with topic mapping
MEDICAL_BOOK_REFERENCES = {
    'general': {
        'default': [
            {'title': "Brant & Helms – Fundamentals of Diagnostic Radiology", 'topic': 'General Principles'},
            {'title': "Grainger & Allison’s Diagnostic Radiology", 'topic': 'General Interpretation'},
        ]
    },
    'neuroradiology': {
        'stroke': [
            {'title': "Osborn’s Brain: Imaging, Pathology, and Anatomy", 'topic': 'Chapter 4: Vascular Disorders'},
            {'title': "Neuroradiology: The Requisites", 'topic': 'Stroke & Ischemia'},
        ],
        'hemorrhage': [
            {'title': "Osborn’s Brain", 'topic': 'Chapter 2: Intracranial Hemorrhage'},
            {'title': "Neuroradiology: The Requisites", 'topic': 'Trauma & Hemorrhage'},
        ],
        'tumor': [
            {'title': "Osborn’s Brain", 'topic': 'Chapter 12: Primary Brain Tumors'},
        ],
        'mass': [
            {'title': "Osborn’s Brain", 'topic': 'Chapter 1: Approach to Masses'},
        ],
        'default': [
            {'title': "Osborn’s Brain", 'topic': 'General Brain Imaging'},
        ]
    },
    'chest': {
        'pneumonia': [
            {'title': "Felson’s Principles of Chest Roentgenology", 'topic': 'Airspace Disease'},
            {'title': "Thoracic Imaging (Webb)", 'topic': 'Infection'},
        ],
        'pneumothorax': [
            {'title': "Felson’s Principles of Chest Roentgenology", 'topic': 'Pleural Disease'},
        ],
        'default': [
            {'title': "Felson’s Principles of Chest Roentgenology", 'topic': 'Chest Basics'},
        ]
    },
    'msk': {
        'fracture': [
            {'title': "Resnick’s Diagnosis of Bone and Joint Disorders", 'topic': 'Trauma & Fractures'},
        ],
        'default': [
            {'title': "Musculoskeletal MRI (Helms)", 'topic': 'General MSK'},
        ]
    },
    'emergency': {
        'default': [
            {'title': "Harris & Harris’ The Radiology of Emergency Medicine", 'topic': 'Trauma Overview'},
        ]
    }
}

_PRIORITY_RANK = {'low': 0, 'normal': 1, 'high': 2, 'urgent': 3}

def _get_online_references(keywords, max_results=3):
    """
    Search for high-quality online references for approved users.
    Returns a list of dicts: {'title': str, 'url': str, 'source': str}
    """
    if not keywords:
        return []
    
    # Clean keywords for search
    search_query = " ".join(keywords[:3]) # Limit query length
    
    # Sources to prioritize
    sources = [
        'site:radiopaedia.org',
        'site:ncbi.nlm.nih.gov', # PubMed / PMC
        'site:merckmanuals.com/professional',
    ]
    
    full_query = f"{search_query} ({' OR '.join(sources)})"
    
    try:
        # Use DuckDuckGo HTML scrape (no API key needed, respectful of rate limits)
        ddg_url = 'https://duckduckgo.com/html/'
        params = {'q': full_query}
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; NoctisPro/1.0; +https://example.com)'}
        
        resp = requests.post(ddg_url, data=params, headers=headers, timeout=5)
        
        results = []
        if resp.ok:
            for m in re.finditer(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.I | re.S):
                url = m.group(1)
                title_raw = re.sub('<[^<]+?>', '', m.group(2))
                title = re.sub(r'\s+', ' ', title_raw).strip()
                
                # Determine source label
                source_label = 'Web'
                if 'radiopaedia.org' in url: source_label = 'Radiopaedia'
                elif 'ncbi.nlm.nih.gov' in url: source_label = 'PubMed/NCBI'
                elif 'merckmanuals' in url: source_label = 'Merck Manual'
                
                if url and title:
                    results.append({'title': title, 'url': url, 'source': source_label})
                
                if len(results) >= max_results:
                    break
        return results
    except Exception:
        # Fail gracefully
        return []

def _normalize_abnormality_label(item) -> str:
    """Best-effort normalization for abnormality entries (dicts/strings)."""
    try:
        if isinstance(item, dict):
            for key in ('label', 'type', 'name', 'finding'):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
            return json.dumps(item, sort_keys=True)
        return str(item).strip()
    except Exception:
        return ''

def _compute_ai_triage(abnormalities, confidence: float) -> dict:
    """
    Compute a triage level + score from AI outputs.
    This is intentionally conservative: it upgrades but never auto-downgrades a study.
    """
    conf = float(confidence or 0.0)
    labels = [(_normalize_abnormality_label(a) or '').lower() for a in (abnormalities or [])]
    labels = [l for l in labels if l]

    # "Urgent" keywords: conditions where expedited review is typically warranted.
    urgent_keywords = (
        'intracranial hemorrhage', 'hemorrhage', 'ich', 'stroke', 'infarct',
        'pneumothorax', 'tension pneumothorax', 'pulmonary embolism', 'embolism',
        'aortic dissection', 'free air', 'perforation'
    )
    # "High" keywords: important findings that should be prioritized but may be less immediately time-critical.
    high_keywords = (
        'fracture', 'consolidation', 'pneumonia', 'large effusion', 'mass', 'tumor',
        'significant stenosis'
    )
    # Trauma heuristics: treat explicit trauma mechanisms/contexts as higher urgency.
    trauma_context_keywords = (
        'trauma', 'mvc', 'rt a', 'rta', 'fall', 'assault', 'gunshot', 'stab', 'blunt', 'polytrauma'
    )
    trauma_finding_keywords = (
        'fracture', 'dislocation', 'hemorrhage', 'bleed', 'laceration',
        'pneumothorax', 'hemothorax', 'contusion', 'solid organ injury', 'free fluid'
    )

    max_hint = 'normal'
    reason = 'no_abnormalities'
    if any(any(k in l for k in urgent_keywords) for l in labels):
        max_hint = 'urgent'
        reason = 'urgent_keyword'
    elif any(any(k in l for k in trauma_finding_keywords) for l in labels) and (
        any(any(k in l for k in trauma_context_keywords) for l in labels)
    ):
        # If a model explicitly emits trauma context + trauma finding, treat as urgent.
        max_hint = 'urgent'
        reason = 'trauma_keyword'
    elif any(any(k in l for k in high_keywords) for l in labels):
        max_hint = 'high'
        reason = 'high_keyword'
    elif labels:
        max_hint = 'normal'
        reason = 'abnormality_present'

    base = {'low': 0.15, 'normal': 0.35, 'high': 0.70, 'urgent': 1.0}.get(max_hint, 0.35)
    score = min(1.0, (base * 0.6) + (conf * 0.4))

    if max_hint == 'urgent' or score >= 0.85:
        level = 'urgent'
    elif max_hint == 'high' or score >= 0.65:
        level = 'high'
    elif score <= 0.25 and not labels:
        level = 'low'
    else:
        level = 'normal'

    flagged = level in ('high', 'urgent') and conf >= 0.55
    return {
        'triage_level': level,
        'triage_score': round(score, 3),
        'flagged': bool(flagged),
        'reason': reason,
        'abnormalities_count': len(labels),
    }

def _upgrade_study_priority(study: Study, new_priority: str) -> bool:
    """Upgrade the study priority if the new priority is more severe."""
    try:
        cur = (study.priority or 'normal').lower()
        nxt = (new_priority or 'normal').lower()
        if _PRIORITY_RANK.get(nxt, 1) > _PRIORITY_RANK.get(cur, 1):
            study.priority = nxt
            study.save(update_fields=['priority', 'last_updated'])
            return True
        return False
    except Exception:
        return False

def _notify_ai_triage(analysis: AIAnalysis, triage: dict) -> None:
    """Create a notification for radiologists/admins when AI upgrades triage."""
    try:
        from notifications.models import Notification, NotificationType
        from notifications.models import NotificationPreference
        from notifications import services as notify_services
        from accounts.models import User

        study = analysis.study
        facility = getattr(study, 'facility', None)
        triage_level = triage.get('triage_level', 'normal')
        triage_score = triage.get('triage_score', 0)

        notif_type, _ = NotificationType.objects.get_or_create(
            code='ai_triage',
            defaults={
                'name': 'AI Triage Flag',
                'description': 'AI flagged a study for priority review',
                'is_system': True,
                'default_priority': 'high',
            },
        )

        # Prefer notifying the assigned radiologist (if any). Otherwise notify facility radiologists + admins.
        assigned = getattr(study, "radiologist", None)
        if assigned:
            recipients = User.objects.filter(id=assigned.id)
        else:
            recipients = User.objects.filter(Q(role='radiologist') | Q(role='admin'))
            if facility:
                recipients = recipients.filter(Q(role='admin') | Q(facility=facility))

        title = f"AI flagged study {study.accession_number} ({triage_level.upper()})"
        msg = (
            f"AI triage level: {triage_level.upper()} (score {triage_score}). "
            f"Please review the study promptly. Findings: {analysis.findings[:200]}"
        )
        
        # Add references if present in analysis measurements
        if analysis.measurements and 'reference_suggestions' in analysis.measurements:
            refs = analysis.measurements['reference_suggestions']
            if refs:
                # Simplify to title + topic for SMS/Notification brevity
                ref_texts = [f"{r.get('title')} ({r.get('topic')})" for r in refs if isinstance(r, dict)]
                if not ref_texts: # Fallback if old format
                    ref_texts = [r for r in refs if isinstance(r, str)]
                msg += " | Refs: " + "; ".join(ref_texts[:2])

        action_url = f"/worklist/study/{study.id}/"
        # Dedupe key prevents duplicate alerts per recipient/triage level.
        dedupe_key = f"ai_triage:{study.id}:{analysis.id}:{triage_level}"
        
        for recipient in recipients:
            # Check for offline status (last_login > 15 mins ago or None)
            is_offline = True
            if recipient.last_login:
                if (timezone.now() - recipient.last_login).total_seconds() < 900:
                    is_offline = False
            
            # Avoid duplicating the same alert repeatedly.
            if Notification.objects.filter(
                recipient=recipient,
                notification_type=notif_type,
                data__dedupe_key=dedupe_key,
            ).exists():
                continue

            notif = Notification.objects.create(
                notification_type=notif_type,
                recipient=recipient,
                sender=None,
                title=title,
                message=msg,
                priority=triage_level if triage_level in _PRIORITY_RANK else 'high',
                study=study,
                facility=facility,
                action_url=action_url,
                data={
                    'study_id': study.id,
                    'analysis_id': analysis.id,
                    'triage': triage,
                    'dedupe_key': dedupe_key,
                },
            )

            # Notification Logic based on Urgency and Presence
            should_notify_out_of_band = False
            if triage_level == 'urgent':
                should_notify_out_of_band = True
            elif triage_level == 'high' and is_offline:
                should_notify_out_of_band = True

            if should_notify_out_of_band:
                try:
                    pref = NotificationPreference.objects.filter(user=recipient).first()
                    # Default to SMS if not specified for urgent alerts
                    method = (getattr(pref, 'preferred_method', None) or 'sms').lower()
                    if method == 'web': 
                        method = 'sms' # Force SMS for urgent offline alerts if web was default
                    
                    to_number = (getattr(recipient, 'phone', None) or '').strip()
                    if not to_number:
                        continue
                        
                    if method == 'sms':
                        notify_services.send_sms(
                            to_number,
                            f"[CRITICAL] {title}. Open: {action_url}",
                        )
                    elif method == 'call':
                        notify_services.place_call(
                            to_number,
                            f"Critical AI alert. {title}. Please log in to review immediately.",
                        )
                except Exception:
                    # Best-effort only: web notification remains
                    pass
    except Exception:
        # Best-effort only
        return

def _apply_ai_triage(analysis: AIAnalysis) -> None:
    """
    Persist triage info to the analysis, upgrade Study.priority if needed,
    and notify radiologists/admins on upgrade.
    """
    triage = _compute_ai_triage(analysis.abnormalities_detected, analysis.confidence_score or 0.0)

    # Persist triage metadata on the analysis (no schema changes required).
    try:
        measurements = analysis.measurements or {}
        if not isinstance(measurements, dict):
            measurements = {}
        measurements.update({
            'triage_level': triage.get('triage_level'),
            'triage_score': triage.get('triage_score'),
            'triage_flagged': triage.get('flagged'),
            'triage_reason': triage.get('reason'),
        })
        
        # Persist reference suggestions based on modality/body part and findings
        try:
            suggested_refs = []
            
            # Helper to add refs
            def add_refs_for_key(category, key):
                if category in MEDICAL_BOOK_REFERENCES and key in MEDICAL_BOOK_REFERENCES[category]:
                    suggested_refs.extend(MEDICAL_BOOK_REFERENCES[category][key])
            
            # Add modality specific references
            modality = analysis.study.modality.code
            
            # Analyze findings/labels for keywords to match topics
            labels = [(_normalize_abnormality_label(a) or '').lower() for a in (analysis.abnormalities_detected or [])]
            finding_text = (analysis.findings or '').lower()
            
            # --- NEURORADIOLOGY ---
            if modality in ['CT', 'MR'] and ('brain' in str(analysis.study.body_part).lower() or 'head' in str(analysis.study.body_part).lower()):
                add_refs_for_key('neuroradiology', 'default')
                if any('stroke' in l for l in labels) or 'stroke' in finding_text:
                     add_refs_for_key('neuroradiology', 'stroke')
                if any('hemorrhage' in l for l in labels) or 'bleed' in finding_text:
                     add_refs_for_key('neuroradiology', 'hemorrhage')
                if any('tumor' in l for l in labels) or 'mass' in finding_text:
                     add_refs_for_key('neuroradiology', 'tumor')
            
            # --- CHEST ---
            elif modality in ['CT', 'XR', 'CR'] and ('chest' in str(analysis.study.body_part).lower() or 'lung' in str(analysis.study.body_part).lower()):
                 add_refs_for_key('chest', 'default')
                 if any('pneumonia' in l for l in labels) or 'consolidation' in finding_text:
                      add_refs_for_key('chest', 'pneumonia')
                 if any('pneumothorax' in l for l in labels):
                      add_refs_for_key('chest', 'pneumothorax')

            # --- MSK ---
            elif 'knee' in str(analysis.study.body_part).lower() or 'spine' in str(analysis.study.body_part).lower() or 'shoulder' in str(analysis.study.body_part).lower():
                add_refs_for_key('msk', 'default')
                if any('fracture' in l for l in labels):
                    add_refs_for_key('msk', 'fracture')
            
            else:
                 add_refs_for_key('general', 'default')

            # Add emergency references if urgent
            if triage.get('triage_level') == 'urgent':
                add_refs_for_key('emergency', 'default')
                
            # Limit to unique entries (dedupe by title+topic)
            seen = set()
            unique_suggested_refs = []
            for r in suggested_refs:
                key = f"{r['title']}:{r['topic']}"
                if key not in seen:
                    seen.add(key)
                    unique_suggested_refs.append(r)

            measurements['reference_suggestions'] = unique_suggested_refs
            
        except Exception:
            pass
            
        analysis.measurements = measurements
        analysis.save(update_fields=['measurements'])
    except Exception:
        pass

    # Upgrade study priority and notify if we actually upgraded.
    upgraded = _upgrade_study_priority(analysis.study, triage.get('triage_level', 'normal'))
    if upgraded and triage.get('flagged'):
        _notify_ai_triage(analysis, triage)

def simulate_ai_analysis(analysis):
    """Heavier inference if available; otherwise safe simulation."""
    modality = analysis.study.modality.code
    # Heavier text classification demo for AI summary confidence, if transformers available
    confidence = 0.85
    if AutoTokenizer and AutoModelForSequenceClassification:
        try:
            # Lightweight sentiment-like proxy to modulate confidence
            model_name = 'distilbert-base-uncased-finetuned-sst-2-english'
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForSequenceClassification.from_pretrained(model_name)
            text = f"Preliminary {modality} analysis"
            inputs = tokenizer(text, return_tensors='pt')
            outputs = model(**inputs)
            scores = outputs.logits.softmax(dim=-1).detach().numpy()[0]
            confidence = float(scores.max()) * 0.2 + 0.8  # keep range ~0.8-1.0
        except Exception:
            confidence = 0.88
    # Optional ONNX path could go here for imaging if an .onnx exists; skip unless file provided
    time.sleep(2)

    # Deterministic “demo triage” abnormalities for smoke/demo environments.
    # Real deployments should replace this with actual model inference outputs.
    acc = (getattr(analysis.study, 'accession_number', '') or '').encode('utf-8')
    h = int(hashlib.md5(acc or b'0').hexdigest(), 16)
    clin = (getattr(analysis.study, 'clinical_info', '') or '').lower()

    if modality == 'CT':
        findings = "No acute intracranial abnormality. Brain parenchyma appears normal."
        abnormalities = []
        if 'trauma' in clin or 'fall' in clin or 'mvc' in clin or (h % 20 == 4):
            abnormalities = [{'label': 'Trauma context', 'severity_hint': 'urgent'}, {'label': 'Skull fracture suspicion', 'severity_hint': 'urgent'}]
            findings = "Trauma context with possible skull fracture; urgent review recommended."
        elif 'stroke' in clin or (h % 20 == 1):
            abnormalities = [{'label': 'Ischemic stroke suspicion', 'severity_hint': 'urgent'}]
            findings = "Findings suspicious for acute ischemic stroke; urgent clinical correlation recommended."
        elif 'hemorrhage' in clin or (h % 20 == 0):
            abnormalities = [{'label': 'Intracranial hemorrhage suspicion', 'severity_hint': 'urgent'}]
            findings = "Possible intracranial hemorrhage; urgent review recommended."
        elif 'mass' in clin or 'tumor' in clin or (h % 20 == 5):
            abnormalities = [{'label': 'Intracranial mass/lesion suspicion', 'severity_hint': 'high'}]
            findings = "Possible intracranial mass/lesion; recommend expedited review and correlation."
        elif (h % 20 == 2):
            abnormalities = [{'label': 'Mass effect / edema suspicion', 'severity_hint': 'high'}]
            findings = "Possible mass effect/edema; recommend expedited review."
        measurements = {"brain_volume": "1450 mL", "ventricle_size": "normal"}
    elif modality == 'MR':
        findings = "Normal brain MRI. No evidence of acute infarction or hemorrhage."
        abnormalities = []
        if 'ms' in clin or (h % 25 == 3):
            abnormalities = [{'label': 'Demyelinating lesions suspicion', 'severity_hint': 'high'}]
            findings = "Possible demyelinating lesions; correlate clinically and review sequences."
        measurements = {"lesion_count": 0, "white_matter": "normal"}
    elif modality == 'XR':
        findings = "Chest X-ray shows clear lungs. Heart size is normal."
        abnormalities = []
        if 'pneumothorax' in clin or (h % 15 == 0):
            abnormalities = [{'label': 'Pneumothorax suspicion', 'severity_hint': 'urgent'}]
            findings = "Possible pneumothorax; urgent review recommended."
        elif 'pneumonia' in clin or (h % 15 == 1):
            abnormalities = [{'label': 'Pneumonia / consolidation suspicion', 'severity_hint': 'high'}]
            findings = "Possible consolidation/pneumonia; recommend review."
        measurements = {"heart_size": "normal", "lung_fields": "clear"}
    else:
        findings = "Study reviewed by AI. No acute abnormalities detected."
        abnormalities = []
        measurements = {}

    # Calibrate confidence for demo cases.
    if abnormalities:
        confidence = 0.75 + ((h % 23) / 100.0)  # ~0.75-0.98
    else:
        confidence = min(confidence, 0.9)

    return {
        'findings': findings,
        'abnormalities': abnormalities,
        'confidence': confidence,
        'measurements': measurements
    }
