"""
LLM-based radiology report generation for Noctis Pro PACS.

Supports three backends in priority order:
1. External API (OpenAI-compatible) — set AI_REPORT_API_URL + AI_REPORT_API_KEY env vars
2. Local transformers model — auto-downloads a small instruction-tuned model on first use
3. Deterministic fallback — always available, no dependencies beyond existing stack

Configuration (via settings or environment):
    AI_REPORT_API_URL    — Base URL for OpenAI-compatible API (e.g. https://api.openai.com/v1)
    AI_REPORT_API_KEY    — API key for the external service
    AI_REPORT_MODEL      — Model name for API calls (default: gpt-3.5-turbo)
    AI_LOCAL_MODEL       — HuggingFace model ID for local inference
                           (default: google/flan-t5-base — 250MB, CPU-friendly)
    AI_REPORT_MAX_TOKENS — Max tokens for generated report sections (default: 300)
    AI_REPORT_TIMEOUT    — Timeout in seconds for API calls (default: 30)
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ai_analysis")

_model_lock = threading.Lock()
_local_pipeline = None
_local_pipeline_error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Settings helpers
# ─────────────────────────────────────────────────────────────────────────────

def _setting(name: str, default: str = "") -> str:
    try:
        from django.conf import settings
        return str(getattr(settings, name, "") or os.environ.get(name, default) or default)
    except Exception:
        return str(os.environ.get(name, default) or default)


# ─────────────────────────────────────────────────────────────────────────────
# Study-type identification
# ─────────────────────────────────────────────────────────────────────────────

# Body-region keyword groups (order matters — more specific first)
_REGION_KEYWORDS: List[tuple] = [
    # Neuro / Head
    ("brain",           ["brain", "cerebr", "intracrani", "cranial"]),
    ("head",            ["head", "skull", "calvari"]),
    ("pituitary",       ["pituitary", "sella", "sellar"]),
    ("orbit",           ["orbit", "orbital", "ocular", "eye"]),
    ("iac",             ["iac", "internal auditory canal", "temporal bone"]),
    ("paranasal_sinus", ["sinus", "paranasal", "maxillary", "ethmoid", "frontal sinus", "sphenoid sinus"]),
    ("face",            ["face", "facial", "mandible", "maxilla", "zygoma"]),
    ("neck",            ["neck", "throat", "larynx", "pharynx", "thyroid", "salivary"]),
    # Spine
    ("cervical_spine",  ["c-spine", "c spine", "cervical spine", "cervical cord"]),
    ("thoracic_spine",  ["t-spine", "t spine", "thoracic spine"]),
    ("lumbar_spine",    ["l-spine", "l spine", "lumbar spine", "lumbosacral", "lumbar"]),
    ("sacrum_coccyx",   ["sacrum", "coccyx", "sacral", "sacrococcygeal"]),
    ("spine",           ["spine", "spinal", "vertebr", "cord", "disc", "discal", "foramina"]),
    # Thorax / Chest
    ("cardiac",         ["cardiac", "heart", "coronary", "coronaries", "pericardi", "aortic valve",
                          "mitral", "tricuspid", "pulmonary valve", "ventricular"]),
    ("aorta",           ["aorta", "aortic", "aorto"]),
    ("chest_pe",        ["pe protocol", "pulmonary embolism", "ctpa", "ct pulmonary angiogram"]),
    ("chest",           ["chest", "thorax", "thoracic", "lung", "pulmonary", "pleural",
                          "mediastin", "trachea", "bronch", "rib", "sternum", "pectoral"]),
    # Abdomen / GI
    ("liver",           ["liver", "hepatic", "hepat"]),
    ("pancreas",        ["pancrea"]),
    ("kidney",          ["kidney", "renal", "nephro"]),
    ("adrenal",         ["adrenal", "suprarenal"]),
    ("bowel",           ["bowel", "colon", "rectal", "rectum", "sigmoid", "ileum", "jejunum", "duodenum",
                          "small bowel", "large bowel", "intestin"]),
    ("stomach",         ["stomach", "gastric", "gastro"]),
    ("abdomen_pelvis",  ["abdomen and pelvis", "ab/pelvis", "a/p", "abdominal pelvis"]),
    ("abdomen",         ["abdomen", "abdominal", "peritoneal", "retroperitoneal", "spleen", "splenic"]),
    # Pelvis / GU
    ("prostate",        ["prostate", "prostatic"]),
    ("uterus_ovary",    ["uterus", "uterine", "ovary", "ovarian", "endometri", "cervix uteri", "fallopian"]),
    ("bladder",         ["bladder", "vesical"]),
    ("pelvis",          ["pelvis", "pelvic", "hip", "acetabul", "sacroiliac", "si joint"]),
    # Extremities / MSK
    ("shoulder",        ["shoulder", "acromioclavicular", "glenohumeral", "rotator cuff", "scapula", "clavicle"]),
    ("elbow",           ["elbow", "cubital", "olecranon", "humerus distal"]),
    ("wrist",           ["wrist", "carpal", "distal radius", "distal ulna"]),
    ("hand_finger",     ["hand", "finger", "thumb", "metacarpal", "phalanx", "phalanges"]),
    ("upper_extremity", ["upper arm", "humerus", "forearm", "radius", "ulna", "upper limb", "upper extremity"]),
    ("knee",            ["knee", "patell", "meniscus", "menisci", "cruciate", "tibiofemoral"]),
    ("ankle",           ["ankle", "talar", "calcaneus", "calcaneal", "fibula distal", "tibia distal"]),
    ("foot",            ["foot", "metatarsal", "tarsal", "plantar", "heel", "achilles"]),
    ("lower_extremity", ["femur", "tibia", "fibula", "lower extremity", "lower limb", "thigh", "leg"]),
    ("whole_body",      ["whole body", "total body", "full body"]),
]

# Body region → clinical domain
_DOMAIN_MAP = {
    "brain": "neuro", "head": "neuro", "pituitary": "neuro", "orbit": "neuro",
    "iac": "neuro", "paranasal_sinus": "head_neck", "face": "head_neck", "neck": "head_neck",
    "cervical_spine": "spine", "thoracic_spine": "spine", "lumbar_spine": "spine",
    "sacrum_coccyx": "spine", "spine": "spine",
    "cardiac": "cardiac", "aorta": "vascular", "chest_pe": "vascular",
    "chest": "thoracic",
    "liver": "abdominal", "pancreas": "abdominal", "kidney": "abdominal",
    "adrenal": "abdominal", "bowel": "abdominal", "stomach": "abdominal",
    "abdomen_pelvis": "abdominal", "abdomen": "abdominal",
    "prostate": "pelvic", "uterus_ovary": "pelvic", "bladder": "pelvic", "pelvis": "pelvic",
    "shoulder": "msk", "elbow": "msk", "wrist": "msk", "hand_finger": "msk",
    "upper_extremity": "msk", "knee": "msk", "ankle": "msk", "foot": "msk",
    "lower_extremity": "msk", "whole_body": "oncology",
}

# Human-readable labels for body regions
_REGION_LABELS = {
    "brain": "Brain", "head": "Head", "pituitary": "Pituitary/Sella",
    "orbit": "Orbits", "iac": "Internal Auditory Canals",
    "paranasal_sinus": "Paranasal Sinuses", "face": "Face/Facial Bones", "neck": "Neck/Soft Tissues",
    "cervical_spine": "Cervical Spine", "thoracic_spine": "Thoracic Spine",
    "lumbar_spine": "Lumbar Spine", "sacrum_coccyx": "Sacrum/Coccyx", "spine": "Spine",
    "cardiac": "Cardiac", "aorta": "Aorta/Great Vessels", "chest_pe": "Chest (PE Protocol)",
    "chest": "Chest",
    "liver": "Liver", "pancreas": "Pancreas", "kidney": "Kidneys",
    "adrenal": "Adrenal Glands", "bowel": "Bowel/Colon", "stomach": "Stomach/Upper GI",
    "abdomen_pelvis": "Abdomen and Pelvis", "abdomen": "Abdomen",
    "prostate": "Prostate", "uterus_ovary": "Uterus/Ovaries", "bladder": "Bladder",
    "pelvis": "Pelvis",
    "shoulder": "Shoulder", "elbow": "Elbow", "wrist": "Wrist", "hand_finger": "Hand/Fingers",
    "upper_extremity": "Upper Extremity", "knee": "Knee", "ankle": "Ankle",
    "foot": "Foot/Ankle", "lower_extremity": "Lower Extremity",
    "whole_body": "Whole Body",
}

_MODALITY_FULL = {
    "CT": "Computed Tomography", "MR": "Magnetic Resonance Imaging",
    "CR": "Conventional Radiograph", "DX": "Digital Radiograph",
    "US": "Ultrasound", "MG": "Mammography", "PT": "PET",
    "NM": "Nuclear Medicine", "XA": "X-ray Angiography",
    "RF": "Fluoroscopy", "ECG": "Electrocardiogram", "OT": "Other",
}


def _identify_study_type(
    modality: str,
    body_part: str,
    study_description: str,
    series_descriptions: List[str],
    clinical_info: str,
    ai_model_body_part: str = "",
) -> Dict[str, Any]:
    """
    Parse all available metadata and return a structured study-type descriptor.

    Returns a dict with:
        exam_type       — short label, e.g. "CT Chest"
        modality        — normalised modality code
        modality_full   — e.g. "Computed Tomography"
        body_region     — internal region key, e.g. "chest"
        body_label      — human label, e.g. "Chest"
        clinical_domain — e.g. "thoracic", "neuro", "msk"
        laterality      — "left", "right", "bilateral", or ""
        contrast        — "with contrast", "without contrast", "with and without contrast", or ""
        protocol        — specific protocol string, e.g. "PE protocol", "MRCP", "DWIBS"
        sequences       — list of MRI sequences detected
        study_label     — full human-readable label, e.g. "CT Chest with Contrast (PE Protocol)"
        specific_hints  — list of imaging-specific guidance strings for the prompt
    """
    mod = (modality or "").upper().strip()
    combined = " ".join(filter(None, [
        body_part, study_description, ai_model_body_part,
        " ".join(series_descriptions[:5]), clinical_info
    ])).lower()

    # ── Body region detection ──────────────────────────────────────────────
    detected_region = ""
    for region_key, keywords in _REGION_KEYWORDS:
        if any(kw in combined for kw in keywords):
            detected_region = region_key
            break

    # Fallback: use raw body_part
    if not detected_region and body_part:
        bp = body_part.strip().lower()
        detected_region = bp.replace(" ", "_") if bp else ""

    body_label = _REGION_LABELS.get(detected_region, (body_part or "").title() or "Study")
    clinical_domain = _DOMAIN_MAP.get(detected_region, "general")

    # ── Laterality ────────────────────────────────────────────────────────
    laterality = ""
    if "bilateral" in combined or "both" in combined:
        laterality = "bilateral"
    elif "left" in combined or " lt " in combined:
        laterality = "left"
    elif "right" in combined or " rt " in combined:
        laterality = "right"

    # ── Contrast ─────────────────────────────────────────────────────────
    # Check "without" patterns first (they contain the word "with")
    contrast = ""
    wo = bool(re.search(r"\bwithout\b|w/o\b|non.contrast|noncontrast|unenhanced|plain\s+film|plain\s+chest", combined))
    ww = bool(re.search(r"\bwith\s+contrast\b|\bwith\s+iv\b|\bwith\s+gad\b|\bcontrast.enhanced\b|\bce\b|\bpost.contrast\b|\bwith\s+and\s+without\b", combined))
    if ww and wo:
        contrast = "with and without contrast"
    elif ww:
        contrast = "with contrast"
    elif wo:
        contrast = "without contrast"

    # ── Protocol detection ────────────────────────────────────────────────
    protocol = ""
    _protocols = [
        ("PE protocol",         ["pe protocol", "ctpa", "pulmonary angiogram", "pulmonary embolism"]),
        ("HRCT",                ["hrct", "high resolution", "high-resolution"]),
        ("Triple-phase",        ["triple phase", "triphasic", "triple-phase"]),
        ("MRCP",                ["mrcp", "cholangiopancreatography"]),
        ("MR Angiography",      ["mra", "mr angiography", "mr angio", "time of flight", "tof"]),
        ("MR Venography",       ["mrv", "mr venography"]),
        ("MR Spectroscopy",     ["spectroscopy", "mrs"]),
        ("MR Perfusion",        ["perfusion", "dsc", "dce", "asl"]),
        ("Diffusion-Weighted",  ["dwi", "diffusion", "dwibs", "adc"]),
        ("Cardiac CT",          ["calcium score", "calcium scoring", "cac", "coronary cta", "ccta"]),
        ("Arthrography",        ["arthrogram", "arthrography", "arthro"]),
        ("Enterography",        ["enterography", "enteroclysis"]),
        ("Urography",           ["urography", "pyelography", "ivu"]),
        ("Myelography",         ["myelogram", "myelography"]),
        ("Stress Test",         ["stress", "exercise"]),
        ("DEXA",                ["dexa", "bone density", "densitometry"]),
        ("Angiography",         ["angiogram", "angiography", "angio"]),
    ]
    for p_label, p_keys in _protocols:
        if any(k in combined for k in p_keys):
            protocol = p_label
            break

    # ── MRI sequences ─────────────────────────────────────────────────────
    sequences: List[str] = []
    if mod == "MR":
        _seq_map = [
            ("T1", ["t1", "t1w", "t1-weighted"]),
            ("T2", ["t2", "t2w", "t2-weighted"]),
            ("FLAIR", ["flair"]),
            ("DWI", ["dwi", "diffusion"]),
            ("ADC", ["adc"]),
            ("SWI/GRE", ["swi", "gradient echo", "gre", "susceptibility"]),
            ("STIR", ["stir"]),
            ("Gadolinium CE", ["gad", "gadolinium", "gd", "post contrast", "post-contrast", "t1 ce"]),
            ("MRA", ["mra", "angio", "tof"]),
            ("MRCP", ["mrcp"]),
        ]
        for seq_label, seq_keys in _seq_map:
            if any(k in combined for k in seq_keys):
                sequences.append(seq_label)

    # ── Study label ───────────────────────────────────────────────────────
    mod_full = _MODALITY_FULL.get(mod, mod)
    lat_str = f" {laterality.title()}" if laterality and laterality != "bilateral" else (" Bilateral" if laterality == "bilateral" else "")
    exam_type = f"{mod} {body_label}{lat_str}".strip()
    parts_label = [exam_type]
    if contrast:
        parts_label.append(contrast)
    # Only append protocol if it is not already embedded in the body_label (e.g. "Chest (PE Protocol)")
    if protocol and protocol.lower() not in body_label.lower():
        parts_label.append(f"({protocol})")
    study_label = " ".join(parts_label)

    # ── Imaging-specific guidance for prompt ──────────────────────────────
    specific_hints: List[str] = []

    # Modality-level hints
    _mod_hints = {
        "CT":  "Report Hounsfield unit attenuation values for key structures. "
               "Note density, enhancement pattern, and any calcification.",
        "MR":  "Report signal characteristics on each sequence (T1, T2, FLAIR, DWI where applicable). "
               "State whether enhancement is present and its pattern.",
        "CR":  "Use standard plain film terminology. Note cardiothoracic ratio, bone cortex, "
               "soft tissue planes, and air-space disease patterns.",
        "DX":  "Use plain film terminology. Note cortical integrity, trabecular pattern, "
               "joint space, and soft tissue swelling.",
        "US":  "Report echogenicity (hyperechoic/hypoechoic/isoechoic/anechoic), vascularity on "
               "Doppler, shadowing, and through-transmission.",
        "MG":  "Report using BI-RADS terminology. State breast composition category. "
               "Describe mass shape/margin/density and calcification morphology/distribution.",
        "PT":  "Report SUVmax values for focal lesions. Describe distribution pattern and "
               "compare to physiologic background uptake.",
        "NM":  "Describe radiotracer distribution, areas of increased or decreased uptake, "
               "and photopenic defects. Report qualitative and semi-quantitative data.",
        "XA":  "Describe vessel caliber, contour, wall irregularity, stenosis grade, and "
               "any filling defects or extravasation.",
    }
    if mod in _mod_hints:
        specific_hints.append(_mod_hints[mod])

    # Domain/region-specific hints
    _domain_hints = {
        "neuro": (
            "Evaluate the parenchyma, ventricles, sulci, cisterns, midline structures, and "
            "the posterior fossa. Note any mass effect, herniation, midline shift, or hydrocephalus. "
            "Report white matter signal changes, restricted diffusion, and vascular territories."
        ),
        "thoracic": (
            "Systematically evaluate: lung parenchyma (both upper, middle, and lower zones), "
            "pleural spaces, mediastinum, hilum, pericardium, and visible osseous structures. "
            "Note air-space disease, interstitial pattern, nodules, effusions, and pneumothorax."
        ),
        "cardiac": (
            "Report cardiac chamber size, wall thickness, pericardial effusion, "
            "coronary artery calcium score (if applicable), and great vessel morphology. "
            "Note any perfusion defects or wall motion abnormalities."
        ),
        "vascular": (
            "Describe vessel caliber, filling defects, thrombus, aneurysm, dissection flap, "
            "wall thickening, and involvement of branch vessels. Report extent and severity."
        ),
        "abdominal": (
            "Systematically evaluate all solid organs (liver, spleen, pancreas, kidneys, adrenals) "
            "and hollow viscera. Note fat stranding, free fluid, lymphadenopathy, and vascular structures. "
            "Report organ size, density/signal, and any focal lesions with location, size, and character."
        ),
        "pelvic": (
            "Evaluate pelvic organs, pelvic floor, lymph nodes, and bony pelvis. "
            "Note any adnexal, uterine, prostatic, or bladder abnormalities. "
            "Report size, morphology, signal/density, and enhancement pattern of lesions."
        ),
        "msk": (
            "Systematically evaluate bone cortex, medullary cavity, articular cartilage, "
            "joint space, ligaments, tendons, and periarticular soft tissues. "
            "Report fracture lines, bone marrow signal, and any soft tissue abnormality."
        ),
        "spine": (
            "Evaluate vertebral body height, alignment, disc height, endplates, "
            "spinal canal diameter, neural foramina, and cord/conus signal. "
            "Note any disc herniation, spinal stenosis, nerve root compression, or marrow signal change."
        ),
        "head_neck": (
            "Evaluate all anatomical compartments of the neck/head. Note lymph node size, "
            "necrosis, calcification, and relation to adjacent structures. "
            "Report mucosal thickening, air-fluid levels, and osseous involvement."
        ),
    }
    if clinical_domain in _domain_hints:
        specific_hints.append(_domain_hints[clinical_domain])

    # Protocol-specific hints
    _proto_hints = {
        "PE protocol":        "Evaluate for filling defects in pulmonary arteries to subsegmental level. "
                              "Report right heart strain signs (RV:LV ratio, septal deviation, reflux). "
                              "Note any infarcts or pleural effusions.",
        "HRCT":               "Report using HRCT pattern (ground-glass, consolidation, reticulation, honeycombing). "
                              "Note distribution (central/peripheral, upper/lower, unilateral/bilateral).",
        "Triple-phase":       "Report arterial, portal venous, and delayed phase enhancement characteristics. "
                              "Describe enhancement pattern (arterial wash-in, washout, capsule).",
        "MRCP":               "Evaluate biliary tree caliber, filling defects, strictures, and pancreatic duct. "
                              "Report choledocholithiasis, ductal dilatation, and any periductal signal change.",
        "MR Angiography":     "Report vessel caliber, stenosis grade (NASCET method if carotid), "
                              "aneurysm presence and morphology, and flow voids.",
        "Cardiac CT":         "Report Agatston calcium score per vessel and total. "
                              "Note coronary artery stenosis (if CTA), plaque morphology, and any incidental findings.",
        "Arthrography":       "Report intra-articular contrast distribution, cartilage defects (full- vs partial-thickness), "
                              "labral/meniscal tears, and ligament integrity.",
        "Diffusion-Weighted": "Report ADC values for any restricted diffusion foci. "
                              "Correlate DWI with ADC to distinguish true restriction from T2 shine-through.",
    }
    if protocol in _proto_hints:
        specific_hints.append(_proto_hints[protocol])

    if sequences:
        specific_hints.append(f"MRI sequences available: {', '.join(sequences)}. Report signal characteristics on each relevant sequence.")

    return {
        "exam_type": exam_type,
        "modality": mod,
        "modality_full": mod_full,
        "body_region": detected_region,
        "body_label": body_label,
        "clinical_domain": clinical_domain,
        "laterality": laterality,
        "contrast": contrast,
        "protocol": protocol,
        "sequences": sequences,
        "study_label": study_label,
        "specific_hints": specific_hints,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_prompt(
    study_type: Dict[str, Any],
    clinical_info: str,
    findings_summary: str,
    abnormalities: list,
    triage_level: str,
    confidence: float,
    measurements: dict = None,
) -> str:
    """
    Construct an instruction prompt rich with study-type context.
    Works with instruction-tuned models (Flan-T5, GPT, Llama, etc.).
    """
    mod = study_type.get("modality", "Study")
    study_label = study_type.get("study_label", mod)
    body_label = study_type.get("body_label", "")
    laterality = study_type.get("laterality", "")
    contrast = study_type.get("contrast", "")
    protocol = study_type.get("protocol", "")
    sequences = study_type.get("sequences", [])
    specific_hints = study_type.get("specific_hints", [])
    modality_full = study_type.get("modality_full", mod)

    parts = [
        "You are an expert radiologist generating a preliminary AI-assisted radiology report.",
        "Write a professional, clinically accurate, anatomically specific report based ONLY on the data provided.",
        "Do not invent findings. Use precise radiological and anatomical language appropriate for the modality.",
        "",
        f"EXAMINATION: {study_label}",
        f"MODALITY: {modality_full} ({mod})",
    ]
    if body_label:
        parts.append(f"ANATOMICAL REGION: {body_label}")
    if laterality:
        parts.append(f"LATERALITY: {laterality.title()}")
    if contrast:
        parts.append(f"CONTRAST: {contrast.title()}")
    if protocol:
        parts.append(f"PROTOCOL: {protocol}")
    if sequences:
        parts.append(f"MRI SEQUENCES: {', '.join(sequences)}")
    if clinical_info:
        parts.append(f"CLINICAL INDICATION: {clinical_info}")

    # Imaging guidance
    if specific_hints:
        parts.append("")
        parts.append("IMAGING GUIDANCE (apply when generating the report):")
        for h in specific_hints:
            parts.append(f"  {h}")

    # AI findings
    parts.append("")
    if findings_summary:
        parts.append(f"AI ANALYSIS SUMMARY: {findings_summary}")
    if abnormalities:
        parts.append("DETECTED ABNORMALITIES:")
        for a in abnormalities[:12]:
            parts.append(f"  - {a}")

    # Measurements
    if measurements and isinstance(measurements, dict):
        meas_lines = []
        skip = {"overlays", "reference_suggestions", "online_references",
                "report", "triage_level", "triage_score", "triage_flagged", "series_id", "study_id"}
        for k, v in measurements.items():
            if k in skip or v is None or isinstance(v, (dict, list)):
                continue
            meas_lines.append(f"  - {str(k).replace('_', ' ').title()}: {v}")
        if meas_lines:
            parts.append("QUANTITATIVE AI MEASUREMENTS:")
            parts.extend(meas_lines[:20])

    if triage_level:
        parts.append(f"AI TRIAGE: {triage_level.upper()} (confidence {confidence:.0%})")
    else:
        parts.append(f"AI CONFIDENCE: {confidence:.0%}")

    parts += [
        "",
        "Generate a complete structured radiology report in this EXACT format:",
        "FINDINGS: [4-6 sentences. Describe specific imaging findings for each anatomical "
        "compartment with location, size, attenuation/signal, and enhancement. "
        "State that normal structures are unremarkable if no abnormality. Be precise.]",
        "IMPRESSION: [1-3 sentences. Primary diagnosis or most likely interpretation. "
        "Include differential if appropriate. Be direct and clinically actionable.]",
        "RECOMMENDATIONS: [2-4 bullet points. Urgency, follow-up imaging, clinical correlation, "
        "or additional workup appropriate for the findings and modality.]",
        "",
        "Report:",
    ]
    return "\n".join(p for p in parts if p is not None)


# ─────────────────────────────────────────────────────────────────────────────
# Response parser
# ─────────────────────────────────────────────────────────────────────────────

def _parse_llm_output(text: str) -> Dict[str, str]:
    text = (text or "").strip()
    result = {"findings": "", "impression": "", "recommendations": ""}

    sections = {
        "findings":        re.search(r"FINDINGS:\s*(.*?)(?=IMPRESSION:|RECOMMENDATIONS:|$)", text, re.S | re.I),
        "impression":      re.search(r"IMPRESSION:\s*(.*?)(?=RECOMMENDATIONS:|FINDINGS:|$)", text, re.S | re.I),
        "recommendations": re.search(r"RECOMMENDATIONS?:\s*(.*?)(?=IMPRESSION:|FINDINGS:|$)", text, re.S | re.I),
    }
    for key, match in sections.items():
        if match:
            result[key] = match.group(1).strip()

    if not any(result.values()):
        result["findings"] = text
        result["impression"] = "AI preliminary assessment. Radiologist review required."
        result["recommendations"] = "• Radiologist correlation and review required."

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Backend 1: External API (OpenAI-compatible)
# ─────────────────────────────────────────────────────────────────────────────

def _generate_via_api(prompt: str) -> Optional[Dict[str, str]]:
    api_url = _setting("AI_REPORT_API_URL")
    api_key = _setting("AI_REPORT_API_KEY")
    if not api_url or not api_key:
        return None

    model = _setting("AI_REPORT_MODEL", "gpt-3.5-turbo")
    max_tokens = int(_setting("AI_REPORT_MAX_TOKENS", "600"))
    timeout = int(_setting("AI_REPORT_TIMEOUT", "30"))

    try:
        import requests
        url = api_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert radiologist generating preliminary AI-assisted reports. "
                        "Write concise, accurate, professional radiology reports structured as: "
                        "FINDINGS / IMPRESSION / RECOMMENDATIONS. "
                        "This is an AI-generated preliminary report requiring radiologist review."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.25,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        logger.info("AI report generated via external API (model=%s)", model)
        return _parse_llm_output(content)
    except Exception as exc:
        logger.warning("External AI API call failed: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Backend 2: Local transformers model
# ─────────────────────────────────────────────────────────────────────────────

def _load_local_model():
    global _local_pipeline, _local_pipeline_error

    with _model_lock:
        if _local_pipeline is not None:
            return _local_pipeline
        _local_pipeline_error = None

        model_id = _setting("AI_LOCAL_MODEL", "google/flan-t5-base")
        logger.info("Loading local AI model: %s", model_id)

        try:
            from transformers import pipeline as hf_pipeline
            import torch

            device = -1  # CPU
            if any(x in model_id.lower() for x in ("flan", "t5", "bart")):
                for task in ("text2text-generation", "text-generation"):
                    try:
                        pipe = hf_pipeline(
                            task,
                            model=model_id,
                            device=device,
                            model_kwargs={"low_cpu_mem_usage": True, "dtype": torch.float32},
                        )
                        break
                    except ValueError:
                        continue
                else:
                    raise ValueError(f"No working task for model {model_id}")
            else:
                pipe = hf_pipeline(
                    "text-generation",
                    model=model_id,
                    device=device,
                    model_kwargs={"low_cpu_mem_usage": True, "dtype": torch.float32},
                )
            _local_pipeline = pipe
            logger.info("Local AI model loaded: %s", model_id)
            return pipe

        except Exception as exc:
            _local_pipeline_error = str(exc)
            logger.warning("Failed to load local AI model '%s': %s", model_id, exc)
            return None


def _generate_via_local_model(prompt: str) -> Optional[Dict[str, str]]:
    pipe = _load_local_model()
    if pipe is None:
        return None

    max_tokens = int(_setting("AI_REPORT_MAX_TOKENS", "500"))

    try:
        model_id = _setting("AI_LOCAL_MODEL", "google/flan-t5-base")
        is_seq2seq = any(x in model_id.lower() for x in ("flan", "t5", "bart"))

        if is_seq2seq:
            outputs = pipe(prompt, max_new_tokens=max_tokens, do_sample=False, num_beams=4)
            generated = outputs[0]["generated_text"] if isinstance(outputs, list) else str(outputs)
        else:
            outputs = pipe(
                prompt,
                max_new_tokens=max_tokens,
                do_sample=True,
                temperature=0.25,
                top_p=0.85,
                repetition_penalty=1.2,
                pad_token_id=pipe.tokenizer.eos_token_id,
            )
            generated = outputs[0]["generated_text"]
            if generated.startswith(prompt):
                generated = generated[len(prompt):].strip()

        logger.info("AI report generated via local model (%s)", model_id)
        parsed = _parse_llm_output(generated)

        # Quality gate: reject hallucinated/repetitive/trivially short output
        findings_text = parsed.get("findings", "")
        impression_text = parsed.get("impression", "")
        if not _local_output_quality_ok(findings_text, impression_text, generated):
            logger.warning("Local model output failed quality check — falling back to deterministic")
            return None

        return parsed

    except Exception as exc:
        logger.warning("Local model inference failed: %s", exc)
        return None


def _local_output_quality_ok(findings: str, impression: str, raw: str) -> bool:
    """
    Heuristic quality check for local-model output.
    Rejects: too short, repetitive, prompt-echoed, or medically incoherent.
    """
    combined = (findings + " " + impression).strip()
    if len(combined) < 80:
        return False

    low = combined.lower()

    # Reject prompt-echoed output
    _prompt_echoes = [
        "you are an expert radiologist",
        "describe specific imaging findings for each anatomical",
        "write a professional, clinically accurate",
        "do not invent findings",
        "4-6 sentences",
        "1-3 sentences. primary diagnosis",
        "2-4 bullet points",
        "generate a complete structured",
        "ai analysis summary:",
        "anatomical region:",
        "clinical indication:",
        "modality:",
        "imaging guidance",
        "report:",
    ]
    if any(echo in low for echo in _prompt_echoes):
        return False

    # Detect repeating phrases (causal-LM looping)
    words = combined.split()
    if len(words) > 20:
        half = len(words) // 2
        if words[:half] == words[half:half * 2]:
            return False
    # Reject if >40% of words are duplicates (severe repetition)
    if len(words) > 30:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.35:
            return False

    # Must contain genuine medical language
    medical_terms = [
        "normal", "no ", "identified", "demonstrates", "demonstrate", "reveal",
        "shows", "unremarkable", "finding", "lesion", "mass", "effusion",
        "opacity", "signal", "attenuat", "cortex", "organ", "hepat", "pulm",
        "patient", "acute", "chronic", "bilater", "unilater", "bilat",
        "parenchym", "ventricl", "pleural", "osseous", "soft tissue",
    ]
    if not any(t in low for t in medical_terms):
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Backend 3: Enhanced deterministic fallback
# ─────────────────────────────────────────────────────────────────────────────

# Region-specific normal findings templates (far more specific than the old modality-only ones)
_NORMAL_FINDINGS_REGION: Dict[str, str] = {
    # Neuro CT
    "CT:brain": (
        "CT brain demonstrates no acute intracranial abnormality. The cerebral parenchyma "
        "shows normal gray-white matter differentiation without focal hypodensity or hyperdensity. "
        "Ventricles are normal in size and configuration. Sulci and cisterns are patent and symmetric. "
        "No midline shift, mass effect, or herniation identified. No acute hemorrhage, extra-axial "
        "collection, or calvarial abnormality."
    ),
    "MR:brain": (
        "MRI brain demonstrates no significant intracranial abnormality. The cerebral parenchyma "
        "shows normal signal intensity on T1, T2, and FLAIR sequences without focal signal abnormality. "
        "No restricted diffusion identified on DWI/ADC. Ventricles are normal in size. Sulci and cisterns "
        "are patent and symmetric. No midline shift, mass lesion, or abnormal enhancement. "
        "Posterior fossa structures appear unremarkable."
    ),
    "CT:paranasal_sinus": (
        "CT paranasal sinuses demonstrates clear aeration of all paranasal sinuses bilaterally. "
        "No mucosal thickening, air-fluid levels, or opacification identified. Ostiomeatal "
        "complexes appear patent bilaterally. Nasal septum is midline. Turbinates appear unremarkable. "
        "No bony erosion or orbital/intracranial extension."
    ),
    "MR:spine": (
        "MRI spine demonstrates preservation of vertebral body heights and normal intervertebral "
        "disc heights throughout. Disc signal is maintained on T2-weighted sequences without evidence "
        "of disc desiccation at the levels imaged. Spinal canal is patent with adequate cord space. "
        "Spinal cord demonstrates normal signal without myelopathic change. Neural foramina are patent "
        "bilaterally. No significant disc herniation, spinal stenosis, or nerve root compression identified."
    ),
    "CT:chest": (
        "CT chest demonstrates clear lung parenchyma bilaterally without focal consolidation, "
        "ground-glass opacity, nodule, or mass. No pleural effusion or pneumothorax identified. "
        "Mediastinum is normal in caliber without lymphadenopathy (all nodes <1 cm short axis). "
        "Cardiac silhouette is within normal limits. Pericardium is unremarkable. "
        "No hilar enlargement. Visualised osseous structures appear intact."
    ),
    "CR:chest": (
        "Chest radiograph demonstrates clear lung fields bilaterally without focal air-space "
        "opacity, interstitial marking increase, or pleural effusion. Cardiac silhouette is within "
        "normal limits (cardiothoracic ratio <0.5). Mediastinum is not widened. Trachea is midline. "
        "No pneumothorax identified. Costophrenic angles are acute and clear. "
        "Visualised bony thorax appears intact without acute fracture."
    ),
    "CT:abdomen": (
        "CT abdomen demonstrates no acute intra-abdominal pathology. Liver is normal in size "
        "and attenuation without focal lesion. Spleen, pancreas, and adrenal glands are unremarkable. "
        "Kidneys are symmetric and enhance normally. No hydronephrosis or nephrolithiasis identified. "
        "Bowel loops are non-distended without wall thickening or pneumatosis. "
        "No free intra-abdominal air or pathological free fluid. "
        "Retroperitoneal structures and mesentery appear unremarkable."
    ),
    "CT:abdomen_pelvis": (
        "CT abdomen and pelvis demonstrates no acute findings. Solid abdominal organs (liver, spleen, "
        "pancreas, kidneys, adrenals) are within normal limits without focal abnormality. "
        "Bowel is non-obstructed and non-distended. No pathological free fluid or free air. "
        "Pelvic organs appear unremarkable. No significant lymphadenopathy. "
        "No acute osseous abnormality within the imaged field."
    ),
    "MR:knee": (
        "MRI knee demonstrates intact articular cartilage of the medial and lateral femoral condyles, "
        "tibial plateaux, and patella without focal chondral defect or full-thickness loss. "
        "Medial and lateral menisci show normal morphology and signal without tear. "
        "Anterior and posterior cruciate ligaments are intact. Medial and lateral collateral ligaments "
        "are intact. Quadriceps and patellar tendons are unremarkable. No joint effusion or "
        "bone marrow oedema pattern identified."
    ),
    "MR:shoulder": (
        "MRI shoulder demonstrates intact rotator cuff tendons (supraspinatus, infraspinatus, "
        "teres minor, and subscapularis) without full- or partial-thickness tear. "
        "Subacromial-subdeltoid bursa is unremarkable without effusion. "
        "Labrum shows normal morphology and signal without tear. "
        "Glenohumeral joint demonstrates normal alignment. No bone marrow signal abnormality. "
        "Acromioclavicular joint is unremarkable."
    ),
    "US:abdomen": (
        "Sonographic evaluation of the abdomen demonstrates normal liver echogenicity, size, and "
        "morphology without focal lesion, biliary ductal dilatation, or portal hypertension features. "
        "Gallbladder is thin-walled without calculus or sludge. Common bile duct caliber is within "
        "normal limits. Pancreas is visualised and unremarkable. Kidneys are symmetric with normal "
        "cortical echogenicity and without hydronephrosis or calculus. Spleen is normal in size."
    ),
    "MG:breast": (
        "Mammogram demonstrates heterogeneously dense fibroglandular tissue (BI-RADS density B/C). "
        "No suspicious mass, focal asymmetry, or architectural distortion identified. "
        "No suspicious calcifications. Skin and nipple-areolar complexes are unremarkable. "
        "Axillary lymph nodes appear normal in morphology and size. "
        "Assessment: BI-RADS 1 — Negative. Routine screening interval recommended."
    ),
}

_NORMAL_FINDINGS_MODALITY: Dict[str, str] = {
    "CT":  "CT {label} demonstrates no acute abnormality. Visualised structures appear within normal limits.",
    "MR":  "MRI {label} demonstrates no significant signal abnormality. Structures appear within normal limits.",
    "CR":  "Radiograph of the {label} demonstrates no acute osseous or soft tissue abnormality.",
    "DX":  "Digital radiograph of the {label} demonstrates no acute bony abnormality. Soft tissues appear unremarkable.",
    "US":  "Sonographic evaluation of the {label} demonstrates no focal abnormality. Normal echogenicity and vascularity.",
    "MG":  "Mammographic examination is negative for malignancy. BI-RADS 1.",
    "PT":  "PET study demonstrates no areas of abnormal hypermetabolic activity. Normal physiologic distribution.",
    "NM":  "Nuclear medicine study demonstrates normal radiotracer distribution without focal abnormality.",
    "XA":  "Angiographic study demonstrates normal vessel caliber and morphology without stenosis or occlusion.",
}

_ABNORMAL_FINDINGS_MODALITY: Dict[str, str] = {
    "CT":  "CT {label} demonstrates {findings}. CT attenuation characteristics are described above.",
    "MR":  "MRI {label} reveals {findings}. Signal characteristics are as described on the relevant sequences.",
    "CR":  "Radiograph of the {label} demonstrates {findings}. Correlation with clinical presentation recommended.",
    "DX":  "Digital radiograph of the {label} reveals {findings}. Clinical correlation recommended.",
    "US":  "Sonographic evaluation of the {label} demonstrates {findings}. Additional imaging may be considered.",
    "MG":  "Mammographic examination demonstrates {findings}. Additional workup as per BI-RADS recommendations.",
    "_default": "{modality} examination of the {label} demonstrates {findings}.",
}


def _generate_deterministic(
    study_type: Dict[str, Any],
    clinical_info: str,
    findings_summary: str,
    abnormalities: list,
    triage_level: str,
    confidence: float,
    measurements: dict = None,
) -> Dict[str, str]:
    """
    High-quality deterministic report using study-type-specific templates.
    Used as fallback when no LLM is available.
    """
    mod = study_type.get("modality", "Study")
    body_region = study_type.get("body_region", "")
    body_label = study_type.get("body_label", "")
    study_label = study_type.get("study_label", mod)
    laterality = study_type.get("laterality", "")
    contrast = study_type.get("contrast", "")
    protocol = study_type.get("protocol", "")
    clinical_domain = study_type.get("clinical_domain", "general")

    lat_qualifier = f" {laterality}" if laterality else ""
    label = (body_label + lat_qualifier).strip() or "study"
    abn_text = "; ".join(abnormalities[:8]) if abnormalities else ""

    # Measurement addendum
    meas_lines = []
    if measurements and isinstance(measurements, dict):
        skip = {"overlays", "reference_suggestions", "online_references",
                "report", "triage_level", "triage_score", "triage_flagged", "series_id", "study_id"}
        for k, v in measurements.items():
            if k in skip or v is None or isinstance(v, (dict, list)):
                continue
            meas_lines.append(f"  {str(k).replace('_', ' ').title()}: {v}")

    # ── Findings ──────────────────────────────────────────────────────────
    if not abnormalities:
        # Try region-specific normal template first
        region_key = f"{mod}:{body_region}"
        if region_key in _NORMAL_FINDINGS_REGION:
            findings = _NORMAL_FINDINGS_REGION[region_key]
        else:
            tmpl = _NORMAL_FINDINGS_MODALITY.get(mod,
                   "{modality} examination of the {label} is unremarkable.")
            findings = tmpl.format(modality=mod, label=label)
        if findings_summary and findings_summary not in findings:
            findings += f"\n\nAI analysis summary: {findings_summary}"
    else:
        tmpl = _ABNORMAL_FINDINGS_MODALITY.get(mod, _ABNORMAL_FINDINGS_MODALITY["_default"])
        findings = tmpl.format(modality=mod, label=label,
                               findings=abn_text or findings_summary or "an incidental finding")
        if findings_summary and findings_summary not in findings:
            findings += f"\n\nAI analysis summary: {findings_summary}"

    if contrast:
        findings = f"Examination performed {contrast}.\n\n" + findings
    if protocol:
        findings = f"Protocol: {protocol}.\n\n" + findings
    if meas_lines:
        findings += "\n\nAI-derived measurements:\n" + "\n".join(meas_lines[:15])
    if clinical_info:
        findings = f"Clinical indication: {clinical_info}\n\n" + findings

    # ── Impression ────────────────────────────────────────────────────────
    if triage_level in ("urgent", "critical", "stat"):
        impression = (
            f"URGENT: AI analysis identifies findings on {study_label} requiring prompt radiologist "
            f"attention (confidence {confidence:.0%}). Immediate clinical correlation and "
            f"radiologist review recommended."
        )
    elif triage_level in ("high", "elevated"):
        impression = (
            f"AI analysis of {study_label} suggests {abn_text or 'possible pathology'} "
            f"(confidence {confidence:.0%}). Expedited radiologist review and clinical correlation recommended."
        )
    elif abnormalities:
        impression = (
            f"AI analysis of {study_label} suggests possible {abn_text} "
            f"(confidence {confidence:.0%}). Radiologist review and clinical correlation are recommended to confirm."
        )
    else:
        impression = (
            f"No acute abnormality detected by AI analysis on {study_label} "
            f"({confidence:.0%} confidence). Radiologist review recommended for final interpretation."
        )

    # ── Recommendations ───────────────────────────────────────────────────
    recs = []
    if triage_level in ("urgent", "critical", "stat"):
        recs.append("Immediate radiologist review — urgent/critical triage classification")
        recs.append("Direct clinical notification if findings are confirmed on radiologist review")
        recs.append("Consider immediate clinical management while awaiting radiologist sign-off")
    elif triage_level in ("high", "elevated"):
        recs.append("Expedited radiologist review recommended within the same working day")
        recs.append("Clinical correlation with current symptoms, history, and lab results")
    else:
        recs.append("Routine radiologist review and sign-off")
        recs.append("Correlation with prior imaging studies if available")

    # Domain-specific follow-up recommendations
    _domain_recs = {
        "neuro": "Neurology/neurosurgery referral if symptoms are persistent or progressive",
        "thoracic": "Pulmonology referral and pulmonary function tests if parenchymal disease confirmed",
        "cardiac": "Cardiology referral and echocardiogram if cardiac pathology confirmed",
        "vascular": "Vascular surgery or interventional radiology review if significant vascular pathology",
        "abdominal": "Gastroenterology/surgery referral if significant visceral pathology confirmed",
        "pelvic": "Gynaecology/urology referral as clinically appropriate",
        "msk": "Orthopaedic surgery review if structural abnormality confirmed; consider weight-bearing views",
        "spine": "Neurosurgery or orthopaedics review if cord compression or instability suspected",
    }
    if clinical_domain in _domain_recs and abnormalities:
        recs.append(_domain_recs[clinical_domain])

    if confidence < 0.65:
        recs.append("AI confidence is moderate — interpret with caution and consider additional imaging or dedicated protocol")

    recommendations = "\n".join(f"• {r}" for r in recs)

    return {
        "findings": findings,
        "impression": impression,
        "recommendations": recommendations,
        "disclaimer": (
            f"AI-generated preliminary report ({study_label}, confidence {confidence:.0%}). "
            "For radiologist review and clinical decision support only. "
            "Not a final diagnosis. Radiologist sign-off required before clinical use."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_llm_report(
    modality: str = "",
    body_part: str = "",
    clinical_info: str = "",
    findings_summary: str = "",
    abnormalities: Optional[list] = None,
    triage_level: str = "",
    confidence: float = 0.0,
    measurements: Optional[dict] = None,
    study_description: str = "",
    series_descriptions: Optional[List[str]] = None,
    ai_model_body_part: str = "",
) -> Dict[str, str]:
    """
    Generate a preliminary radiology report using the best available backend.
    Now performs study-type identification first for accurate, specialised output.

    Returns a dict with: findings, impression, recommendations, disclaimer, llm_used, study_type
    """
    abnormalities = abnormalities or []
    series_descriptions = series_descriptions or []
    modality = (modality or "").upper().strip()

    # ── Step 1: Identify the study type ───────────────────────────────────
    study_type = _identify_study_type(
        modality=modality,
        body_part=body_part or "",
        study_description=study_description or "",
        series_descriptions=series_descriptions,
        clinical_info=clinical_info or "",
        ai_model_body_part=ai_model_body_part,
    )
    logger.info(
        "Study identified: %s | domain: %s | contrast: %s | protocol: %s",
        study_type["study_label"], study_type["clinical_domain"],
        study_type["contrast"] or "none", study_type["protocol"] or "none",
    )

    # ── Step 2: Build prompt ──────────────────────────────────────────────
    prompt = _build_prompt(
        study_type=study_type,
        clinical_info=clinical_info,
        findings_summary=findings_summary,
        abnormalities=abnormalities,
        triage_level=triage_level,
        confidence=confidence,
        measurements=measurements,
    )

    # ── Step 3: Try backends in order ─────────────────────────────────────
    result = None
    llm_used = "deterministic"

    api_url = _setting("AI_REPORT_API_URL")
    api_key = _setting("AI_REPORT_API_KEY")
    if api_url and api_key:
        result = _generate_via_api(prompt)
        if result:
            llm_used = f"api:{_setting('AI_REPORT_MODEL', 'gpt-3.5-turbo')}"

    if result is None:
        use_local = _setting("AI_USE_LOCAL_MODEL", "true").lower() in ("1", "true", "yes")
        if use_local:
            result = _generate_via_local_model(prompt)
            if result:
                llm_used = f"local:{_setting('AI_LOCAL_MODEL', 'google/flan-t5-base')}"

    if result is None:
        result = _generate_deterministic(
            study_type=study_type,
            clinical_info=clinical_info,
            findings_summary=findings_summary,
            abnormalities=abnormalities,
            triage_level=triage_level,
            confidence=confidence,
            measurements=measurements,
        )
        llm_used = "deterministic"

    if not result.get("disclaimer"):
        result["disclaimer"] = (
            f"AI-generated preliminary report ({study_type['study_label']}, "
            f"confidence {confidence:.0%}). "
            "For radiologist review only. Not a substitute for radiologist interpretation."
        )

    result["llm_used"] = llm_used
    result["study_type"] = study_type.get("study_label", "")
    logger.info("Report generated: backend=%s, exam=%s", llm_used, study_type["study_label"])
    return result


def generate_llm_report_from_analysis(analysis) -> Dict[str, str]:
    """Convenience wrapper: extracts all available metadata from an AIAnalysis object."""
    study = getattr(analysis, "study", None)

    # Modality
    modality_obj = getattr(study, "modality", None)
    modality = getattr(modality_obj, "code", None) or ""

    # Body part / description
    body_part = getattr(study, "body_part", "") or ""
    study_description = getattr(study, "study_description", "") or ""
    clinical_info = getattr(study, "clinical_info", "") or ""
    findings_summary = getattr(analysis, "findings", "") or ""
    confidence = float(getattr(analysis, "confidence_score", 0.0) or 0.0)

    # Series descriptions from measurements (stored by the inference engine) and from DB
    m = getattr(analysis, "measurements", {}) or {}
    if not isinstance(m, dict):
        m = {}

    series_descriptions: List[str] = []
    # From measurements
    for key in ("series_description", "series_desc"):
        sd = m.get(key)
        if sd and isinstance(sd, str):
            series_descriptions.append(sd)
    # From the study's series set in DB
    try:
        series_qs = study.series_set.only("series_description", "body_part").all()
        for s in series_qs[:10]:
            desc = getattr(s, "series_description", "") or ""
            bp = getattr(s, "body_part", "") or ""
            if desc:
                series_descriptions.append(desc)
            if bp and bp not in series_descriptions:
                series_descriptions.append(bp)
    except Exception:
        pass

    # AI model body part context
    ai_model = getattr(analysis, "ai_model", None)
    ai_model_body_part = getattr(ai_model, "body_part", "") or ""

    # Abnormalities
    abnormalities: List[str] = []
    raw_abn = getattr(analysis, "abnormalities_detected", []) or []
    if isinstance(raw_abn, list):
        for item in raw_abn:
            if isinstance(item, dict):
                label = ""
                for key in ("label", "type", "name", "finding"):
                    val = item.get(key, "")
                    if val and isinstance(val, str):
                        label = val.strip()
                        break
                if label:
                    extra = []
                    for detail_key in ("location", "size", "severity", "confidence"):
                        dv = item.get(detail_key)
                        if dv and str(dv).strip():
                            extra.append(f"{detail_key}: {dv}")
                    if extra:
                        label = f"{label} ({', '.join(extra)})"
                    abnormalities.append(label)
            elif isinstance(item, str) and item.strip():
                abnormalities.append(item.strip())

    triage_level = (m.get("triage_level") or "").strip().lower()

    return generate_llm_report(
        modality=modality,
        body_part=body_part,
        clinical_info=clinical_info,
        findings_summary=findings_summary,
        abnormalities=abnormalities,
        triage_level=triage_level,
        confidence=confidence,
        measurements=m,
        study_description=study_description,
        series_descriptions=series_descriptions,
        ai_model_body_part=ai_model_body_part,
    )
