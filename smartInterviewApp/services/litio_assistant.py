from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from smartInterviewApp.models import (
    CompanyProfile,
    LitioAssistantConversation,
    LitioAssistantFeedback,
    LitioAssistantKnowledge,
    LitioAssistantMessage,
)


QUICK_CHIPS = [
    'Create a vacancy',
    'Add candidates',
    'Explain AI Talent Pool',
    'Assign Litio interview',
    'Assign aptitude test',
    'Understand candidate scores',
    'Share feedback',
]

SAFE_FALLBACK = (
    "I couldn't find an approved Shortlistii help answer for that yet. "
    "Try asking about vacancies, candidates, AI Talent Pool, interviews, aptitude tests, reports, reminders, or feedback."
)

SENSITIVE_RESPONSE = (
    'I can explain this from a user workflow perspective, but internal system details are protected for security and reliability.'
)

SENSITIVE_PATTERNS = [
    r'\bapi\s*key\b',
    r'\bsecret\b',
    r'\btoken\b',
    r'\bprompt\b',
    r'\bhidden instructions?\b',
    r'\bmodel\b',
    r'\bprovider\b',
    r'\bdatabase schema\b',
    r'\bschema\b',
    r'\bbackend architecture\b',
    r'\binfrastructure\b',
    r'\bscoring formula\b',
    r'\bexact formula\b',
    r'\bfraud\b',
    r'\bintegrity detection\b',
    r'\badmin-only\b',
    r'\binternal logic\b',
]

INTENT_KEYWORDS = {
    'troubleshooting': {'issue', 'problem', 'not received', 'did not receive', 'camera', 'mic', 'microphone', 'permission', 'troubleshoot'},
    'score_explanation': {'score', 'resume score', 'role fit', 'fit score', 'marks', 'passing'},
    'workflow_recommendation': {'workflow', 'next step', 'recommend', 'assign', 'status', 'reminder'},
    'navigation_help': {'where', 'open', 'go to', 'find', 'navigate'},
    'feedback': {'feedback', 'confusing', 'missing', 'not working', 'suggestion'},
    'how_to': {'how', 'create', 'add', 'upload', 'schedule', 'review', 'send'},
}

DEFAULT_SUGGESTIONS = [
    'Create a vacancy',
    'Add candidates',
    'Assign Litio interview',
    'Understand candidate scores',
]

CATEGORY_SUGGESTIONS = {
    'vacancy': ['Add candidates', 'Explain AI Talent Pool', 'Assign Litio interview'],
    'candidate': ['Understand candidate scores', 'Assign aptitude test', 'Review reports'],
    'interview': ['Assign aptitude test', 'Review reports', 'Send reminders'],
    'assessment': ['Understand candidate scores', 'Review reports', 'Troubleshoot candidate link'],
    'feedback': ['Create a vacancy', 'Add candidates', 'Explain AI Talent Pool'],
}


@dataclass(frozen=True)
class AssistantMatch:
    knowledge: LitioAssistantKnowledge | None
    intent: str
    confidence: float


def resolve_user_company(user: User) -> CompanyProfile | None:
    profile = getattr(user, 'profile', None)
    if profile and getattr(profile, 'company_id', None):
        return profile.company
    if hasattr(user, 'company_profile'):
        return user.company_profile
    hr = getattr(profile, 'hr', None) if profile else None
    hr_profile = getattr(hr, 'profile', None)
    if hr_profile and getattr(hr_profile, 'company_id', None):
        return hr_profile.company
    if hr and hasattr(hr, 'company_profile'):
        return hr.company_profile
    return None


def classify_intent(message: str) -> str:
    lowered = message.lower()
    if is_sensitive_query(lowered):
        return 'sensitive_internal_query'
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return intent
    return 'feature_help'


def is_sensitive_query(message: str) -> bool:
    return any(re.search(pattern, message, flags=re.IGNORECASE) for pattern in SENSITIVE_PATTERNS)


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r'[a-z0-9]+', value.lower()) if len(token) > 2}


def _knowledge_score(message: str, message_tokens: set[str], knowledge: LitioAssistantKnowledge) -> float:
    haystacks = [
        knowledge.title,
        knowledge.category,
        knowledge.short_answer,
        knowledge.detailed_answer,
        ' '.join(str(item) for item in (knowledge.question_patterns or [])),
    ]
    searchable = ' '.join(haystacks).lower()
    score = 0.0
    for pattern in knowledge.question_patterns or []:
        pattern_text = str(pattern).strip().lower()
        if not pattern_text:
            continue
        if pattern_text in message:
            score += 4.0
        pattern_tokens = _tokens(pattern_text)
        if pattern_tokens:
            overlap = len(message_tokens & pattern_tokens)
            score += overlap / max(len(pattern_tokens), 1)
    knowledge_tokens = _tokens(searchable)
    if knowledge_tokens:
        score += min(len(message_tokens & knowledge_tokens), 6) * 0.35
    score += max(0, 120 - knowledge.priority) / 250
    return score


