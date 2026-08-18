from __future__ import annotations

import json
import os
import re

import httpx

from app.models.records import (
    ClassificationSource,
    NumberKind,
    PhoneOccurrence,
    UniquePhone,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Deterministic keyword classifier. Labels match the inventory categories.
CLASSIFICATION_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Emergency", ("emergency", "911", "crisis")),
    ("Campus Safety", ("campus safety", "public safety", "police", "security dispatch")),
    ("Admissions", ("admissions", "enrollment", "prospective student")),
    ("Registrar", ("registrar", "transcript", "records office")),
    ("Financial Aid", ("financial aid", "fafsa", "scholarships office")),
    ("Student Services", ("student services", "student affairs", "dean of students")),
    ("IT Support", ("help desk", "itsupport", "it support", "technology services", "information technology")),
    ("Human Resources", ("human resources", "hr office", "benefits")),
    ("Library", ("library", "circulation desk")),
    ("Athletics", ("athletics", "athletic department", "sports information")),
    ("Faculty", ("faculty", "professor", "instructor")),
    ("Staff", ("staff directory", "staff office", "staff phone", "employee directory")),
    ("Department", ("department of", "school of", "college of", "academic department")),
    ("General Information", ("main office", "switchboard", "information desk", "operator", "general information")),
]

FAX_HINT = re.compile(r"\bfax(?:es|imile)?\b", re.I)
VOICE_HINT = re.compile(r"\b(voice|phone|tel|telephone|call|office line)\b", re.I)


def _blob(phone: UniquePhone) -> str:
    parts = [
        " ".join(phone.sample_contexts),
        " ".join(phone.nearest_headings),
        " ".join(phone.page_titles),
    ]
    return " ".join(parts).lower()


def classify_kind(blob: str) -> NumberKind:
    if FAX_HINT.search(blob):
        return NumberKind.FAX
    if VOICE_HINT.search(blob):
        return NumberKind.VOICE
    return NumberKind.UNKNOWN


def classify_with_rules(phone: UniquePhone) -> UniquePhone:
    blob = _blob(phone)
    phone.number_kind = classify_kind(blob)
    for label, keywords in CLASSIFICATION_RULES:
        if any(keyword in blob for keyword in keywords):
            phone.classification = label
            phone.category = label
            phone.classification_source = ClassificationSource.RULES
            phone.classification_confidence = 0.7
            phone.departments_or_context = _departments_or_context(phone, label)
            return phone
    phone.classification = "Unknown"
    phone.category = "Unknown"
    phone.classification_source = ClassificationSource.UNCLASSIFIED
    phone.classification_confidence = 0.2
    phone.departments_or_context = _departments_or_context(phone, "Unknown")
    return phone


def _departments_or_context(phone: UniquePhone, label: str) -> str:
    context = phone.sample_contexts[0] if phone.sample_contexts else ""
    if context:
        return f"{label}: {context[:240]}"
    return label


def classify_inventory(phones: list[UniquePhone]) -> list[UniquePhone]:
    return [classify_with_rules(phone) for phone in phones]


async def classify_with_ai(
    phones: list[UniquePhone],
    occurrences: list[PhoneOccurrence],
) -> list[UniquePhone]:
    """Optional second layer. Never used during crawling. Requires OPENAI_API_KEY."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("classify_ai_skipped", reason="missing_openai_api_key")
        return phones
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    unlabeled = [phone for phone in phones if phone.classification_source != ClassificationSource.RULES]
    if not unlabeled:
        return phones

    def prompt_for(phone: UniquePhone) -> str:
        return (
            "Classify this published phone number into a short institutional function "
            "label such as Admissions, Registrar, Campus Safety, or Unknown. "
            "Return JSON with keys classification, number_kind (VOICE|FAX|UNKNOWN), confidence (0-1).\n"
            f"Number: {phone.e164_phone or phone.normalized_phone}\n"
            f"Context: {' | '.join(phone.sample_contexts[:3])}\n"
            f"Headings: {' | '.join(phone.nearest_headings[:3])}\n"
        )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for phone in unlabeled[:200]:
            try:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {
                                "role": "system",
                                "content": "You classify publicly published phone numbers from website context.",
                            },
                            {"role": "user", "content": prompt_for(phone)},
                        ],
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                phone.classification = str(data.get("classification") or "Unknown")
                phone.category = phone.classification
                kind = str(data.get("number_kind") or "UNKNOWN").upper()
                if kind in NumberKind.__members__:
                    phone.number_kind = NumberKind[kind]
                phone.classification_source = ClassificationSource.AI
                phone.classification_confidence = float(data.get("confidence") or 0.5)
                phone.departments_or_context = _departments_or_context(phone, phone.category)
            except Exception as exc:
                logger.warning("classify_ai_failed", error=str(exc), phone=phone.e164_phone)
    return phones
