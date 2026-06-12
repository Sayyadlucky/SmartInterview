from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from django.contrib.auth.models import AnonymousUser, User
from django.db import transaction

from smartInterviewApp.models import (
    LitioAssistantConversation,
    LitioAssistantKnowledge,
    LitioAssistantMessage,
)


SAFE_RESPONSE = (
    'I can help with Litio hiring workflows, candidate management, job posting, role matching, '
    'and dashboard guidance. I cannot share internal system details, provider information, '
    'private prompts, keys, formulas, or protection logic.'
)

UNKNOWN_RESPONSE = (
    'I do not have a confirmed Litio help article for that yet. Try asking about posting a job, '
    'assigning a candidate to a role, role fit scores, interviews, or candidate pipeline actions.'
)

SUGGESTIONS = [
    'How do I post a job?',
    'How do I assign a candidate to a role?',
    'How is role fit score explained?',
    'How do I map a candidate to a vacancy?',
]

TYPO_REPLACEMENTS = {
    'candiate': 'candidate',
    'candiadte': 'candidate',
    'rile': 'role',
    'rol': 'role',
    'vacany': 'vacancy',
    'vancancy': 'vacancy',
    'vacancie': 'vacancy',
    'asign': 'assign',
    'assing': 'assign',
    'tagg': 'tag',
    'jpb': 'job',
}

SENSITIVE_TERMS = {
    'api key',
    'apikey',
    'secret key',
    'provider',
    'openai',
    'model do you use',
    'ai model',
    'prompt',
    'system prompt',
    'internal formula',
    'formula',
    'fraud detection',
    'fraud-detection',
    'protection logic',
    'scoring internals',
}

CANDIDATE_JOB_MAPPING_PHRASES = {
    'how to tag candidate with job role',
    'tag candidate with job role',
    'assign candidate to role',
    'map candidate to vacancy',
    'link candidate with job',
}

DEFAULT_KNOWLEDGE = [
    {
        'intent_key': 'candidate_job_mapping',
        'title': 'Assign candidate to role',
        'priority': 1,
        'keywords': ['candidate', 'role', 'job', 'vacancy', 'assign', 'map', 'tag', 'link'],
        'answer': (
            'To assign a candidate to a role, open Candidates, choose the candidate, select the role or vacancy, '
            'and save the assignment. You can also use the bulk assignment action when mapping several candidates.'
        ),
    },
    {
        'intent_key': 'create_vacancy',
        'title': 'Post a job',
        'priority': 5,
        'keywords': ['post', 'job', 'create', 'vacancy', 'role', 'opening'],
        'answer': (
            'To post a job, open Job Postings and create a new vacancy with the role title, description, '
            'location, job type, experience, and open positions. Once saved, it appears as an active role.'
        ),
    },
    {
        'intent_key': 'role_fit_score',
        'title': 'Role fit score',
        'priority': 10,
        'keywords': ['role', 'fit', 'score', 'explain', 'explanation', 'matching'],
        'answer': (
            'Role fit score summarizes how well a candidate aligns with a selected role based on visible hiring '
            'signals such as skills, experience, role relevance, and available profile evidence. Use it as a '
            'decision aid alongside recruiter review.'
        ),
    },
    {
        'intent_key': 'candidate_pipeline',
        'title': 'Candidate pipeline',
        'priority': 30,
        'keywords': ['candidate', 'pipeline', 'status', 'shortlist', 'hired', 'rejected'],
        'answer': (
            'Use Candidate Management to review each candidate stage, search the pipeline, open profiles, '
            'schedule next steps, and update hiring status.'
        ),
    },
    {
        'intent_key': 'known_feature',
        'title': 'Litio AI Assistant',
        'priority': 40,
        'keywords': ['litio', 'assistant', 'help', 'dashboard'],
        'answer': (
            'Litio AI Assistant helps answer practical questions about using the hiring dashboard, jobs, '
            'candidate assignment, and role matching workflows.'
        ),
    },
]


@dataclass(frozen=True)
class AssistantResult:
    answer: str
    intent_key: str
    confidence: Decimal
    matched_title: str = ''


def normalize_query(value: str) -> str:
    text = (value or '').lower()
    text = re.sub(r'[^a-z0-9\s-]', ' ', text)
    words = []
    for word in text.replace('-', ' ').split():
        words.append(TYPO_REPLACEMENTS.get(word, word))
    return re.sub(r'\s+', ' ', ' '.join(words)).strip()


def _contains_sensitive_query(normalized: str) -> bool:
    return any(term in normalized for term in SENSITIVE_TERMS)


def _is_candidate_job_mapping(normalized: str) -> bool:
    if normalized in CANDIDATE_JOB_MAPPING_PHRASES:
        return True
    tokens = set(normalized.split())
    has_candidate = 'candidate' in tokens
    has_job_target = bool(tokens & {'job', 'role', 'vacancy'})
    has_mapping_action = bool(tokens & {'assign', 'map', 'tag', 'link'})
    return has_candidate and has_job_target and has_mapping_action


