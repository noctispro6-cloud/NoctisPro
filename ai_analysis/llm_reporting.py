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
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("ai_analysis")

# Thread lock to prevent concurrent model loads
_model_lock = threading.Lock()
_local_pipeline = None
_local_pipeline_error: Optional[str] = None

# ────────────────────────────────────────────────────────────────────────────
# Settings helpers
# ────────────────────────────────────────────────────────────────────────────

def _setting(name: str, default: str = "") -> str:
    """Read a setting from Django settings first, then environment."""
    try:
        from django.conf import settings
        return str(getattr(settings, name, "") or os.environ.get(name, default) or default)
    except Exception:
        return str(os.environ.get(name, default) or default)


# ────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ────────────────────────────────────────────────────────────────────────────

def _build_prompt(
    modality: str,
    body_part: str,
    clinical_info: str,
    findings_summary: str,
    abnormalities: list,
    triage_level: str,
    confidence: float,
    measurements: dict = None,
) -> str:
    """
    Construct an instruction prompt for a radiology AI assistant.
    Designed to work with instruction-tuned models (Flan-T5, GPT, Llama, etc.).
    """
    modality_hints = {
        "CT":  "Use Hounsfield unit terminology. Note density, attenuation, and enhancement patterns.",
        "MR":  "Use MRI signal terminology (T1/T2 signal, FLAIR, DWI). Note signal intensity and enhancement.",
        "CR":  "Use plain film terminology. Note opacity, lucency, and bone/soft tissue detail.",
        "DX":  "Use plain film terminology. Note opacity, lucency, cortical integrity, and alignment.",
        "US":  "Use sonographic terminology. Note echogenicity, vascularity, and shadowing.",
        "MG":  "Use mammographic terminology. Note density, mass margins, and calcification morphology.",
        "PT":  "Use nuclear medicine terminology. Note SUV, metabolic activity, and distribution.",
        "NM":  "Use nuclear medicine terminology. Note tracer uptake, distribution, and photopenic defects.",
    }
    hint = modality_hints.get(modality, "")

    parts = [
        "You are an expert radiologist generating a preliminary AI-assisted radiology report.",
        "Write a professional, clinically accurate, specific report based ONLY on the data provided.",
        "Do not invent findings not listed below. Use precise anatomical and radiological language.",
        hint,
        "",
        f"MODALITY: {modality or 'Unknown'}",
    ]
    if body_part:
        parts.append(f"BODY PART / REGION: {body_part}")
    if clinical_info:
        parts.append(f"CLINICAL INDICATION: {clinical_info}")
    if findings_summary:
        parts.append(f"AI ANALYSIS SUMMARY: {findings_summary}")
    if abnormalities:
        parts.append("DETECTED ABNORMALITIES:")
        for a in abnormalities[:10]:
            parts.append(f"  - {a}")
    # Include structured measurements if available
    if measurements and isinstance(measurements, dict):
        meas_lines = []
        for k, v in measurements.items():
            if k in ("overlays", "reference_suggestions", "online_references",
                     "report", "triage_level", "triage_score", "triage_flagged"):
                continue
            if v is None or isinstance(v, (dict, list)):
                continue
            meas_lines.append(f"  - {str(k).replace('_', ' ').title()}: {v}")
        if meas_lines:
            parts.append("STRUCTURED MEASUREMENTS / AI OUTPUTS:")
            parts.extend(meas_lines[:20])
    if triage_level:
        parts.append(f"AI TRIAGE LEVEL: {triage_level.upper()} (confidence: {confidence:.0%})")
    else:
        parts.append(f"AI CONFIDENCE: {confidence:.0%}")

    parts += [
        "",
        "Write a complete structured radiology report in this EXACT format:",
        "FINDINGS: [3-5 sentences. Describe specific imaging findings with location, size, and character. "
        "State normal structures if no abnormality. Be precise and anatomically specific.]",
        "IMPRESSION: [1-3 sentences. State the primary diagnosis or most likely interpretation. "
        "Include differential if appropriate. Be direct and clinically actionable.]",
        "RECOMMENDATIONS: [2-4 bullet points. Include urgency, follow-up imaging, clinical correlation, "
        "or additional workup as appropriate for the findings.]",
        "",
        "Report:",
    ]
    return "\n".join(p for p in parts if p is not None)


