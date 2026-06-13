from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from difflib import get_close_matches
from typing import Any, Iterable

from django.contrib.auth.models import AnonymousUser, User
from django.db import transaction

from smartInterviewApp.models import (
    LitioAssistantConversation,
    LitioAssistantKnowledge,
    LitioAssistantMessage,
    LitioAssistantKnowledgeGap,
)
from smartInterviewApp.services.litio_data_intents import answer_data_question as _answer_data_question


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
    'candidat': 'candidate',
    'rile': 'role',
    'jib': 'job',
    'joob': 'job',
    'jpb': 'job',
    'rol': 'role',
    'vacnacy': 'vacancy',
    'vacency': 'vacancy',
    'vacany': 'vacancy',
    'vancancy': 'vacancy',
    'vacancie': 'vacancy',
    'opning': 'opening',
    'opprtunity': 'opportunity',
    'recruter': 'recruiter',
    'recruitor': 'recruiter',
    'asign': 'assign',
    'assing': 'assign',
    'assgin': 'assign',
    'mathc': 'match',
    'macth': 'match',
    'tagg': 'tag',
    'intervew': 'interview',
    'interviw': 'interview',
    'intrview': 'interview',
    'evalution': 'evaluation',
    'evluation': 'evaluation',
    'scor': 'score',
    'aptitute': 'aptitude',
    'aptitudee': 'aptitude',
    'resum': 'resume',
    'whatsap': 'whatsapp',
    'watsapp': 'whatsapp',
    'mesage': 'message',
    'remider': 'reminder',
}

PHRASE_REPLACEMENTS = {
    'rolefit': 'role fit',
    'role fit score': 'role fit score',
    'resume score': 'resume score',
    'fit score': 'role fit score',
    'candidate fit': 'role fit',
    'map candidate': 'assign candidate',
    'tag candidate': 'assign candidate',
    'link candidate': 'assign candidate',
    'post a job': 'create vacancy',
    'post job': 'create vacancy',
    'add job': 'create vacancy',
    'create job': 'create vacancy',
    'new opening': 'create vacancy',
    'auto interview': 'litio interview',
    'ai interview': 'litio interview',
    'aptitude exam': 'aptitude test',
    'assessment test': 'aptitude test',
    'whats app': 'whatsapp',
}

SYNONYM_REPLACEMENTS = {
    'vacancies': 'vacancy',
    'jobs': 'job',
    'roles': 'role',
    'openings': 'opening',
    'opportunities': 'opportunity',
    'candidates': 'candidate',
    'recruiters': 'recruiter',
    'interviews': 'interview',
    'interviewing': 'interview',
    'assessments': 'assessment',
    'evaluations': 'evaluation',
    'reports': 'report',
    'scores': 'score',
    'scoring': 'score',
    'assigning': 'assign',
    'assigned': 'assign',
    'mapping': 'map',
    'mapped': 'map',
    'tagging': 'tag',
    'tagged': 'tag',
    'linking': 'link',
    'linked': 'link',
    'matching': 'match',
    'matched': 'match',
    'scheduling': 'schedule',
    'scheduled': 'schedule',
    'messages': 'message',
    'reminders': 'reminder',
    'updates': 'update',
    'statuses': 'status',
    'flags': 'flag',
    'warnings': 'warning',
    'signs': 'sign',
    'concerns': 'concern',
    'alerts': 'alert',
    'signals': 'signal',
    'behaviour': 'behavior',
    'behaviours': 'behavior',
    'recommendations': 'recommendation',
    'recommended': 'recommendation',
    'notifications': 'notification',
    'notified': 'notify',
    'notifies': 'notify',
    'actions': 'action',
}

