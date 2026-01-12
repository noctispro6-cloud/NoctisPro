from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple

from django.utils import timezone


def _as_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _normalize_abnormality_label(item: Any) -> str:
    try:
        if isinstance(item, dict):
            for key in ("label", "type", "name", "finding"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
            return ""
        if isinstance(item, str):
            return item.strip()
        return str(item).strip()
    except Exception:
        return ""


def _fmt_measurements(measurements: Any) -> Iterable[Tuple[str, str]]:
    if not isinstance(measurements, dict):
        return []
    for k, v in measurements.items():
        if k in ("overlays", "reference_suggestions", "online_references", "report"):
            continue
        if k.startswith("triage_"):
            continue
        if v is None:
            continue
        try:
            if isinstance(v, (dict, list)):
                continue
            yield (str(k).replace("_", " ").title(), str(v))
        except Exception:
            continue


def build_report_sections_from_analysis(analysis) -> Dict[str, str]:
    """
    Build a human-readable preliminary report from an AIAnalysis.

    Note: intentionally deterministic + local (no external LLM calls).
    """
    study = getattr(analysis, "study", None)
    modality = getattr(getattr(study, "modality", None), "code", None) or "Study"
    body_part = (getattr(study, "body_part", "") or "").strip()
    clinical = (getattr(study, "clinical_info", "") or "").strip()

    conf = float(getattr(analysis, "confidence_score", 0.0) or 0.0)
    abnormalities = [_normalize_abnormality_label(a) for a in _as_list(getattr(analysis, "abnormalities_detected", []))]
    abnormalities = [a for a in abnormalities if a]

    m = getattr(analysis, "measurements", {}) or {}
    triage_level = (m.get("triage_level") or "").strip().lower()
    triage_score = m.get("triage_score")
    flagged = bool(m.get("triage_flagged"))

    # References (local + optional online)
    references_lines: list[str] = []
    try:
        refs = (m.get("reference_suggestions") or [])
        if isinstance(refs, list) and refs:
            references_lines.append("Selected references:")
            for r in refs[:6]:
                if isinstance(r, dict):
                    title = (r.get("title") or "").strip()
                    topic = (r.get("topic") or "").strip()
                    if title and topic:
                        references_lines.append(f"- {title} — {topic}")
                    elif title:
                        references_lines.append(f"- {title}")
                elif isinstance(r, str) and r.strip():
                    references_lines.append(f"- {r.strip()}")
        online = (m.get("online_references") or [])
        if isinstance(online, list) and online:
            references_lines.append("Online references (best-effort):")
            for r in online[:4]:
                if isinstance(r, dict):
                    title = (r.get("title") or "").strip()
                    url = (r.get("url") or "").strip()
                    source = (r.get("source") or "").strip()
                    if title and url:
                        label = f"{title} ({source})" if source else title
                        references_lines.append(f"- {label}: {url}")
    except Exception:
        references_lines = []

    # Findings
    lines: list[str] = []
    header = f"{modality}"
    if body_part:
        header += f" {body_part}"
    lines.append(header)
    if clinical:
        lines.append(f"Clinical information: {clinical}")
    summary = (getattr(analysis, "findings", "") or "").strip()
    if summary:
        lines.append(f"AI summary: {summary}")

    if abnormalities:
        lines.append("Detected abnormalities:")
        for a in abnormalities[:15]:
            lines.append(f"- {a}")

    meas = list(_fmt_measurements(m))
    if meas:
        lines.append("Measurements / structured outputs:")
        for k, v in meas[:20]:
            lines.append(f"- {k}: {v}")

    if triage_level:
        tri = f"AI triage: {triage_level.upper()}"
        if triage_score is not None:
            tri += f" (score {triage_score})"
        if flagged:
            tri += " [FLAGGED]"
        lines.append(tri)

    findings_text = "\n".join(lines).strip()
    if references_lines:
        findings_text = (findings_text + "\n\n" + "\n".join(references_lines)).strip()

    # Impression (keep it conservative)
    if triage_level in ("urgent", "high") or flagged:
        impression = (
            "Potentially significant abnormality flagged by AI. "
            "Priority radiologist review is recommended."
        )
    elif abnormalities:
        impression = "Abnormality suspected by AI. Correlate clinically and confirm on full review."
    else:
        impression = "No acute abnormality detected by AI. Correlate clinically."

    # Recommendations
    recs: list[str] = []
    if triage_level == "urgent":
        recs.append("Immediate radiologist review and clinical correlation.")
    elif triage_level == "high":
        recs.append("Expedited radiologist review.")
    else:
        recs.append("Routine radiologist review.")
    if conf and conf < 0.65:
        recs.append("Low/medium confidence: interpret cautiously and consider additional imaging/clinical correlation.")
    recommendations = "\n".join(f"- {r}" for r in recs)

    disclaimer = (
        "AI-generated preliminary report. For clinical decision support only. "
        "Not a substitute for radiologist interpretation."
    )

    return {
        "findings": findings_text,
        "impression": impression,
        "recommendations": recommendations,
        "disclaimer": disclaimer,
    }


def render_report_text(sections: Dict[str, str]) -> str:
    parts = [
        "FINDINGS",
        sections.get("findings", "").strip(),
        "",
        "IMPRESSION",
        sections.get("impression", "").strip(),
        "",
        "RECOMMENDATIONS",
        sections.get("recommendations", "").strip(),
        "",
        "DISCLAIMER",
        sections.get("disclaimer", "").strip(),
    ]
    return "\n".join(parts).strip()


def persist_report_on_analysis(analysis) -> Dict[str, Any]:
    """
    Store report in analysis.measurements['report'] and return it.
    """
    sections = build_report_sections_from_analysis(analysis)
    text = render_report_text(sections)

    m = getattr(analysis, "measurements", {}) or {}
    if not isinstance(m, dict):
        m = {}
    m["report"] = {
        "version": 1,
        "generated_at": timezone.now().isoformat(),
        "confidence": float(getattr(analysis, "confidence_score", 0.0) or 0.0),
        **sections,
        "text": text,
    }
    analysis.measurements = m
    analysis.save(update_fields=["measurements"])
    return m["report"]


def generate_report_content(study, analyses, template=None) -> Dict[str, Any]:
    """
    Backwards-compatible helper for views.generate_auto_report.
    Produces dict with findings/impression/recommendations/confidence.
    """
    primary = analyses.first() if hasattr(analyses, "first") else (analyses[0] if analyses else None)
    if not primary:
        return {"findings": "", "impression": "", "recommendations": "", "confidence": 0.0}

    report = (getattr(primary, "measurements", {}) or {}).get("report") or {}
    if not report:
        # Build on the fly (no persistence here)
        sections = build_report_sections_from_analysis(primary)
        report = {**sections, "confidence": float(getattr(primary, "confidence_score", 0.0) or 0.0)}

    return {
        "findings": report.get("findings", "") or "",
        "impression": report.get("impression", "") or "",
        "recommendations": report.get("recommendations", "") or "",
        "confidence": float(getattr(primary, "confidence_score", 0.0) or 0.0),
    }