# ────────────────────────────────────────────────────────────────────────────
# Response parser
# ────────────────────────────────────────────────────────────────────────────

def _parse_llm_output(text: str) -> Dict[str, str]:
    """
    Parse the LLM output into findings/impression/recommendations sections.
    Handles various output formats gracefully.
    """
    text = (text or "").strip()
    result = {"findings": "", "impression": "", "recommendations": ""}

    # Try structured parsing first
    import re
    sections = {
        "findings": re.search(r"FINDINGS:\s*(.*?)(?=IMPRESSION:|RECOMMENDATIONS:|$)", text, re.S | re.I),
        "impression": re.search(r"IMPRESSION:\s*(.*?)(?=RECOMMENDATIONS:|FINDINGS:|$)", text, re.S | re.I),
        "recommendations": re.search(r"RECOMMENDATIONS?:\s*(.*?)(?=IMPRESSION:|FINDINGS:|$)", text, re.S | re.I),
    }

    for key, match in sections.items():
        if match:
            result[key] = match.group(1).strip()

    # If structured parsing failed, use the whole text as findings
    if not any(result.values()):
        result["findings"] = text
        result["impression"] = "AI preliminary assessment. Radiologist review required."
        result["recommendations"] = "- Radiologist correlation and review required."

    return result


# ────────────────────────────────────────────────────────────────────────────
# Backend 1: External API (OpenAI-compatible)
# ────────────────────────────────────────────────────────────────────────────

def _generate_via_api(prompt: str) -> Optional[Dict[str, str]]:
    """Call an external OpenAI-compatible API."""
    api_url = _setting("AI_REPORT_API_URL")
    api_key = _setting("AI_REPORT_API_KEY")
    if not api_url or not api_key:
        return None

    model = _setting("AI_REPORT_MODEL", "gpt-3.5-turbo")
    max_tokens = int(_setting("AI_REPORT_MAX_TOKENS", "500"))
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
                        "Write concise, accurate, professional radiology reports. "
                        "This is an AI-generated preliminary report for radiologist review."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,  # Lower temperature for more consistent medical text
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        logger.info("AI report generated via external API (model=%s)", model)
        return _parse_llm_output(content)
    except Exception as exc:
        logger.warning("External AI API call failed: %s", exc)
        return None


# ────────────────────────────────────────────────────────────────────────────
# Backend 2: Local transformers model
# ────────────────────────────────────────────────────────────────────────────

def _load_local_model():
    """Load the local transformers pipeline (lazy, cached)."""
    global _local_pipeline, _local_pipeline_error

    with _model_lock:
        if _local_pipeline is not None:
            return _local_pipeline
        # Reset stale errors so retries are possible
        _local_pipeline_error = None

        model_id = _setting("AI_LOCAL_MODEL", "google/flan-t5-base")
        logger.info("Loading local AI model: %s", model_id)

        try:
            from transformers import pipeline as hf_pipeline
            import torch

            # Use CPU — no GPU required
            device = -1  # CPU

            # For seq2seq models (Flan-T5 family) use text-generation
            # (transformers 5.x unified the task names)
            if any(x in model_id.lower() for x in ("flan", "t5", "bart")):
                # Try text2text-generation first, fall back to text-generation
                for task in ("text2text-generation", "text-generation"):
                    try:
                        pipe = hf_pipeline(
                            task,
                            model=model_id,
                            device=device,
                            model_kwargs={"low_cpu_mem_usage": True, "torch_dtype": torch.float32},
                        )
                        break
                    except ValueError:
                        continue
                else:
                    raise ValueError(f"Could not find working task for model {model_id}")
            else:
                task = "text-generation"
                pipe = hf_pipeline(
                    task,
                    model=model_id,
                    device=device,
                    model_kwargs={"low_cpu_mem_usage": True, "torch_dtype": torch.float32},
                )
            _local_pipeline = pipe
            logger.info("Local AI model loaded successfully: %s", model_id)
            return pipe

        except Exception as exc:
            _local_pipeline_error = str(exc)
            logger.warning("Failed to load local AI model '%s': %s", model_id, exc)
            return None
    # If called again after an error, allow retry (don't cache errors permanently)