INTENT_KEYWORDS = {
    'candidate_job_mapping': {'candidate', 'job', 'role', 'vacancy', 'assign', 'map', 'tag', 'link', 'match'},
    'create_vacancy': {'create', 'post', 'add', 'new', 'job', 'vacancy', 'role', 'opening', 'opportunity'},
    'role_fit_score': {'role', 'fit', 'score', 'match', 'candidate'},
    'resume_score': {'resume', 'score', 'profile'},
    'schedule_interview': {'schedule', 'interview', 'candidate', 'calendar'},
    'litio_interview': {'start', 'litio', 'auto', 'interview', 'screening'},
    'aptitude_test': {'aptitude', 'test', 'exam', 'assessment'},
    'evaluation_report': {'evaluation', 'report', 'feedback', 'result'},
    'evaluation_red_flags': {'red', 'flag', 'warning', 'sign', 'concern', 'integrity', 'alert', 'suspicious', 'behavior'},
    'next_hiring_step': {'next', 'step', 'action', 'proceed', 'move', 'forward', 'hiring', 'candidate'},
    'explain_recommendation': {'explain', 'recommendation', 'hire', 'decision', 'why', 'meaning', 'candidate'},
    'send_reminder': {'send', 'reminder', 'notify', 'notification', 'follow', 'up', 'candidate', 'interview', 'whatsapp', 'sms', 'status', 'update'},
    'communication_updates': {'whatsapp', 'sms', 'message', 'reminder', 'status', 'update'},
}

FUZZY_VOCABULARY = sorted({
    word
    for words in INTENT_KEYWORDS.values()
    for word in words
} | {
    'assistant',
    'dashboard',
    'interviewer',
    'recruiter',
    'recruitment',
})