def _is_role_fit_score(normalized: str) -> bool:
    tokens = set(normalized.split())
    has_score = bool(tokens & {'score', 'scoring'})
    has_role_fit = 'role' in tokens and 'fit' in tokens
    asks_explanation = bool(tokens & {'explain', 'explanation', 'calculate', 'mean', 'means'})
    return has_score and (has_role_fit or asks_explanation)


def _is_create_vacancy(normalized: str) -> bool:
    if 'post a job' in normalized or 'post job' in normalized:
        return True
    tokens = set(normalized.split())
    return bool(tokens & {'create', 'post', 'add'}) and bool(tokens & {'vacancy', 'job', 'role'})


def _iter_knowledge() -> Iterable[dict]:
    rows = LitioAssistantKnowledge.objects.filter(is_active=True).order_by('priority', 'title')
    yielded_intents = set()
    for row in rows:
        yielded_intents.add(row.intent_key)
        yield {
            'intent_key': row.intent_key,
            'title': row.title,
            'priority': row.priority,
            'keywords': row.keywords or [],
            'question_patterns': row.question_patterns or [],
            'answer': row.answer,
        }
    for item in DEFAULT_KNOWLEDGE:
        if item['intent_key'] not in yielded_intents:
            yield item


def _knowledge_score(normalized: str, item: dict) -> int:
    if not normalized:
        return 0
    patterns = [normalize_query(pattern) for pattern in item.get('question_patterns') or []]
    if normalized in patterns:
        return 100
    score = 0
    for pattern in patterns:
        if pattern and (pattern in normalized or normalized in pattern):
            score = max(score, 80)
    tokens = set(normalized.split())
    keywords = {normalize_query(keyword) for keyword in item.get('keywords') or []}
    keyword_hits = len(tokens & keywords)
    if keyword_hits:
        score = max(score, keyword_hits * 18)
    return score


class LitioAssistantService:
    def answer(self, question: str) -> AssistantResult:
        normalized = normalize_query(question)
        if not normalized:
            return AssistantResult(UNKNOWN_RESPONSE, 'unknown', Decimal('0.00'))
        if _contains_sensitive_query(normalized):
            return AssistantResult(SAFE_RESPONSE, 'protected', Decimal('1.00'))
        if _is_candidate_job_mapping(normalized):
            item = next(entry for entry in DEFAULT_KNOWLEDGE if entry['intent_key'] == 'candidate_job_mapping')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.99'), item['title'])
        if _is_role_fit_score(normalized):
            item = next(entry for entry in DEFAULT_KNOWLEDGE if entry['intent_key'] == 'role_fit_score')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.93'), item['title'])
        if _is_create_vacancy(normalized):
            item = next(entry for entry in DEFAULT_KNOWLEDGE if entry['intent_key'] == 'create_vacancy')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.94'), item['title'])

        best_item = None
        best_score = 0
        for item in _iter_knowledge():
            score = _knowledge_score(normalized, item)
            if score > best_score:
                best_score = score
                best_item = item

        if best_item and best_score >= 36:
            confidence = min(Decimal('0.90'), Decimal(best_score) / Decimal('100'))
            return AssistantResult(best_item['answer'], best_item['intent_key'], confidence, best_item.get('title', ''))
        return AssistantResult(UNKNOWN_RESPONSE, 'unknown', Decimal('0.00'))

    @transaction.atomic
    def chat(
        self,
        *,
        question: str,
        user: User | AnonymousUser | None = None,
        conversation_id: int | None = None,
    ) -> dict:
        user_obj = user if getattr(user, 'is_authenticated', False) else None
        conversation = self._get_or_create_conversation(question, user_obj, conversation_id)
        user_message = LitioAssistantMessage.objects.create(
            conversation=conversation,
            sender=LitioAssistantMessage.Sender.USER,
            content=question.strip(),
        )
        result = self.answer(question)
        assistant_message = LitioAssistantMessage.objects.create(
            conversation=conversation,
            sender=LitioAssistantMessage.Sender.ASSISTANT,
            content=result.answer,
            intent_key=result.intent_key,
            confidence=result.confidence,
            metadata={'matched_title': result.matched_title},
        )
        conversation.save(update_fields=['updated_at'])
        return {
            'conversation_id': conversation.id,
            'user_message_id': user_message.id,
            'assistant_message_id': assistant_message.id,
            'answer': result.answer,
            'intent_key': result.intent_key,
            'confidence': float(result.confidence),
            'suggestions': SUGGESTIONS,
        }

    def _get_or_create_conversation(
        self,
        question: str,
        user: User | None,
        conversation_id: int | None,
    ) -> LitioAssistantConversation:
        if conversation_id:
            conversation = LitioAssistantConversation.objects.filter(id=conversation_id).first()
            if conversation and (not conversation.user_id or not user or conversation.user_id == user.id):
                return conversation
        title = question.strip()[:160] or 'Litio Assistant Chat'
        return LitioAssistantConversation.objects.create(user=user, title=title)