def _generate_via_local_model(prompt: str) -> Optional[Dict[str, str]]:
    """Generate report using a local HuggingFace model."""
    pipe = _load_local_model()
    if pipe is None:
        return None

    max_tokens = int(_setting("AI_REPORT_MAX_TOKENS", "400"))

    try:
        model_id = _setting("AI_LOCAL_MODEL", "google/flan-t5-base")
        is_seq2seq = "flan" in model_id.lower() or "t5" in model_id.lower()

        if is_seq2seq:
            # Flan-T5: use a condensed instruction prompt (seq2seq models prefer shorter inputs)
            # Extract key facts for a more focused prompt
            outputs = pipe(
                prompt,
                max_new_tokens=max_tokens,
                do_sample=False,
                num_beams=4,
            )
            generated = outputs[0]["generated_text"] if isinstance(outputs, list) else str(outputs)
        else:
            # Causal LM: text-generation
            outputs = pipe(
                prompt,
                max_new_tokens=max_tokens,
                do_sample=True,
                temperature=0.3,
                top_p=0.85,
                repetition_penalty=1.2,
                pad_token_id=pipe.tokenizer.eos_token_id,
            )
            generated = outputs[0]["generated_text"]
            # Remove the prompt from the output for causal models
            if generated.startswith(prompt):
                generated = generated[len(prompt):].strip()

        logger.info("AI report generated via local model (%s)", model_id)
        return _parse_llm_output(generated)

    except Exception as exc:
        logger.warning("Local model inference failed: %s", exc)
        return None


# ────────────────────────────────────────────────────────────────────────────
# Backend 3: Enhanced deterministic fallback
# ────────────────────────────────────────────────────────────────────────────

# Modality-specific normal findings templates
_NORMAL_FINDINGS = {
    "CT": (
        "CT {body} demonstrates no acute intracranial abnormality. "
        "Parenchyma is unremarkable. Ventricles and sulci are normal in caliber. "
        "No mass effect, midline shift, or herniation. No acute hemorrhage identified."
    ),
    "MR": (
        "MRI {body} shows no significant signal abnormality. "
        "Parenchymal volume and signal intensity appear within normal limits. "
        "No restricted diffusion, mass lesion, or abnormal enhancement identified."
    ),
    "CR": (
        "Chest radiograph demonstrates clear lung fields bilaterally. "
        "Cardiac silhouette is within normal limits. Mediastinum is not widened. "
        "No pleural effusion or pneumothorax identified. Osseous structures appear intact."
    ),
    "DX": (
        "Digital radiograph demonstrates no acute bony abnormality. "
        "Soft tissues appear unremarkable. No joint space narrowing identified. "
        "No fracture or dislocation detected."
    ),
    "US": (
        "Sonographic evaluation demonstrates no focal abnormality. "
        "Parenchymal echogenicity appears within normal limits. "
        "No free fluid identified. Vascularity is preserved on Doppler assessment."
    ),
    "MG": (
        "Mammographic examination demonstrates no suspicious mass, architectural distortion, "
        "or suspicious calcifications. Parenchymal density appears within normal limits."
    ),
    "XA": (
        "Angiographic study demonstrates normal vessel caliber and morphology. "
        "No stenosis, occlusion, or aneurysm identified."
    ),
    "NM": (
        "Nuclear medicine study demonstrates normal radiotracer distribution. "
        "No areas of abnormal uptake or photopenia identified."
    ),
    "PT": (
        "PET study demonstrates no areas of abnormal hypermetabolic activity. "
        "Normal physiologic radiotracer distribution noted."
    ),
}