SENSITIVE_TOKEN_SKIP = {
    'ai',
    'api',
    'key',
    'keys',
    'model',
    'models',
    'openai',
    'provider',
    'providers',
    'prompt',
    'prompts',
    'secret',
    'secrets',
    'system',
    'training',
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
        'intent_key': 'resume_score',
        'title': 'Resume score',
        'priority': 12,
        'keywords': ['resume', 'score', 'profile', 'candidate'],
        'answer': (
            'Resume score summarizes the visible strength and completeness of a candidate profile from the resume '
            'and available profile evidence. Use it as a screening signal alongside role fit score and recruiter review.'
        ),
    },
    {
        'intent_key': 'schedule_interview',
        'title': 'Schedule interview',
        'priority': 15,
        'keywords': ['schedule', 'interview', 'candidate', 'calendar'],
        'answer': (
            'To schedule an interview, open the candidate or pipeline record, choose the interview action, select the '
            'role, date, time, and participants, then save the schedule.'
        ),
    },
    {
        'intent_key': 'litio_interview',
        'title': 'Litio interview',
        'priority': 16,
        'keywords': ['litio', 'auto', 'interview', 'screening', 'start'],
        'answer': (
            'To start a Litio interview workflow, open the candidate interview area for the role and use the available '
            'Litio interview or auto-screening action when it is enabled for that candidate and vacancy.'
        ),
    },
    {
        'intent_key': 'aptitude_test',
        'title': 'Aptitude test',
        'priority': 18,
        'keywords': ['aptitude', 'test', 'exam', 'assessment', 'candidate'],
        'answer': (
            'Use aptitude tests to assess candidate reasoning and job-relevant aptitude. Assign an available aptitude '
            'test from the candidate or role workflow, then review the submitted result after completion.'
        ),
    },
    {
        'intent_key': 'evaluation_report',
        'title': 'Evaluation report',
        'priority': 20,
        'keywords': ['evaluation', 'report', 'feedback', 'result', 'interview'],
        'answer': (
            'Evaluation reports collect interview or assessment outcomes into a recruiter-facing summary. Open the '
            'candidate or interview record to review available scores, feedback, and result details.'
        ),
    },
    {
        'intent_key': 'evaluation_red_flags',
        'title': 'Evaluation red flags',
        'priority': 21,
        'keywords': ['red', 'flag', 'warning', 'sign', 'concern', 'integrity', 'alert', 'suspicious', 'behavior'],
        'answer': (
            'Red flags are warning signals shown in a candidate evaluation, such as incomplete or weak answers, '
            'low-confidence evidence, unusual interview behavior, integrity alerts, repeated off-screen activity, '
            'copy/paste or fullscreen exits, voice or face mismatch signals, or major gaps against the role. Treat '
            'them as review signals, not automatic rejection. Open the evaluation report, check the evidence and '
            'transcript summary, then decide whether to shortlist, follow up, or disqualify.'
        ),
    },
    {
        'intent_key': 'next_hiring_step',
        'title': 'Next hiring step',
        'priority': 22,
        'keywords': ['next', 'step', 'action', 'proceed', 'move', 'forward', 'hiring', 'candidate'],
        'answer': (
            'Use the next hiring step based on the candidate current stage and evidence. If the role fit and evaluation '
            'look strong, shortlist or schedule the next interview. If evidence is incomplete, add a follow-up note or '
            'ask for clarification. If major gaps or red flags are present, review the evaluation evidence before '
            'disqualifying. Shortlistii should support the recruiter decision, not make the final decision automatically.'
        ),
    },
    {
        'intent_key': 'explain_recommendation',
        'title': 'Explain recommendation',
        'priority': 23,
        'keywords': ['explain', 'recommendation', 'hire', 'decision', 'why', 'meaning', 'candidate'],
        'answer': (
            'The recommendation summarizes the available hiring evidence for the candidate, including role fit, interview '
            'answers, evaluation signals, and visible gaps. Treat it as a recruiter review aid. Open the evaluation report, '
            'check the evidence behind the recommendation, compare it with role requirements, and then decide whether to '
            'shortlist, follow up, schedule another round, or reject.'
        ),
    },
    {
        'intent_key': 'send_reminder',
        'title': 'Send reminder',
        'priority': 24,
        'keywords': ['send', 'reminder', 'notify', 'notification', 'follow', 'up', 'candidate', 'interview', 'whatsapp', 'sms', 'status', 'update'],
        'answer': (
            'Interview reminders are sent automatically based on the scheduled interview time. Shortlistii/Litio triggers '
            'candidate reminders before the interview, including around 60 minutes, 30 minutes, and 15 minutes before the '
            'scheduled start. To make sure reminders work correctly, confirm that the interview is scheduled, the candidate '
            'contact details are valid, and the required communication channels are configured. There is no separate manual '
            'reminder step unless a manual send action is available in your workflow.'
        ),
    },
    {
        'intent_key': 'communication_updates',
        'title': 'WhatsApp and SMS updates',
        'priority': 25,
        'keywords': ['whatsapp', 'sms', 'message', 'reminder', 'status', 'update'],
        'answer': (
            'Litio can use configured WhatsApp and SMS workflows for interview reminders and delivery/status updates. '
            'Check the interview schedule, reminder status, and candidate notification preferences when following up.'
        ),
    },
    {
        'intent_key': 'ai_talent_pool',
        'title': 'AI Talent Pool',
        'priority': 28,
        'keywords': ['ai', 'talent', 'pool', 'ai talent pool', 'candidate pool', 'litio', 'talent-pool'],
        'answer': (
            'AI Talent Pool provides an aggregated workspace for curated candidate matches and insights. Use the talent '
            'pool to explore suggested candidates, view matching signals, and surface candidates for roles or outreach.'
        ),
    },
    {
        'intent_key': 'dashboard_analytics',
        'title': 'Dashboard analytics',
        'priority': 29,
        'keywords': ['analytics', 'reports', 'dashboard', 'metrics', 'kpi', 'insights'],
        'answer': (
            'Dashboard analytics surface hiring KPIs and trends such as open roles, pipeline health, and pending actions. '
            'Use the analytics tab to filter dates, export reports, and identify areas that need recruiter attention.'
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
    text = (value or '').lower().strip()
    text = re.sub(r'[-_/]+', ' ', text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    words = []
    for word in text.split():
        normalized = TYPO_REPLACEMENTS.get(word, word)
        normalized = SYNONYM_REPLACEMENTS.get(normalized, normalized)
        if normalized == word:
            normalized = _fuzzy_normalize_token(word)
        words.append(normalized)

    text = re.sub(r'\s+', ' ', ' '.join(words)).strip()
    return _apply_phrase_replacements(text)


def _fuzzy_normalize_token(word: str) -> str:
    if len(word) < 4 or word in SENSITIVE_TOKEN_SKIP:
        return word
    match = get_close_matches(word, FUZZY_VOCABULARY, n=1, cutoff=0.84)
    return match[0] if match else word


def _apply_phrase_replacements(text: str) -> str:
    normalized = f' {text} '
    for source, target in sorted(PHRASE_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = re.sub(rf'\b{re.escape(source)}\b', target, normalized)
    return re.sub(r'\s+', ' ', normalized).strip()


def _contains_sensitive_query(normalized: str) -> bool:
    return any(term in normalized for term in SENSITIVE_TERMS)


def _is_candidate_job_mapping(normalized: str) -> bool:
    if normalized in CANDIDATE_JOB_MAPPING_PHRASES:
        return True
    tokens = set(normalized.split())
    has_candidate = 'candidate' in tokens
    has_job_target = bool(tokens & {'job', 'role', 'vacancy'})
    has_mapping_action = bool(tokens & {'assign', 'map', 'tag', 'link', 'match'})
    return has_candidate and has_job_target and has_mapping_action


def _is_role_fit_score(normalized: str) -> bool:
    tokens = set(normalized.split())
    has_score = bool(tokens & {'score', 'scoring'})
    has_role_fit = 'role' in tokens and 'fit' in tokens
    has_matching_context = 'match' in tokens and bool(tokens & {'candidate', 'role'})
    return has_score and (has_role_fit or has_matching_context)


def _is_resume_score(normalized: str) -> bool:
    tokens = set(normalized.split())
    return 'resume' in tokens and 'score' in tokens


def _is_schedule_interview(normalized: str) -> bool:
    tokens = set(normalized.split())
    return 'schedule' in tokens and 'interview' in tokens


def _is_litio_interview(normalized: str) -> bool:
    tokens = set(normalized.split())
    return 'interview' in tokens and bool(tokens & {'litio', 'auto', 'screening'}) and bool(tokens & {'start', 'schedule', 'litio', 'auto'})


def _is_aptitude_test(normalized: str) -> bool:
    tokens = set(normalized.split())
    return 'aptitude' in tokens and bool(tokens & {'test', 'exam', 'assessment'})


def _is_evaluation_report(normalized: str) -> bool:
    tokens = set(normalized.split())
    return 'evaluation' in tokens and bool(tokens & {'report', 'result', 'feedback'})


def _is_evaluation_red_flags(normalized: str) -> bool:
    tokens = set(normalized.split())
    phrases = {
        'red flag',
        'warning sign',
        'candidate concern',
        'integrity flag',
        'evaluation flag',
        'fraud signal',
        'interview alert',
        'suspicious behavior',
        'behavior alert',
    }
    if any(phrase in normalized for phrase in phrases):
        return True
    has_alert_signal = bool(tokens & {'flag', 'warning', 'concern', 'alert'})
    has_evaluation_context = bool(tokens & {'candidate', 'evaluation', 'interview', 'integrity', 'behavior', 'red'})
    return has_alert_signal and has_evaluation_context


def _is_next_hiring_step(normalized: str) -> bool:
    tokens = set(normalized.split())
    phrases = {
        'next hiring step',
        'next step',
        'what should i do next',
        'next action',
        'proceed candidate',
        'move forward',
        'hiring action',
    }
    if any(phrase in normalized for phrase in phrases):
        return True
    return bool(tokens & {'next', 'proceed'}) and bool(tokens & {'step', 'action', 'candidate', 'hiring'})


def _is_explain_recommendation(normalized: str) -> bool:
    tokens = set(normalized.split())
    phrases = {
        'explain recommendation',
        'hire recommendation',
        'recommendation meaning',
        'why recommendation',
        'why not recommendation',
        'decision recommendation',
    }
    if any(phrase in normalized for phrase in phrases):
        return True
    return 'recommendation' in tokens and bool(tokens & {'explain', 'hire', 'why', 'meaning', 'decision'})


def _is_send_reminder(normalized: str) -> bool:
    tokens = set(normalized.split())
    phrases = {
        'send reminder',
        'candidate reminder',
        'interview reminder',
        'whatsapp reminder',
        'sms reminder',
        'notify candidate',
        'follow up candidate',
        'status update',
    }
    if any(phrase in normalized for phrase in phrases):
        return True
    has_reminder = 'reminder' in tokens
    has_notify = bool(tokens & {'notify', 'notification'})
    has_follow_up = 'follow' in tokens and 'up' in tokens and 'candidate' in tokens
    has_status_update = 'status' in tokens and 'update' in tokens
    return has_reminder or has_notify or has_follow_up or has_status_update


def _is_communication_update(normalized: str) -> bool:
    tokens = set(normalized.split())
    has_channel = bool(tokens & {'whatsapp', 'sms', 'message'})
    has_update_or_reminder = bool(tokens & {'status', 'update', 'reminder'})
    return has_channel and has_update_or_reminder


def _is_create_vacancy(normalized: str) -> bool:
    if 'create vacancy' in normalized or 'post a job' in normalized or 'post job' in normalized:
        return True
    tokens = set(normalized.split())
    has_create_action = bool(tokens & {'create', 'post', 'add', 'new'})
    has_role_target = bool(tokens & {'vacancy', 'job', 'role', 'opening', 'opportunity'})
    return has_create_action and has_role_target


def _default_knowledge_item(intent_key: str) -> dict:
    return next(entry for entry in DEFAULT_KNOWLEDGE if entry['intent_key'] == intent_key)


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


SAFE_CONTEXT_KEYS = {
    'page',
    'section',
    'activeTab',
    'openModal',
    'vacancyId',
    'vacancyTitle',
    'candidateId',
    'candidateName',
    'candidateStage',
    'evaluationStatus',
}


def _sanitize_context(context: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(context, dict):
        return {}
    sanitized: dict[str, str] = {}
    for key in SAFE_CONTEXT_KEYS:
        value = context.get(key)
        if value is None:
            continue
        if not isinstance(value, (str, int, float, bool)):
            continue
        text = re.sub(r'\s+', ' ', str(value)).strip()[:120]
        if text:
            sanitized[key] = text
    return sanitized


def _context_text(context: dict[str, str]) -> str:
    return normalize_query(' '.join(context.values()))


def _has_vacancy_context(context: dict[str, str]) -> bool:
    text = _context_text(context)
    return bool(context.get('vacancyId') or context.get('vacancyTitle') or {'vacancy', 'role', 'talent', 'pool'} & set(text.split()))


def _has_candidate_context(context: dict[str, str]) -> bool:
    text = _context_text(context)
    return bool(context.get('candidateId') or context.get('candidateName') or {'candidate', 'profile', 'evaluation'} & set(text.split()))


def _has_evaluation_context(context: dict[str, str]) -> bool:
    text = _context_text(context)
    return bool({'evaluation', 'report', 'profile', 'score'} & set(text.split()) or context.get('evaluationStatus'))


def _has_aptitude_context(context: dict[str, str]) -> bool:
    return 'aptitude' in set(_context_text(context).split())


def _is_assignment_question(normalized: str) -> bool:
    tokens = set(normalized.split())
    return bool(tokens & {'assign', 'map', 'tag', 'link', 'match'}) and bool(tokens & {'candidate', 'here', 'this'})


def _is_score_question(normalized: str) -> bool:
    tokens = set(normalized.split())
    return 'score' in tokens and bool(tokens & {'mean', 'explain', 'this', 'role', 'fit', 'evaluation', 'recommendation'})


def _is_interview_question(normalized: str) -> bool:
    tokens = set(normalized.split())
    return 'interview' in tokens and bool(tokens & {'schedule', 'start', 'here', 'this', 'next', 'litio', 'auto'})


def _contextual_answer(normalized: str, context: dict[str, str]) -> AssistantResult | None:
    if not context:
        return None
    vacancy_title = context.get('vacancyTitle', '')
    vacancy_phrase = f' for {vacancy_title}' if vacancy_title else ''

    if _is_assignment_question(normalized) and _has_vacancy_context(context):
        return AssistantResult(
            (
                f'From this vacancy view{vacancy_phrase}, use the candidate assignment or matching action to add candidates '
                'to the role. Review the visible match signals, select the candidates you want to move forward, and save '
                'the assignment.'
            ),
            'candidate_job_mapping',
            Decimal('0.96'),
            'Assign candidate to role',
        )

    if _is_score_question(normalized) and (_has_candidate_context(context) or _has_evaluation_context(context)):
        return AssistantResult(
            (
                'On this candidate or evaluation view, the visible score is a recruiter-facing signal for fit or evaluation '
                'strength. Use it to prioritize review, then confirm against the candidate profile, interview feedback, '
                'and role requirements before deciding the next step.'
            ),
            'evaluation_report',
            Decimal('0.92'),
            'Evaluation score',
        )

    if _is_interview_question(normalized) and (_has_candidate_context(context) or _has_evaluation_context(context)):
        return AssistantResult(
            (
                'From this candidate context, use the interview or Litio interview action to schedule the next screening '
                'step. Confirm the role, time, participants, and notification settings before saving.'
            ),
            'schedule_interview',
            Decimal('0.91'),
            'Schedule interview',
        )

    if _is_aptitude_test(normalized) and (_has_candidate_context(context) or _has_aptitude_context(context)):
        return AssistantResult(
            (
                'From this candidate context, use the aptitude assessment action to assign the relevant test, then review '
                'the submitted result and status once the candidate completes it.'
            ),
            'aptitude_test',
            Decimal('0.91'),
            'Aptitude test',
        )

    return None


class LitioAssistantService:
    def answer(self, question: str, context: dict[str, Any] | None = None) -> AssistantResult:
        normalized = normalize_query(question)
        safe_context = _sanitize_context(context)
        if not normalized:
            return AssistantResult(UNKNOWN_RESPONSE, 'unknown', Decimal('0.00'))
        if _contains_sensitive_query(normalized):
            return AssistantResult(SAFE_RESPONSE, 'protected', Decimal('1.00'))
        # Data-intent handling is performed in chat() where the authenticated user is available.
        contextual_result = _contextual_answer(normalized, safe_context)
        if contextual_result:
            return contextual_result
        if _is_candidate_job_mapping(normalized):
            item = _default_knowledge_item('candidate_job_mapping')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.99'), item['title'])
        if _is_role_fit_score(normalized):
            item = _default_knowledge_item('role_fit_score')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.93'), item['title'])
        if _is_resume_score(normalized):
            item = _default_knowledge_item('resume_score')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.92'), item['title'])
        if _is_create_vacancy(normalized):
            item = _default_knowledge_item('create_vacancy')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.94'), item['title'])
        if _is_litio_interview(normalized):
            item = _default_knowledge_item('litio_interview')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.92'), item['title'])
        if _is_schedule_interview(normalized):
            item = _default_knowledge_item('schedule_interview')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.92'), item['title'])
        if _is_aptitude_test(normalized):
            item = _default_knowledge_item('aptitude_test')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.92'), item['title'])
        if _is_evaluation_red_flags(normalized):
            item = _default_knowledge_item('evaluation_red_flags')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.94'), item['title'])
        if _is_next_hiring_step(normalized):
            item = _default_knowledge_item('next_hiring_step')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.94'), item['title'])
        if _is_explain_recommendation(normalized):
            item = _default_knowledge_item('explain_recommendation')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.94'), item['title'])
        if _is_send_reminder(normalized):
            item = _default_knowledge_item('send_reminder')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.94'), item['title'])
        if _is_evaluation_report(normalized):
            item = _default_knowledge_item('evaluation_report')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.92'), item['title'])
        if _is_communication_update(normalized):
            item = _default_knowledge_item('communication_updates')
            return AssistantResult(item['answer'], item['intent_key'], Decimal('0.92'), item['title'])

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

    def chat(
        self,
        *,
        question: str,
        user: User | AnonymousUser | None = None,
        conversation_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict:
        safe_context = _sanitize_context(context)
        user_obj = user if getattr(user, 'is_authenticated', False) else None
        conversation = self._get_or_create_conversation(question, user_obj, conversation_id)
        user_message = LitioAssistantMessage.objects.create(
            conversation=conversation,
            sender=LitioAssistantMessage.Sender.USER,
            content=question.strip(),
            metadata={'dashboard_context': safe_context} if safe_context else {},
        )
        # Before falling back to knowledge, check sensitive and then data intents using the authenticated user.
        normalized = normalize_query(question)
        if _contains_sensitive_query(normalized):
            # sensitive handled by answer() as protected
            result = self.answer(question, safe_context)
        else:
            data_result = None
            try:
                data_result = _answer_data_question(user_obj, question, safe_context)
            except Exception:
                data_result = None
            if data_result and getattr(data_result, 'handled', False):
                if data_result.needs_clarification:
                    result = AssistantResult(data_result.clarification, 'data_clarification', Decimal('0.90'))
                else:
                    result = AssistantResult(data_result.answer, data_result.intent_key or 'data', Decimal('0.99'))
            else:
                result = self.answer(question, safe_context)
        assistant_message = LitioAssistantMessage.objects.create(
            conversation=conversation,
            sender=LitioAssistantMessage.Sender.ASSISTANT,
            content=result.answer,
            intent_key=result.intent_key,
            confidence=result.confidence,
            metadata={'matched_title': result.matched_title, 'dashboard_context': safe_context} if safe_context else {'matched_title': result.matched_title},
        )
        conversation.save(update_fields=['updated_at'])
        # Phase 3: create a knowledge gap record when assistant falls back with no confirmed help article
        try:
            if result.intent_key == 'unknown' and result.answer == UNKNOWN_RESPONSE:
                normalized = normalize_query(question)
                # Simple duplicate prevention: open gap with same normalized question and same user
                existing = LitioAssistantKnowledgeGap.objects.filter(
                    normalized_question=normalized,
                    status=LitioAssistantKnowledgeGap.Status.OPEN,
                    user=conversation.user,
                ).exists()
                if not existing:
                    company = None
                    user_obj = conversation.user if getattr(conversation, 'user', None) else None
                    try:
                        company = getattr(user_obj.profile, 'company', None) if user_obj else None
                    except Exception:
                        company = None
                    LitioAssistantKnowledgeGap.objects.create(
                        conversation=conversation,
                        message=user_message if user_message else None,
                        company=company,
                        user=user_obj,
                        original_question=question.strip(),
                        normalized_question=normalized,
                        context=safe_context or {},
                        fallback_reason='no_matching_knowledge',
                        status=LitioAssistantKnowledgeGap.Status.OPEN,
                    )
        except Exception:
            # Never allow knowledge gap creation errors to break the chat flow
            pass
        # include optional safe actions from data intents
        actions = []
        try:
            if data_result and getattr(data_result, 'actions', None):
                for a in data_result.actions:
                    # serialize allowed fields only
                    actions.append({
                        'label': getattr(a, 'label', '') or '',
                        'action_type': getattr(a, 'action_type', '') or '',
                        'route': getattr(a, 'route', '') or '',
                        'query_params': getattr(a, 'query_params', None) or None,
                        'entity_type': getattr(a, 'entity_type', '') or '',
                        'entity_id': getattr(a, 'entity_id', None),
                    })
        except Exception:
            actions = []

        return {
            'conversation_id': conversation.id,
            'user_message_id': user_message.id,
            'assistant_message_id': assistant_message.id,
            'answer': result.answer,
            'intent_key': result.intent_key,
            'confidence': float(result.confidence),
            'suggestions': SUGGESTIONS,
            'actions': actions,
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