def match_knowledge(message: str) -> AssistantMatch:
    lowered = message.lower().strip()
    intent = classify_intent(lowered)
    if intent == 'sensitive_internal_query':
        return AssistantMatch(None, intent, 1.0)

    message_tokens = _tokens(lowered)
    best: LitioAssistantKnowledge | None = None
    best_score = 0.0
    for knowledge in LitioAssistantKnowledge.objects.filter(is_active=True).order_by('priority', 'title'):
        score = _knowledge_score(lowered, message_tokens, knowledge)
        if score > best_score:
            best = knowledge
            best_score = score

    confidence = min(best_score / 4.0, 1.0)
    if not best or best_score < 1.7:
        return AssistantMatch(None, 'unsupported' if intent == 'feature_help' else intent, confidence)
    return AssistantMatch(best, intent, confidence)


def build_answer(knowledge: LitioAssistantKnowledge | None, intent: str) -> str:
    if intent == 'sensitive_internal_query':
        return SENSITIVE_RESPONSE
    if not knowledge:
        return SAFE_FALLBACK

    parts = [knowledge.short_answer.strip()]
    if knowledge.detailed_answer.strip():
        parts.append(knowledge.detailed_answer.strip())
    steps = [str(step).strip() for step in (knowledge.steps or []) if str(step).strip()]
    if steps:
        parts.append('\n'.join(f'{index}. {step}' for index, step in enumerate(steps, start=1)))
    return '\n\n'.join(part for part in parts if part)


def suggestions_for(category: str) -> list[str]:
    return CATEGORY_SUGGESTIONS.get(category, DEFAULT_SUGGESTIONS)


@transaction.atomic
def answer_message(
    *,
    user: User,
    message: str,
    conversation_id: int | None = None,
    page_context: str = '',
    page_url: str = '',
) -> dict[str, Any]:
    cleaned_message = (message or '').strip()
    if not cleaned_message:
        raise ValueError('Message is required.')
    if len(cleaned_message) > 3000:
        cleaned_message = cleaned_message[:3000]

    company = resolve_user_company(user)
    conversation = None
    if conversation_id:
        conversation = LitioAssistantConversation.objects.filter(id=conversation_id, user=user).first()
    if not conversation:
        conversation = LitioAssistantConversation.objects.create(
            user=user,
            company=company,
            page_context=page_context[:160],
            page_url=page_url[:1000],
        )
    else:
        updates = []
        if page_context and conversation.page_context != page_context[:160]:
            conversation.page_context = page_context[:160]
            updates.append('page_context')
        if page_url and conversation.page_url != page_url[:1000]:
            conversation.page_url = page_url[:1000]
            updates.append('page_url')
        if company and conversation.company_id != company.id:
            conversation.company = company
            updates.append('company')
        if updates:
            conversation.save(update_fields=updates)

    user_message = LitioAssistantMessage.objects.create(
        conversation=conversation,
        sender=LitioAssistantMessage.Sender.USER,
        message=cleaned_message,
    )
    match = match_knowledge(cleaned_message)
    answer = build_answer(match.knowledge, match.intent)
    category = match.knowledge.category if match.knowledge else match.intent
    assistant_message = LitioAssistantMessage.objects.create(
        conversation=conversation,
        sender=LitioAssistantMessage.Sender.ASSISTANT,
        message=answer,
        intent=match.intent,
        matched_knowledge=match.knowledge,
        confidence=match.confidence,
    )
    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=['last_message_at'])

    return {
        'conversation_id': conversation.id,
        'message_id': assistant_message.id,
        'user_message_id': user_message.id,
        'answer': answer,
        'intent': match.intent,
        'category': category,
        'confidence': match.confidence,
        'suggestions': suggestions_for(category),
        'show_feedback': True,
    }


@transaction.atomic
def save_feedback(
    *,
    user: User,
    conversation_id: int,
    rating: str,
    comment: str = '',
    message_id: int | None = None,
    page_context: str = '',
    page_url: str = '',
) -> LitioAssistantFeedback:
    if rating not in LitioAssistantFeedback.Rating.values:
        raise ValueError('Invalid feedback rating.')
    conversation = LitioAssistantConversation.objects.filter(id=conversation_id, user=user).first()
    if not conversation:
        raise LookupError('Conversation not found.')
    message = None
    if message_id:
        message = LitioAssistantMessage.objects.filter(id=message_id, conversation=conversation).first()

    feedback = LitioAssistantFeedback.objects.create(
        user=user,
        conversation=conversation,
        message=message,
        rating=rating,
        comment=(comment or '').strip()[:2000],
        page_context=(page_context or conversation.page_context)[:160],
        page_url=(page_url or conversation.page_url)[:1000],
        feature_area=getattr(message.matched_knowledge, 'category', '') if message else '',
    )
    conversation.feedback_rating = rating
    if comment:
        conversation.feedback_summary = comment[:1000]
        conversation.save(update_fields=['feedback_rating', 'feedback_summary'])
    else:
        conversation.save(update_fields=['feedback_rating'])
    return feedback