_ABNORMAL_FINDINGS = {
    "CT": "CT {body} demonstrates {findings}. Additional imaging or clinical correlation may be indicated.",
    "MR": "MRI {body} reveals {findings}. Further characterization with dedicated sequences may be warranted.",
    "CR": "Radiograph demonstrates {findings}. Correlation with clinical presentation recommended.",
    "DX": "Radiographic examination reveals {findings}. Clinical correlation recommended.",
    "US": "Sonographic evaluation demonstrates {findings}. Additional imaging may be considered.",
    "MG": "Mammographic examination demonstrates {findings}. Additional views or ultrasound correlation may be warranted.",
    "_default": "{modality} {body} examination demonstrates {findings}.",
}


def _generate_deterministic(
    modality: str,
    body_part: str,
    clinical_info: str,
    findings_summary: str,
    abnormalities: list,
    triage_level: str,
    confidence: float,
    measurements: dict = None,
) -> Dict[str, str]:
    """
    Enhanced deterministic report — used as fallback when LLM is unavailable.
    More detailed and medically appropriate than the basic version.
    """
    body = body_part or "imaging"
    abn_text = "; ".join(abnormalities[:6]) if abnormalities else ""

    # Build structured measurement addendum
    meas_lines = []
    if measurements and isinstance(measurements, dict):
        for k, v in measurements.items():
            if k in ("overlays", "reference_suggestions", "online_references",
                     "report", "triage_level", "triage_score", "triage_flagged"):
                continue
            if v is None or isinstance(v, (dict, list)):
                continue
            meas_lines.append(f"  {str(k).replace('_', ' ').title()}: {v}")

    # Findings
    if abnormalities or abn_text:
        template = _ABNORMAL_FINDINGS.get(modality, _ABNORMAL_FINDINGS["_default"])
        findings = template.format(
            modality=modality,
            body=body,
            findings=abn_text or findings_summary or "an incidental finding",
        )
        if findings_summary and findings_summary not in findings:
            findings += f"\n\nAI analysis summary: {findings_summary}"
    else:
        template = _NORMAL_FINDINGS.get(modality, "{modality} {body} examination is unremarkable.")
        findings = template.format(modality=modality, body=body)
        if findings_summary:
            findings += f"\n\nAI analysis summary: {findings_summary}"

    if meas_lines:
        findings += "\n\nAI-derived measurements:\n" + "\n".join(meas_lines[:15])

    if clinical_info:
        findings = f"Clinical indication: {clinical_info}\n\n" + findings

    # Impression
    if triage_level == "urgent" or (abnormalities and triage_level == "high"):
        impression = (
            f"URGENT: AI analysis identifies findings requiring prompt radiologist attention "
            f"(triage score confidence {confidence:.0%}). "
            f"Immediate clinical correlation and radiologist review recommended."
        )
    elif abnormalities:
        impression = (
            f"AI analysis suggests possible {abn_text or 'abnormality'} "
            f"with {confidence:.0%} confidence. "
            f"Radiologist review and clinical correlation are recommended to confirm."
        )
    else:
        impression = (
            f"No acute abnormality detected by AI analysis ({confidence:.0%} confidence). "
            f"Radiologist review recommended for final interpretation."
        )

    # Recommendations
    recs = []
    if triage_level == "urgent":
        recs.append("Immediate radiologist review — urgent triage classification")
        recs.append("Direct clinical notification if findings confirmed")
    elif triage_level == "high":
        recs.append("Expedited radiologist review recommended")
        recs.append("Clinical correlation with current symptoms and history")
    else:
        recs.append("Routine radiologist review and sign-off")
        recs.append("Correlation with prior imaging if available")

    if confidence < 0.65:
        recs.append("AI confidence is moderate — interpret with caution and consider additional imaging")

    recommendations = "\n".join(f"• {r}" for r in recs)

    return {
        "findings": findings,
        "impression": impression,
        "recommendations": recommendations,
        "disclaimer": (
            f"AI-generated preliminary report ({confidence:.0%} confidence). "
            "For radiologist review and clinical decision support only. "
            "Not a final diagnosis. Radiologist sign-off required before clinical use."
        ),
    }


# ────────────────────────────────────────────────────────────────────────────
# Main entry point
# ────────────────────────────────────────────────────────────────────────────

def generate_llm_report(
    modality: str = "",
    body_part: str = "",
    clinical_info: str = "",
    findings_summary: str = "",
    abnormalities: Optional[list] = None,
    triage_level: str = "",
    confidence: float = 0.0,
    measurements: Optional[dict] = None,
) -> Dict[str, str]:
    """
    Generate a preliminary radiology report using the best available backend.

    Returns a dict with keys: findings, impression, recommendations, disclaimer, llm_used
    """
    abnormalities = abnormalities or []
    modality = (modality or "Study").upper()
    body_part = (body_part or "").strip()

    prompt = _build_prompt(
        modality=modality,
        body_part=body_part,
        clinical_info=clinical_info,
        findings_summary=findings_summary,
        abnormalities=abnormalities,
        triage_level=triage_level,
        confidence=confidence,
        measurements=measurements,
    )

    # Try backends in priority order
    result = None
    llm_used = "deterministic"

    # 1. External API
    api_url = _setting("AI_REPORT_API_URL")
    api_key = _setting("AI_REPORT_API_KEY")
    if api_url and api_key:
        result = _generate_via_api(prompt)
        if result:
            llm_used = f"api:{_setting('AI_REPORT_MODEL', 'gpt-3.5-turbo')}"

    # 2. Local model (if API not configured or failed)
    if result is None:
        use_local = _setting("AI_USE_LOCAL_MODEL", "true").lower() in ("1", "true", "yes")
        if use_local:
            result = _generate_via_local_model(prompt)
            if result:
                llm_used = f"local:{_setting('AI_LOCAL_MODEL', 'google/flan-t5-base')}"

    # 3. Deterministic fallback
    if result is None:
        result = _generate_deterministic(
            modality=modality,
            body_part=body_part,
            clinical_info=clinical_info,
            findings_summary=findings_summary,
            abnormalities=abnormalities,
            triage_level=triage_level,
            confidence=confidence,
            measurements=measurements,
        )
        llm_used = "deterministic"

    # Always add disclaimer if missing
    if not result.get("disclaimer"):
        result["disclaimer"] = (
            f"AI-generated preliminary report ({confidence:.0%} confidence). "
            "For radiologist review only. Not a substitute for radiologist interpretation."
        )

    result["llm_used"] = llm_used
    logger.info("Report generated using backend: %s", llm_used)
    return result


def generate_llm_report_from_analysis(analysis) -> Dict[str, str]:
    """Convenience wrapper that extracts fields from an AIAnalysis object."""
    study = getattr(analysis, "study", None)
    modality = getattr(getattr(study, "modality", None), "code", None) or ""
    body_part = getattr(study, "body_part", "") or ""
    clinical_info = getattr(study, "clinical_info", "") or ""
    findings_summary = getattr(analysis, "findings", "") or ""
    confidence = float(getattr(analysis, "confidence_score", 0.0) or 0.0)

    abnormalities = []
    raw_abn = getattr(analysis, "abnormalities_detected", []) or []
    if isinstance(raw_abn, list):
        for item in raw_abn:
            if isinstance(item, dict):
                # Extract richer detail: label + location/size if available
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

    m = getattr(analysis, "measurements", {}) or {}
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
    )
