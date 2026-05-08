from __future__ import annotations

import json
import mimetypes
import re
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Literal
from xml.etree import ElementTree

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from smartInterviewApp.models import CandidateResume, CandidateResumeSection, Interview, UserProfile


SECTION_ALIASES = {
    'summary': ('summary', 'professional summary', 'profile summary'),
    'objective': ('objective', 'career objective'),
    'skills': ('skills', 'technical skills', 'technical expertise', 'technical stack', 'core skills', 'key skills'),
    'experience': ('experience', 'work experience', 'professional experience', 'employment history', 'work history'),
    'education': ('education', 'academic background', 'academics'),
    'projects': ('projects', 'academic projects', 'personal projects'),
    'internships': ('internships', 'internship'),
    'certifications': ('certifications', 'certificates'),
    'achievements': ('achievements', 'awards', 'accomplishments'),
    'languages': ('languages',),
    'links': ('links', 'profiles', 'online profiles'),
    'contact': ('contact', 'contact details', 'personal details', 'reference', 'references'),
}

CANONICAL_SECTION_BY_ALIAS = {
    alias: key
    for key, aliases in SECTION_ALIASES.items()
    for alias in aliases
}

EXPLICIT_HEADING_PATTERNS = [
    'PROFESSIONAL SUMMARY',
    'PROFILE SUMMARY',
    'CAREER OBJECTIVE',
    'WORK HISTORY',
    'WORK EXPERIENCE',
    'PROFESSIONAL EXPERIENCE',
    'EMPLOYMENT HISTORY',
    'TECHNICAL EXPERTISE',
    'TECHNICAL SKILLS',
    'TECHNICAL STACK',
    'CORE SKILLS',
    'KEY SKILLS',
    'SKILLS',
    'PROJECTS',
    'EDUCATION',
    'CERTIFICATIONS',
    'ACHIEVEMENTS',
    'LANGUAGES',
    'CONTACT DETAILS',
]

CURRENT_DATE_TOKENS = {'present', 'current', 'till date', 'till now', 'to date', 'ongoing'}
EMPLOYMENT_TYPE_VALUES = {
    'full_time',
    'internship',
    'contract',
    'freelance',
    'part_time',
    'apprenticeship',
    'temporary',
    'unknown',
}
TECHNICAL_EXPERTISE_KEYS = (
    'languages',
    'frameworks',
    'libraries',
    'databases',
    'tools',
    'cloud',
    'devops',
    'web_technologies',
    'testing',
    'other',
)
CANONICAL_SECTION_KEYS = {
    'summary',
    'objective',
    'skills',
    'technical_expertise',
    'experience',
    'projects',
    'education',
    'certifications',
    'achievements',
    'languages',
    'contact',
}
MONTH_NAME_TO_NUMBER = {
    'jan': 1,
    'january': 1,
    'feb': 2,
    'february': 2,
    'mar': 3,
    'march': 3,
    'apr': 4,
    'april': 4,
    'may': 5,
    'jun': 6,
    'june': 6,
    'jul': 7,
    'july': 7,
    'aug': 8,
    'august': 8,
    'sep': 9,
    'sept': 9,
    'september': 9,
    'oct': 10,
    'october': 10,
    'nov': 11,
    'november': 11,
    'dec': 12,
    'december': 12,
}
DATE_TOKEN_RE = re.compile(
    r'(?P<token>'
    r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s,./-]+\d{2,4}'
    r'|\d{4}[-/]\d{1,2}'
    r'|\d{4}'
    r'|present|current|till\s+date|till\s+now|to\s+date|ongoing'
    r')',
    re.IGNORECASE,
)
DATE_RANGE_RE = re.compile(
    r'(?P<start>'
    r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s,./-]+\d{2,4}'
    r'|\d{4}[-/]\d{1,2}'
    r'|\d{4}'
    r')\s*(?:-|–|—|to)\s*'
    r'(?P<end>'
    r'present|current|till\s+date|till\s+now|to\s+date|ongoing'
    r'|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s,./-]+\d{2,4}'
    r'|\d{4}[-/]\d{1,2}'
    r'|\d{4}'
    r')',
    re.IGNORECASE,
)
COMPANY_SUFFIX_RE = re.compile(r'\b(?:ltd|pvt|private limited|inc|llc|corp|corporation|limited)\b', re.IGNORECASE)
ROLE_TITLE_RE = re.compile(
    r'\b(?:software|python|java|backend|frontend|full stack|fullstack|devops|data|qa|test|machine learning|ml|ai)?\s*'
    r'(?:engineer|developer|intern|manager|lead|architect|consultant|analyst|specialist|administrator|designer)\b',
    re.IGNORECASE,
)
SKILL_PROSE_PHRASES = (
    'responsibilities',
    'description',
    'client',
    'worked on',
    'developed',
    'collaborated',
    'seeking',
    'objective',
    'professional summary',
    'advantage of the company',
)
KNOWN_EXTRA_SECTION_KEYS = {'overview', 'links', 'internships'}
EXPERIENCE_BULLET_VERBS = (
    'developed',
    'worked',
    'collaborated',
    'improved',
    'enhanced',
    'participated',
    'testing',
    'monitored',
    'monitoring',
    'performing',
    'built',
    'implemented',
    'designed',
    'maintained',
    'created',
    'delivered',
    'supported',
    'led',
    'managed',
    'automated',
    'analyzed',
    'documented',
)
ROLE_SIGNAL_RE = re.compile(
    r'\b(?:developer|engineer|manager|analyst|consultant|lead|architect|intern|administrator|specialist|designer|qa|tester|sde|executive)\b',
    re.IGNORECASE,
)
LOCATION_HINT_RE = re.compile(r'\b(?:remote|hybrid|onsite|india|usa|uk|bangalore|bengaluru|mumbai|pune|delhi|chennai|hyderabad)\b', re.IGNORECASE)


@dataclass
class ParsedResumePayload:
    provider: str
    data: dict[str, Any]


@dataclass
class OpenAIExtractionResult:
    payload: ParsedResumePayload | None
    attempted: bool
    configured: bool
    error: str
    raw_preview: str
    model: str


@dataclass(frozen=True)
class ParsedMonth:
    year: int
    month: int
    precision: Literal['month', 'year', 'current']

    @property
    def month_index(self) -> int:
        return self.year * 12 + (self.month - 1)

    def iso_value(self) -> str:
        return f'{self.year:04d}-{self.month:02d}'


@dataclass(frozen=True)
class ExperienceRange:
    start_index: int
    end_index: int
    employment_type: str


@dataclass(frozen=True)
class ExperienceCalculationResult:
    professional_months: int
    internship_months: int
    combined_months: int
    notes: list[str]


class ResumeProcessingError(Exception):
    pass


def _clean_string(value: Any) -> str:
    return str(value or '').strip()


def _clean_optional_string(value: Any) -> str | None:
    cleaned = _clean_string(value)
    return cleaned or None


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_string(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _empty_technical_expertise() -> dict[str, list[str]]:
    return {key: [] for key in TECHNICAL_EXPERTISE_KEYS}


def _has_sentence_punctuation_prose(text: str) -> bool:
    return bool(re.search(r'[.!?]\s+[a-z]', text))


def _is_likely_prose(text: str) -> bool:
    cleaned = _clean_string(text)
    if not cleaned:
        return False
    lowered = cleaned.casefold()
    if any(phrase in lowered for phrase in SKILL_PROSE_PHRASES):
        return True
    if _has_sentence_punctuation_prose(cleaned):
        return True
    if len(cleaned) > 70 and ':' not in cleaned:
        return True
    words = cleaned.split()
    if len(words) > 8 and not re.search(r'[+/#.]', cleaned):
        return True
    return False


def _is_likely_company_or_role_line(text: str) -> bool:
    cleaned = _clean_string(text)
    if not cleaned:
        return False
    if COMPANY_SUFFIX_RE.search(cleaned) and not re.search(r'\b(?:c\+\+|asp\.net|node\.js)\b', cleaned, re.IGNORECASE):
        return True
    if ROLE_TITLE_RE.search(cleaned) and len(cleaned.split()) <= 6:
        return True
    if ' at ' in cleaned.lower():
        return True
    return False


def _is_likely_skill_item(text: str) -> bool:
    cleaned = _clean_string(text).strip('• ').strip()
    if not cleaned:
        return False
    lowered = cleaned.casefold()
    if DATE_RANGE_RE.search(cleaned) or DATE_TOKEN_RE.search(cleaned):
        return False
    if '@' in cleaned:
        return False
    if any(phrase in lowered for phrase in SKILL_PROSE_PHRASES):
        return False
    if _is_likely_prose(cleaned):
        return False
    if _is_likely_company_or_role_line(cleaned):
        return False
    if len(cleaned) > 50 and ':' not in cleaned:
        return False
    if cleaned.count(',') >= 3:
        return False
    if len(cleaned.split()) > 6:
        return False
    return bool(re.search(r'[A-Za-z0-9+#./-]', cleaned))


def _has_strong_role_signal(line: str) -> bool:
    cleaned = _clean_string(line)
    if not cleaned:
        return False
    return bool(ROLE_SIGNAL_RE.search(cleaned) or re.search(r'\brole\s*:', cleaned, re.IGNORECASE))


def _has_strong_company_signal(line: str) -> bool:
    cleaned = _clean_string(line)
    if not cleaned:
        return False
    if COMPANY_SUFFIX_RE.search(cleaned):
        return True
    if ' at ' in cleaned.lower():
        return True
    if '|' in cleaned:
        parts = [part.strip() for part in cleaned.split('|') if part.strip()]
        return len(parts) >= 2 and any(COMPANY_SUFFIX_RE.search(part) for part in parts[1:])
    return False


def _is_likely_experience_bullet(line: str) -> bool:
    cleaned = _clean_string(line).lstrip('-*• ').strip()
    if not cleaned:
        return False
    lowered = cleaned.casefold()
    if re.search(r'\b(?:tech(?:nologies)?|stack|tools used|environment)\b', lowered, re.IGNORECASE):
        return True
    if any(lowered.startswith(f'{verb} ') for verb in EXPERIENCE_BULLET_VERBS):
        return True
    if _is_likely_prose(cleaned):
        return True
    if len(cleaned) > 100:
        return True
    if cleaned.endswith('.'):
        return True
    return False


def _is_likely_experience_header(line: str) -> bool:
    cleaned = _clean_string(line).lstrip('-*• ').strip()
    if not cleaned:
        return False
    lowered = cleaned.casefold()
    if len(cleaned) > 140 and not (DATE_RANGE_RE.search(cleaned) and (_has_strong_role_signal(cleaned) or _has_strong_company_signal(cleaned))):
        return False
    if re.search(r'\b(?:tech(?:nologies)?|stack|tools used|environment)\b', lowered, re.IGNORECASE):
        return False
    if any(lowered.startswith(f'{verb} ') for verb in EXPERIENCE_BULLET_VERBS):
        return False
    if _is_likely_prose(cleaned) and not DATE_RANGE_RE.search(cleaned):
        return False
    has_date = bool(DATE_RANGE_RE.search(cleaned))
    has_role = _has_strong_role_signal(cleaned)
    has_company = _has_strong_company_signal(cleaned)
    if has_date and (has_role or has_company):
        return True
    if ' at ' in lowered and len(cleaned.split()) <= 12:
        return has_role or has_company
    if '|' in cleaned:
        parts = [part.strip() for part in cleaned.split('|') if part.strip()]
        short_parts = [part for part in parts if len(part.split()) <= 8]
        if len(short_parts) >= 2 and (has_role or has_company or has_date):
            return True
    compact_pattern = re.search(
        r'^[A-Za-z][A-Za-z0-9 &/().,+#-]{1,80}\s+(?:at|\|)\s+[A-Za-z0-9 &/().,+#-]{1,80}(?:\s+(?:\||,|-)\s*.+)?$',
        cleaned,
        re.IGNORECASE,
    )
    return bool(compact_pattern and (has_role or has_company or has_date))


def _is_noisy_experience_bullet(text: str) -> bool:
    cleaned = _clean_string(text)
    if not cleaned:
        return True
    if _is_weak_experience_statement(cleaned):
        return True
    if re.fullmatch(r'[A-Za-z0-9+#./ -]{1,60}', cleaned) and cleaned.count(',') >= 2:
        return True
    return False


def _is_company_description_bullet(text: str) -> bool:
    cleaned = _clean_string(text)
    lowered = cleaned.casefold()

    if not cleaned:
        return False

    if lowered.startswith(('client:', 'about client', 'about company', 'company:', 'organization:')):
        return True

    descriptive_patterns = [
        r'\bis a leading\b',
        r'\bis an?\b.*\b(company|organization|provider|platform|startup|firm|enterprise|brand|manufacturer)\b',
        r'\bone of the leading\b',
        r'\bheadquartered in\b',
        r'\bfounded in\b',
        r'\bserves\b',
        r'\bserving\b',
        r'\bprovides\b',
        r'\bproviding\b',
        r'\boffers\b',
        r'\bfocused on\b',
        r'\bspecializes in\b',
        r'\bknown for\b',
        r'\boperates in\b',
        r'\bglobal presence\b',
        r'\bcustomers\b',
        r'\busers\b',
        r'\bclients\b',
        r'\brevenue\b',
        r'\bemployees\b',
        r'\boffices\b',
        r'\bfortune\b',
    ]
    if any(re.search(pattern, lowered) for pattern in descriptive_patterns):
        return True

    candidate_action_verbs = (
        'developed', 'built', 'designed', 'implemented', 'created', 'led',
        'improved', 'optimized', 'automated', 'integrated', 'deployed',
        'maintained', 'tested', 'debugged', 'analyzed', 'delivered',
        'collaborated', 'owned', 'supported', 'migrated', 'configured',
    )
    if not any(lowered.startswith(f'{verb} ') for verb in candidate_action_verbs):
        if re.search(r'\b(it|they|the company|the client|organization)\b', lowered):
            return True

    return False


def _is_weak_experience_statement(text: str) -> bool:
    cleaned = _clean_string(text)
    lowered = cleaned.casefold()
    starts_with_action_verb = any(lowered.startswith(f'{verb} ') for verb in EXPERIENCE_BULLET_VERBS)
    if not cleaned:
        return True
    if _is_likely_skill_item(cleaned) and len(cleaned.split()) <= 5 and not starts_with_action_verb:
        return True
    if lowered.startswith('good knowledge of') or lowered.startswith('good understanding of'):
        return True
    if lowered.startswith('knowledge of') or lowered.startswith('familiar with'):
        return True
    if lowered.startswith('hands-on experience in') or lowered.startswith('having experience in'):
        return True
    if lowered.startswith('experience in') or lowered.startswith('responsible for'):
        return True
    if lowered.startswith('ability to ') or lowered.startswith('objective'):
        return True
    if lowered.startswith('used to '):
        return True
    if lowered.startswith('worked on various'):
        return True
    if lowered.startswith('seeking'):
        return True
    if any(phrase in lowered for phrase in ('team player', 'quick learner', 'hard working', 'hardworking', 'self motivated', 'self-motivated')):
        return True
    if any(phrase in lowered for phrase in ('professional summary', 'career objective', 'profile summary')):
        return True
    if re.fullmatch(r'[A-Za-z0-9+#./ -]{1,80}', cleaned) and cleaned.count(',') >= 2:
        return True
    if all(_is_likely_skill_item(piece.strip()) for piece in cleaned.split(',') if piece.strip()) and cleaned.count(',') >= 1:
        return True
    if len(cleaned.split()) <= 6 and not starts_with_action_verb and not _has_strong_role_signal(cleaned) and not _has_strong_company_signal(cleaned):
        return True
    return False


def _has_strong_experience_bullet(text: str) -> bool:
    cleaned = _clean_string(text).lstrip('-*• ').strip()
    lowered = cleaned.casefold()
    if not cleaned or _is_company_description_bullet(cleaned) or _is_weak_experience_statement(cleaned) or _is_noisy_experience_bullet(cleaned):
        return False
    if any(lowered.startswith(f'{verb} ') for verb in EXPERIENCE_BULLET_VERBS):
        return True
    if re.search(r'\b(?:api|apis|service|services|system|systems|platform|platforms|dashboard|dashboards|pipeline|pipelines|automation|deployment|deployments|workflow|workflows|module|modules|feature|features|application|applications|client|clients|process|processes|database|databases|integration|integrations|report|reports|job|jobs|testing|monitoring|reliability|performance)\b', lowered):
        return True
    if re.search(r'\b(?:delivered|owned|handled|supported|maintained|designed|implemented|built|created|analyzed|documented)\b', lowered):
        return True
    return False


def _has_valid_experience_dates(entry: dict[str, Any]) -> bool:
    return bool(_clean_string(entry.get('start_date')) and _clean_string(entry.get('end_date')))


def _entry_identity_fragments(entry: dict[str, Any]) -> set[str]:
    fragments = {
        _clean_string(entry.get('title')).casefold(),
        _clean_string(entry.get('company')).casefold(),
        _clean_string(entry.get('duration_text')).casefold(),
        _clean_string(entry.get('start_date')).casefold(),
        _clean_string(entry.get('end_date')).casefold(),
    }
    fragments.discard('')
    start_date = _clean_string(entry.get('start_date'))
    end_date = _clean_string(entry.get('end_date'))
    if start_date and end_date:
        fragments.add(f'{start_date} - {end_date}'.casefold())
    return fragments


def _has_credible_identity(title: str, company: str) -> bool:
    cleaned_title = _clean_string(title)
    cleaned_company = _clean_string(company)
    title_is_strong = _has_strong_role_signal(cleaned_title)
    company_is_strong = _has_strong_company_signal(cleaned_company)
    company_word_count = len(cleaned_company.split())
    company_is_credible = company_is_strong or (
        bool(cleaned_company)
        and 2 <= company_word_count <= 6
        and not _is_likely_prose(cleaned_company)
    )
    if title_is_strong and company_is_credible:
        return True
    if company_is_strong and cleaned_title and not _is_likely_prose(cleaned_title):
        return True
    return title_is_strong and bool(cleaned_company) and not _is_likely_prose(cleaned_company)


def _is_meaningful_experience_entry(entry: dict[str, Any]) -> bool:
    title = _clean_string(entry.get('title'))
    company = _clean_string(entry.get('company'))
    bullets = _clean_string_list(entry.get('bullets'))
    strong_bullets = [bullet for bullet in bullets if _has_strong_experience_bullet(bullet)]
    has_valid_dates = _has_valid_experience_dates(entry)
    has_identity = bool(title or company)
    has_strong_header_signal = _has_strong_role_signal(title) or _has_strong_company_signal(company)
    has_credible_identity = _has_credible_identity(title, company)

    if not has_identity:
        return has_valid_dates and len(strong_bullets) >= 2

    if strong_bullets:
        if has_credible_identity or has_strong_header_signal or has_valid_dates:
            return True
        return False

    if not has_valid_dates:
        return False
    if has_strong_header_signal:
        return True
    if title and company and has_credible_identity:
        return True
    return False


def parse_resume_date(
    value: str | None,
    *,
    boundary: Literal['start', 'end'],
    today: date | None = None,
) -> ParsedMonth | None:
    """Parse common resume date formats into month precision.

    Year-only values are normalized conservatively:
    start dates use January, end dates use December.
    """
    text = _clean_string(value)
    if not text:
        return None
    normalized = re.sub(r'\s+', ' ', text.lower()).strip(' ,.-')
    if normalized in CURRENT_DATE_TOKENS:
        if boundary != 'end':
            return None
        current = today or date.today()
        return ParsedMonth(year=current.year, month=current.month, precision='current')

    month_match = re.fullmatch(r'(\d{4})[-/](\d{1,2})', normalized)
    if month_match:
        year = int(month_match.group(1))
        month = int(month_match.group(2))
        if 1 <= month <= 12:
            return ParsedMonth(year=year, month=month, precision='month')
        return None

    word_month_match = re.fullmatch(r'([a-z]+)[\s,./-]+(\d{2,4})', normalized)
    if word_month_match:
        month_token = word_month_match.group(1)
        year = int(word_month_match.group(2))
        if year < 100:
            year += 2000 if year < 50 else 1900
        month = MONTH_NAME_TO_NUMBER.get(month_token)
        if month:
            return ParsedMonth(year=year, month=month, precision='month')
        return None

    year_match = re.fullmatch(r'\d{4}', normalized)
    if year_match:
        year = int(normalized)
        month = 1 if boundary == 'start' else 12
        return ParsedMonth(year=year, month=month, precision='year')

    return None


def extract_date_range(
    text: str,
    *,
    today: date | None = None,
) -> tuple[str | None, str | None, bool, str | None, list[str]]:
    cleaned = _clean_string(text)
    if not cleaned:
        return None, None, False, None, []

    match = DATE_RANGE_RE.search(cleaned)
    if not match:
        tokens = [token.strip() for token in DATE_TOKEN_RE.findall(cleaned)]
        if len(tokens) >= 2:
            match = re.match(r'.*', cleaned)
            start_token, end_token = tokens[0], tokens[1]
        else:
            return None, None, False, None, []
    else:
        start_token, end_token = match.group('start'), match.group('end')

    start = parse_resume_date(start_token, boundary='start', today=today)
    end = parse_resume_date(end_token, boundary='end', today=today)
    notes: list[str] = []
    is_current = bool(_clean_string(end_token).lower() in CURRENT_DATE_TOKENS)
    if not start or not end:
        return None, None, is_current, f'{start_token} - {end_token}', ['Unparseable experience date range ignored for calculations.']
    if end.month_index < start.month_index:
        notes.append('Experience date range ignored because end date was earlier than start date.')
        return None, None, is_current, f'{start_token} - {end_token}', notes
    return start.iso_value(), end.iso_value(), is_current, f'{start_token} - {end_token}', notes


def month_index_from_iso(value: str | None) -> int | None:
    parsed = parse_resume_date(value, boundary='start')
    return parsed.month_index if parsed else None


def merge_month_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    ordered = sorted(ranges, key=lambda item: (item[0], item[1]))
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        merged[-1] = (prev_start, max(prev_end, end))
    return merged


def count_unique_months(ranges: Iterable[tuple[int, int]]) -> int:
    return sum((end - start) + 1 for start, end in merge_month_ranges(ranges))


class ExperienceCalculator:
    internship_keywords = ('intern', 'internship', 'trainee', 'apprentice', 'apprenticeship')

    @classmethod
    def summarize(
        cls,
        entries: list[dict[str, Any]],
        *,
        today: date | None = None,
    ) -> ExperienceCalculationResult:
        professional_ranges: list[tuple[int, int]] = []
        internship_ranges: list[tuple[int, int]] = []
        combined_ranges: list[tuple[int, int]] = []
        notes: list[str] = []

        for index, entry in enumerate(entries):
            date_range, entry_notes = cls._range_for_entry(entry, today=today)
            if entry_notes:
                notes.extend(entry_notes)
            if not date_range:
                continue
            start_index, end_index, employment_type = date_range
            combined_ranges.append((start_index, end_index))
            if employment_type == 'internship':
                internship_ranges.append((start_index, end_index))
            else:
                professional_ranges.append((start_index, end_index))

        return ExperienceCalculationResult(
            professional_months=count_unique_months(professional_ranges),
            internship_months=count_unique_months(internship_ranges),
            combined_months=count_unique_months(combined_ranges),
            notes=cls._dedupe_notes(notes),
        )

    @classmethod
    def _range_for_entry(
        cls,
        entry: dict[str, Any],
        *,
        today: date | None = None,
    ) -> tuple[tuple[int, int, str] | None, list[str]]:
        start = parse_resume_date(_clean_optional_string(entry.get('start_date')), boundary='start', today=today)
        end_boundary = 'end'
        end = parse_resume_date(_clean_optional_string(entry.get('end_date')), boundary=end_boundary, today=today)
        if entry.get('is_current') and not end:
            end = parse_resume_date('present', boundary='end', today=today)

        notes: list[str] = []
        if not start or not end:
            notes.append(
                f"Skipped experience duration for role '{_clean_string(entry.get('title')) or 'unknown'}' because dates were incomplete or unparseable."
            )
            return None, notes
        if end.month_index < start.month_index:
            notes.append(
                f"Skipped experience duration for role '{_clean_string(entry.get('title')) or 'unknown'}' because end date was earlier than start date."
            )
            return None, notes
        employment_type = cls.normalize_employment_type(entry)
        return (start.month_index, end.month_index, employment_type), notes

    @classmethod
    def normalize_employment_type(cls, entry: dict[str, Any]) -> str:
        employment_type = _clean_string(entry.get('employment_type')).lower().replace('-', '_')
        if employment_type in EMPLOYMENT_TYPE_VALUES:
            return employment_type
        haystack = ' '.join(
            filter(
                None,
                [
                    _clean_string(entry.get('title')).lower(),
                    _clean_string(entry.get('company')).lower(),
                    ' '.join(_clean_string_list(entry.get('bullets'))).lower(),
                    ' '.join(_clean_string_list(entry.get('notes'))).lower(),
                ],
            )
        )
        if any(keyword in haystack for keyword in cls.internship_keywords):
            return 'internship'
        return 'unknown'

    @classmethod
    def select_current_role(cls, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not entries:
            return None
        current_entries = [entry for entry in entries if bool(entry.get('is_current'))]
        if current_entries:
            return max(current_entries, key=cls._role_sort_key)
        dated_entries = [entry for entry in entries if parse_resume_date(_clean_optional_string(entry.get('end_date')), boundary='end')]
        if dated_entries:
            return max(dated_entries, key=cls._role_sort_key)
        titled_entries = [entry for entry in entries if _clean_string(entry.get('title')) or _clean_string(entry.get('company'))]
        return titled_entries[0] if titled_entries else None

    @classmethod
    def _role_sort_key(cls, entry: dict[str, Any]) -> tuple[int, int, int]:
        end = parse_resume_date(_clean_optional_string(entry.get('end_date')), boundary='end')
        start = parse_resume_date(_clean_optional_string(entry.get('start_date')), boundary='start')
        return (
            1 if entry.get('is_current') else 0,
            end.month_index if end else -1,
            start.month_index if start else -1,
        )

    @staticmethod
    def _dedupe_notes(notes: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for note in notes:
            cleaned = _clean_string(note)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            deduped.append(cleaned)
        return deduped


class ResumeTextExtractor:
    def extract(self, file_obj: BinaryIO, filename: str = '', content_type: str = '') -> tuple[str, str]:
        suffix = Path(filename or '').suffix.lower()
        mime_type = content_type or mimetypes.guess_type(filename or '')[0] or ''
        try:
            content = file_obj.read()
        finally:
            try:
                file_obj.seek(0)
            except Exception:
                pass
        if not isinstance(content, (bytes, bytearray)):
            raise ResumeProcessingError('Unable to read the uploaded resume file.')
        content_bytes = bytes(content)
        if suffix == '.pdf':
            text = self._extract_pdf(content_bytes)
            return self._ensure_text(text, 'PDF'), mime_type or 'application/pdf'
        if suffix == '.docx':
            text = self._extract_docx(content_bytes)
            return self._ensure_text(text, 'DOCX'), mime_type or 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        raise ResumeProcessingError('Unsupported resume format. Please upload a PDF or DOCX file.')

    def _extract_pdf(self, content: bytes) -> str:
        reader_cls = None
        try:
            from pypdf import PdfReader  # type: ignore
            reader_cls = PdfReader
        except Exception:
            try:
                from PyPDF2 import PdfReader  # type: ignore
                reader_cls = PdfReader
            except Exception as exc:
                raise ResumeProcessingError('PDF parsing requires `pypdf` or `PyPDF2`.') from exc

        reader = reader_cls(BytesIO(content))
        if getattr(reader, 'is_encrypted', False):
            raise ResumeProcessingError('Encrypted or password-protected PDFs are not supported.')
        return '\n'.join((page.extract_text() or '') for page in reader.pages).strip()

    def _extract_docx(self, content: bytes) -> str:
        try:
            from docx import Document  # type: ignore
            document = Document(BytesIO(content))
            return '\n'.join(p.text for p in document.paragraphs if p.text.strip()).strip()
        except Exception:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                if 'word/document.xml' not in archive.namelist():
                    raise ResumeProcessingError('DOCX file is missing document.xml content.')
                xml_bytes = archive.read('word/document.xml')
            root = ElementTree.fromstring(xml_bytes)
            fragments: list[str] = []
            for node in root.iter():
                if node.tag.endswith('}t') and node.text:
                    fragments.append(node.text)
                elif node.tag.endswith('}p'):
                    fragments.append('\n')
            return ''.join(fragments).strip()

    def _ensure_text(self, text: str, file_type: str) -> str:
        normalized = (text or '').strip()
        if normalized:
            return normalized
        raise ResumeProcessingError(f'Unable to extract readable text from the uploaded {file_type} file.')


class OpenAIResumeExtractor:
    endpoint = 'https://api.openai.com/v1/responses'

    def __init__(self) -> None:
        self.api_key = getattr(settings, 'OPENAI_API_KEY', '').strip()
        self.model = getattr(settings, 'OPENAI_RESUME_MODEL', 'gpt-4.1-mini').strip()

    def is_enabled(self) -> bool:
        return bool(self.api_key and self.model)

    def extract(self, resume_text: str) -> OpenAIExtractionResult:
        if not resume_text.strip():
            return OpenAIExtractionResult(
                payload=None,
                attempted=False,
                configured=self.is_enabled(),
                error='Empty resume text.',
                raw_preview='',
                model=self.model,
            )
        if not self.is_enabled():
            return OpenAIExtractionResult(
                payload=None,
                attempted=False,
                configured=False,
                error='OpenAI extractor not configured.',
                raw_preview='',
                model=self.model,
            )

        prompt = (
            'You are restructuring noisy resume text extracted from a PDF or DOCX. '
            'The text order may be broken, headings may be misplaced, and lines may be fragmented.\n\n'
            'Return only JSON that matches the schema exactly.\n'
            'Rules:\n'
            '1. Reconstruct the resume semantically, but do not invent facts.\n'
            '2. Preserve ambiguity with nulls and notes instead of guessing.\n'
            '3. Extract work experience into normalized entries with title, company, employment_type, start_date, end_date, is_current, duration_text, tech_stack, bullets, and notes.\n'
            '4. Extract projects and education into structured entries.\n'
            '5. Extract technical expertise into grouped arrays where evidence exists.\n'
            '6. claimed_experience_text may capture prose like "3+ years of experience", but it is not ground truth and must not be converted into computed totals.\n'
            '7. Do not infer missing months from thin evidence beyond the explicit date string. If a date is ambiguous, set the structured field to null and explain in notes.\n'
            '8. Use ISO-like YYYY-MM when a month is known, YYYY when only a year is known, and null when the date cannot be determined.\n'
            '9. sections are optional compatibility output and should be conservative; canonical top-level fields are the source of truth.\n'
            '10. Do not stuff leftover text into skills. Keep objective, summary, experience, education, and technical expertise distinct.\n'
            '11. If text is uncertain or leftover, place it into notes instead of skills.\n\n'
            f'Noisy extracted resume text:\n{resume_text[:90000]}'
        )

        body = json.dumps({
            'model': self.model,
            'input': prompt,
            'temperature': 0.1,
            'text': {
                'format': {
                    'type': 'json_schema',
                    'name': 'resume_profile',
                    'strict': True,
                    'schema': self._response_schema(),
                }
            },
        }).encode('utf-8')
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode('utf-8', errors='ignore')
            except Exception:
                error_body = ''
            return OpenAIExtractionResult(
                payload=None,
                attempted=True,
                configured=True,
                error=f'OpenAI HTTP error {exc.code}.',
                raw_preview=error_body[:2000],
                model=self.model,
            )
        except urllib.error.URLError as exc:
            return OpenAIExtractionResult(
                payload=None,
                attempted=True,
                configured=True,
                error=f'OpenAI network error: {exc.reason}',
                raw_preview='',
                model=self.model,
            )
        except (TimeoutError, json.JSONDecodeError) as exc:
            return OpenAIExtractionResult(
                payload=None,
                attempted=True,
                configured=True,
                error=f'OpenAI response parse error: {exc}',
                raw_preview='',
                model=self.model,
            )

        text = self._extract_output_text(payload)
        if not text:
            return OpenAIExtractionResult(
                payload=None,
                attempted=True,
                configured=True,
                error='OpenAI response did not contain structured output text.',
                raw_preview=json.dumps(payload)[:2000],
                model=self.model,
            )
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return OpenAIExtractionResult(
                payload=None,
                attempted=True,
                configured=True,
                error=f'OpenAI structured output JSON decode failed: {exc}',
                raw_preview=text[:2000],
                model=self.model,
            )
        return OpenAIExtractionResult(
            payload=ParsedResumePayload(provider='openai', data=parsed),
            attempted=True,
            configured=True,
            error='',
            raw_preview=text[:2000],
            model=self.model,
        )

    def _response_schema(self) -> dict[str, Any]:
        string_or_null = {'type': ['string', 'null']}
        string_array = {'type': 'array', 'items': {'type': 'string'}}
        experience_item = {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'title': string_or_null,
                'company': string_or_null,
                'location': string_or_null,
                'employment_type': {'type': 'string', 'enum': sorted(EMPLOYMENT_TYPE_VALUES)},
                'start_date': string_or_null,
                'end_date': string_or_null,
                'is_current': {'type': 'boolean'},
                'duration_text': string_or_null,
                'tech_stack': string_array,
                'bullets': string_array,
                'notes': string_array,
            },
            'required': [
                'title',
                'company',
                'location',
                'employment_type',
                'start_date',
                'end_date',
                'is_current',
                'duration_text',
                'tech_stack',
                'bullets',
                'notes',
            ],
        }
        project_item = {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'name': string_or_null,
                'role': string_or_null,
                'organization': string_or_null,
                'start_date': string_or_null,
                'end_date': string_or_null,
                'tech_stack': string_array,
                'bullets': string_array,
                'notes': string_array,
            },
            'required': ['name', 'role', 'organization', 'start_date', 'end_date', 'tech_stack', 'bullets', 'notes'],
        }
        education_item = {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'degree': string_or_null,
                'institution': string_or_null,
                'location': string_or_null,
                'start_date': string_or_null,
                'end_date': string_or_null,
                'grade': string_or_null,
                'notes': string_array,
            },
            'required': ['degree', 'institution', 'location', 'start_date', 'end_date', 'grade', 'notes'],
        }
        section_item = {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'section_key': {'type': 'string'},
                'title': {'type': 'string'},
                'section_type': {'type': 'string'},
                'display_order': {'type': 'integer'},
                'raw_text': {'type': 'string'},
                'content': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        'text': {'type': 'string'},
                        'items': {
                            'type': 'array',
                            'items': {
                                'anyOf': [
                                    {'type': 'string'},
                                    {
                                        'type': 'object',
                                        'additionalProperties': False,
                                        'properties': {
                                            'label': {'type': 'string'},
                                            'value': {'type': 'string'},
                                        },
                                        'required': ['label', 'value'],
                                    },
                                ],
                            },
                        },
                    },
                    'required': ['text', 'items'],
                },
            },
            'required': ['section_key', 'title', 'section_type', 'display_order', 'raw_text', 'content'],
        }
        return {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'headline': {'type': 'string'},
                'summary': {'type': 'string'},
                'objective': {'type': 'string'},
                'candidate_type': {'type': 'string'},
                'contact': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        'name': {'type': 'string'},
                        'email': {'type': 'string'},
                        'phone': {'type': 'string'},
                        'location': {'type': 'string'},
                        'links': string_array,
                    },
                    'required': ['name', 'email', 'phone', 'location', 'links'],
                },
                'technical_expertise': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {key: string_array for key in TECHNICAL_EXPERTISE_KEYS},
                    'required': list(TECHNICAL_EXPERTISE_KEYS),
                },
                'skills': string_array,
                'experience': {'type': 'array', 'items': experience_item},
                'projects': {'type': 'array', 'items': project_item},
                'education': {'type': 'array', 'items': education_item},
                'certifications': string_array,
                'achievements': string_array,
                'languages': string_array,
                'claimed_experience_text': string_or_null,
                'sections': {'type': 'array', 'items': section_item},
            },
            'required': [
                'headline',
                'summary',
                'objective',
                'candidate_type',
                'contact',
                'technical_expertise',
                'skills',
                'experience',
                'projects',
                'education',
                'certifications',
                'achievements',
                'languages',
                'claimed_experience_text',
                'sections',
            ],
        }

    def _extract_output_text(self, payload: dict[str, Any]) -> str:
        direct = payload.get('output_text')
        if isinstance(direct, str) and direct.strip():
            return direct.strip()

        for item in payload.get('output') or []:
            if not isinstance(item, dict):
                continue
            for content in item.get('content') or []:
                if not isinstance(content, dict):
                    continue
                text = content.get('text')
                if isinstance(text, str) and text.strip():
                    return text.strip()
                if isinstance(content.get('output_text'), str) and content['output_text'].strip():
                    return content['output_text'].strip()
        return ''


class HeuristicResumeExtractor:
    email_re = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
    phone_re = re.compile(r'(?:(?:\+|91)?\s*)?(?:\d[\s-]?){10,15}')
    link_re = re.compile(r'(https?://\S+|www\.\S+|linkedin\.com/\S+|github\.com/\S+)', re.IGNORECASE)
    exp_re = re.compile(r'(\d+(?:\.\d+)?)\+?\s+(?:years?|yrs?)\s+(?:of\s+)?experience', re.IGNORECASE)
    heading_clean_re = re.compile(r'[^a-z ]+')
    all_heading_aliases = sorted(CANONICAL_SECTION_BY_ALIAS.keys(), key=len, reverse=True)

    def extract(self, resume_text: str) -> ParsedResumePayload:
        normalized_text = self._prepare_text(resume_text)
        lines = [line.strip(' \t:-') for line in normalized_text.splitlines()]
        lines = [line for line in lines if line.strip()]

        raw_sections = self._split_sections(lines)
        sections = self._cleanup_sections(raw_sections)
        summary = self._extract_section_text(sections, 'summary')
        objective = self._extract_section_text(sections, 'objective')
        contact = self._extract_contact(normalized_text, lines)
        skills = self._extract_skills(sections)
        technical_expertise = self._extract_technical_expertise(sections, skills)
        languages = self._extract_language_items(sections)
        experience = self._extract_experience(sections)
        education = self._extract_education(sections)
        projects = self._extract_projects(sections)
        certifications = self._extract_string_section_items(sections, 'certifications')
        achievements = self._extract_string_section_items(sections, 'achievements')
        candidate_type = 'experienced' if experience else 'fresher'
        headline = self._infer_headline(lines, summary, objective)
        claimed_experience_text = self._extract_claimed_experience_text(normalized_text)

        payload = {
            'headline': headline,
            'summary': summary,
            'objective': objective,
            'candidate_type': candidate_type,
            'contact': contact,
            'technical_expertise': technical_expertise,
            'skills': skills,
            'experience': experience,
            'projects': projects,
            'education': education,
            'certifications': certifications,
            'achievements': achievements,
            'languages': languages,
            'claimed_experience_text': claimed_experience_text,
            'sections': sections,
        }
        return ParsedResumePayload(provider='heuristic', data=payload)

    def _prepare_text(self, text: str) -> str:
        normalized = (text or '').replace('\r', '\n')
        normalized = re.sub(r'[ \t]+', ' ', normalized)
        normalized = re.sub(r'\n{3,}', '\n\n', normalized)
        normalized = re.sub(r'\s*•\s*', '\n• ', normalized)
        normalized = re.sub(r'(WORK HISTORY)(?=Role:)', r'\1\n', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'(WORK EXPERIENCE)(?=Role:)', r'\1\n', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'(PROFESSIONAL EXPERIENCE)(?=Role:)', r'\1\n', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'(EDUCATION)(?=Bachelor|Master|B\.?Tech|M\.?Tech|B\.?E|M\.?E|BCA|MCA)', r'\1\n', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'(PROJECTS)(?=[A-Z][a-z])', r'\1\n', normalized, flags=re.IGNORECASE)

        for heading in EXPLICIT_HEADING_PATTERNS:
            normalized = re.sub(
                rf'(?<=[a-z0-9\.\)])\s*({re.escape(heading)})\b',
                rf'\n\1\n',
                normalized,
                flags=re.IGNORECASE,
            )
            normalized = re.sub(
                rf'({re.escape(heading)})(?=[A-Z][a-z])',
                rf'\1\n',
                normalized,
                flags=re.IGNORECASE,
            )
            normalized = re.sub(
                rf'(?<!\n)^\s*({re.escape(heading)})\s*$',
                lambda match: f"\n{match.group(1).upper()}\n",
                normalized,
                flags=re.IGNORECASE | re.MULTILINE,
            )

        normalized = re.sub(r'([a-z])([A-Z][A-Z ]{3,})', r'\1\n\2', normalized)
        normalized = re.sub(r'\n{3,}', '\n\n', normalized)
        return normalized.strip()

    def _split_sections(self, lines: list[str]) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        current_title = 'Overview'
        current_key = 'overview'
        current_lines: list[str] = []

        def flush() -> None:
            if not current_lines:
                return
            raw_text = '\n'.join(current_lines).strip()
            sections.append({
                'section_key': current_key,
                'title': current_title,
                'section_type': current_key,
                'display_order': len(sections),
                'content': {'text': raw_text, 'items': self._extract_bullet_items(current_lines)},
                'raw_text': raw_text,
            })

        for line in lines:
            heading_key = self._normalize_heading(line)
            if heading_key in CANONICAL_SECTION_BY_ALIAS or self._looks_like_heading(line):
                flush()
                current_key = CANONICAL_SECTION_BY_ALIAS.get(heading_key, heading_key.replace(' ', '_'))
                current_title = self._titleize_heading(line)
                current_lines = []
                continue
            current_lines.append(line)
        flush()
        return sections

    def _normalize_heading(self, line: str) -> str:
        simplified = self.heading_clean_re.sub(' ', line.lower()).strip()
        return ' '.join(simplified.split())

    def _looks_like_heading(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped or len(stripped) > 40:
            return False
        normalized = self._normalize_heading(stripped)
        if normalized in CANONICAL_SECTION_BY_ALIAS:
            return True
        alpha = re.sub(r'[^A-Za-z ]+', '', stripped)
        return bool(alpha and alpha == alpha.upper() and len(alpha.split()) <= 4)

    def _titleize_heading(self, line: str) -> str:
        normalized = self._normalize_heading(line)
        if normalized in CANONICAL_SECTION_BY_ALIAS:
            return normalized.title()
        return line.title()

    def _extract_bullet_items(self, lines: list[str]) -> list[str]:
        items: list[str] = []
        for line in lines:
            clean = line.lstrip('-*• ').strip()
            if clean:
                items.append(clean)
        return items

    def _cleanup_sections(self, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        seen_keys: dict[str, int] = {}

        for section in sections:
            key = section['section_key']
            text = _clean_string(section.get('raw_text'))
            items = section.get('content', {}).get('items') if isinstance(section.get('content'), dict) else []
            if not text and not items:
                continue
            if key in seen_keys:
                existing = cleaned[seen_keys[key]]
                existing['raw_text'] = '\n'.join(part for part in [existing.get('raw_text', ''), text] if part).strip()
                existing_items = existing.setdefault('content', {}).setdefault('items', [])
                if isinstance(existing_items, list) and isinstance(items, list):
                    existing_items.extend(items)
                existing['content']['text'] = existing['raw_text']
                continue
            seen_keys[key] = len(cleaned)
            cleaned.append(section)

        for index, section in enumerate(cleaned):
            section['display_order'] = index
        return cleaned

    def _extract_contact(self, text: str, lines: list[str]) -> dict[str, Any]:
        first_lines = lines[:12]
        fallback_name = first_lines[0] if first_lines else ''
        email = self.email_re.search(text)
        phone = self.phone_re.search(text)
        links = [match.strip().rstrip('.,') for match in self.link_re.findall(text)]
        location = ''
        for line in first_lines:
            if email and email.group(0) in line:
                continue
            if phone and phone.group(0) in line:
                continue
            if any(link in line for link in links):
                continue
            if len(line.split()) >= 2 and len(line) <= 60:
                location = line
                break
        return {
            'name': fallback_name,
            'email': email.group(0) if email else '',
            'phone': (phone.group(0) if phone else '').strip(),
            'location': location,
            'links': links,
        }

    def _extract_section_text(self, sections: list[dict[str, Any]], key: str) -> str:
        section = next((item for item in sections if item['section_key'] == key), None)
        if not section:
            return ''
        lines = [
            line.strip()
            for line in _clean_string(section.get('raw_text')).splitlines()
            if line.strip() and not self._looks_like_heading(line)
        ]
        return ' '.join(lines[:6]).strip()

    def _extract_skills(self, sections: list[dict[str, Any]]) -> list[str]:
        section = next((item for item in sections if item['section_key'] == 'skills'), None)
        if not section:
            return []
        raw_text = _clean_string(section.get('raw_text'))
        raw_items = self._extract_bullet_items(raw_text.splitlines())
        if not raw_items:
            raw_items = [piece.strip() for piece in re.split(r'[|,/]', raw_text) if piece.strip()]
        return self._normalize_skill_items(raw_items)

    def _extract_technical_expertise(self, sections: list[dict[str, Any]], skills: list[str]) -> dict[str, list[str]]:
        expertise = _empty_technical_expertise()
        relevant_sections = [
            item
            for item in sections
            if item.get('section_key') in {'skills', 'technical_expertise'}
        ]
        raw_lines: list[str] = []
        raw_items: list[str] = []
        for section in relevant_sections:
            raw_lines.extend(_clean_string(section.get('raw_text')).splitlines())
            content = section.get('content') if isinstance(section.get('content'), dict) else {}
            if isinstance(content.get('items'), list):
                raw_items.extend(_clean_string_list(content.get('items')))
        category_aliases = {
            'languages': {'language', 'languages'},
            'frameworks': {'framework', 'frameworks'},
            'libraries': {'library', 'libraries'},
            'databases': {'database', 'databases', 'db'},
            'tools': {'tool', 'tools'},
            'cloud': {'cloud', 'aws', 'azure', 'gcp'},
            'devops': {'devops', 'ci/cd', 'cicd', 'container', 'containers'},
            'web_technologies': {'web', 'web technologies', 'frontend', 'backend'},
            'testing': {'testing', 'test', 'qa'},
        }
        matched_items: set[str] = set()
        for line in raw_lines:
            if ':' not in line:
                continue
            label, values = line.split(':', 1)
            normalized_label = self._normalize_heading(label)
            items = self._normalize_skill_items([piece.strip() for piece in re.split(r'[|,/]', values) if piece.strip()])
            if not items:
                continue
            bucket = next(
                (
                    key
                    for key, aliases in category_aliases.items()
                    if normalized_label in aliases or any(alias in normalized_label for alias in aliases)
                ),
                'other',
            )
            expertise[bucket].extend(items)
            matched_items.update(item.casefold() for item in items)

        expertise = {key: self._normalize_skill_items(value) for key, value in expertise.items()}
        noisy_skill_source = bool(raw_items) and sum(1 for item in raw_items if _is_likely_prose(item)) >= max(2, len(raw_items) // 2 + 1)
        for skill in skills:
            if not _is_likely_skill_item(skill):
                continue
            if noisy_skill_source and not any(expertise.values()):
                continue
            if skill.casefold() not in matched_items:
                expertise['other'].append(skill)
        expertise['other'] = self._normalize_skill_items(expertise['other'])
        return expertise

    def _extract_language_items(self, sections: list[dict[str, Any]]) -> list[str]:
        section = next((item for item in sections if item['section_key'] == 'languages'), None)
        if not section:
            return []
        raw_text = _clean_string(section.get('raw_text'))
        items = [piece.strip() for piece in re.split(r'[|,/]', raw_text) if piece.strip()]
        return self._normalize_skill_items(items)

    def _extract_experience(self, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for section_key in ('experience', 'internships'):
            section = next((item for item in sections if item['section_key'] == section_key), None)
            if not section:
                continue
            items.extend(self._group_experience_entries(_clean_string(section.get('raw_text')).splitlines(), section_key))
        return items

    def _group_experience_entries(self, lines: list[str], section_key: str) -> list[dict[str, Any]]:
        entries: list[list[str]] = []
        current: list[str] = []
        orphan_lines: list[str] = []
        for line in lines:
            clean = line.lstrip('-*• ').strip()
            if not clean:
                continue
            if self._is_likely_experience_header(clean):
                if current:
                    entries.append(current)
                current = [clean]
                if orphan_lines:
                    current.extend(
                        orphan
                        for orphan in orphan_lines
                        if len(orphan.split()) <= 10 and (_has_strong_role_signal(orphan) or _has_strong_company_signal(orphan))
                    )
                    orphan_lines = []
                continue
            if not current:
                orphan_lines.append(clean)
                continue
            if self._is_likely_experience_bullet(clean) or not self._is_likely_experience_header(clean):
                current.append(clean)
                continue
            if current and self._looks_like_experience_header(clean):
                entries.append(current)
                current = [clean]
                continue
            current.append(clean)
        if current:
            entries.append(current)

        structured: list[dict[str, Any]] = []
        for chunk in entries:
            entry = self._build_experience_entry(chunk, section_key)
            if not entry:
                continue
            if structured and not self._is_meaningful_experience_entry(entry):
                structured[-1]['bullets'].extend(_clean_string_list(entry.get('bullets')))
                structured[-1]['notes'].extend(_clean_string_list(entry.get('notes')))
                continue
            structured.append(entry)
        merged: list[dict[str, Any]] = []
        for entry in structured:
            if merged and not self._is_meaningful_experience_entry(entry):
                merged[-1]['bullets'].extend(_clean_string_list(entry.get('bullets')))
                merged[-1]['notes'].extend(_clean_string_list(entry.get('notes')))
                continue
            if (
                merged
                and not _clean_string(entry.get('title'))
                and not _clean_string(entry.get('company'))
                and not (_clean_string(entry.get('start_date')) and _clean_string(entry.get('end_date')))
                and len(_clean_string_list(entry.get('bullets'))) <= 1
            ):
                merged[-1]['bullets'].extend(_clean_string_list(entry.get('bullets')))
                continue
            merged.append(entry)
        return [entry for entry in merged if self._is_meaningful_experience_entry(entry)]

    def _looks_like_experience_header(self, line: str) -> bool:
        return self._is_likely_experience_header(line)

    def _build_experience_entry(self, chunk: list[str], section_key: str) -> dict[str, Any] | None:
        header_candidates = [line for line in chunk[:3] if self._is_likely_experience_header(line)]
        header = self._select_best_experience_header(header_candidates or chunk[:1])
        split_source = DATE_RANGE_RE.sub('', header).strip(' |,-')
        title, company = self._split_role_company(split_source)
        if (not title or self._is_likely_experience_bullet(title)) and len(chunk) > 1:
            better_header = self._select_best_experience_header(chunk[:3])
            better_split_source = DATE_RANGE_RE.sub('', better_header).strip(' |,-')
            better_title, better_company = self._split_role_company(better_split_source)
            if better_title and not self._is_likely_experience_bullet(better_title):
                title, company = better_title, better_company

        title = None if title and self._is_likely_experience_bullet(title) else title or None
        location = self._extract_location_fragment(header)
        start_date = None
        end_date = None
        is_current = False
        duration_text = None
        notes: list[str] = []
        for line in chunk[:3]:
            start_date, end_date, is_current, duration_text, extracted_notes = extract_date_range(line)
            if duration_text:
                notes.extend(extracted_notes)
                break

        bullets: list[str] = []
        tech_stack: list[str] = []
        for line in chunk:
            if line == header:
                continue
            if duration_text and duration_text in line:
                continue
            cleaned = line.lstrip('-*• ').strip()
            if not cleaned:
                continue
            if re.search(r'\b(?:tech(?:nologies)?|stack|tools used)\b', cleaned, re.IGNORECASE):
                _, _, tail = cleaned.partition(':')
                tech_stack.extend(self._normalize_skill_items([piece.strip() for piece in re.split(r'[|,/]', tail or cleaned) if piece.strip()]))
                continue
            if self._is_likely_experience_header(cleaned) and cleaned != header:
                notes.append(cleaned)
                continue
            bullets.append(cleaned)

        bullets = [bullet for bullet in _clean_string_list(bullets) if _has_strong_experience_bullet(bullet)]
        employment_type = self._detect_employment_type(' '.join(chunk), default='internship' if section_key == 'internships' else 'unknown')
        normalized_title = _clean_string(title)
        normalized_company = _clean_string(company)
        deduped_notes = [
            note
            for note in ExperienceCalculator._dedupe_notes(notes)
            if _clean_string(note).casefold() not in {normalized_title.casefold(), normalized_company.casefold(), header.casefold()}
            and normalized_title.casefold() not in _clean_string(note).casefold()
            and normalized_company.casefold() not in _clean_string(note).casefold()
        ]
        entry = {
            'title': title or None,
            'company': company or None,
            'location': location or None,
            'employment_type': employment_type,
            'start_date': start_date,
            'end_date': end_date,
            'is_current': is_current,
            'duration_text': duration_text,
            'tech_stack': self._normalize_skill_items(tech_stack),
            'bullets': bullets,
            'notes': deduped_notes,
        }
        header_is_strong = self._is_likely_experience_header(header) and (
            _has_strong_role_signal(header) or _has_strong_company_signal(header) or bool(DATE_RANGE_RE.search(header))
        )
        if not header_is_strong and not entry['title'] and not entry['company']:
            return None
        if not header_is_strong and not _is_meaningful_experience_entry(entry):
            return None
        if not entry['bullets'] and not (entry['title'] or entry['company']):
            return None
        if not self._is_meaningful_experience_entry(entry):
            return None
        return entry

    def _select_best_experience_header(self, candidates: list[str]) -> str:
        if not candidates:
            return ''
        return max(candidates, key=lambda line: (
            1 if DATE_RANGE_RE.search(line) else 0,
            1 if self._has_strong_role_signal(line) else 0,
            1 if self._has_strong_company_signal(line) else 0,
            -len(line),
        ))

    def _split_role_company(self, line: str) -> tuple[str, str]:
        cleaned = DATE_RANGE_RE.sub('', line).strip(' |,-')
        if ' at ' in cleaned.lower():
            parts = re.split(r'\sat\s', cleaned, maxsplit=1, flags=re.IGNORECASE)
            company = parts[1].strip() if len(parts) > 1 else ''
            company = re.split(r'\s*[|,]\s*', company, maxsplit=1)[0].strip()
            return parts[0].strip(), company
        if '|' in cleaned:
            parts = [part.strip() for part in cleaned.split('|') if part.strip()]
            if len(parts) >= 2:
                return parts[0], parts[1]
        if ',' in cleaned and len(cleaned) < 120:
            parts = [part.strip() for part in cleaned.split(',') if part.strip()]
            if len(parts) >= 2:
                return parts[0], parts[1]
        return cleaned.strip(), ''

    def _extract_location_fragment(self, line: str) -> str:
        if 'remote' in line.lower():
            return 'Remote'
        parts = [part.strip() for part in re.split(r'[|,]', line) if part.strip()]
        if not parts:
            return ''
        candidate = parts[-1]
        if len(candidate.split()) <= 4 and not DATE_RANGE_RE.search(candidate) and LOCATION_HINT_RE.search(candidate):
            return candidate
        return ''

    def _is_likely_experience_bullet(self, line: str) -> bool:
        return _is_likely_experience_bullet(line)

    def _is_likely_experience_header(self, line: str) -> bool:
        return _is_likely_experience_header(line)

    def _has_strong_role_signal(self, line: str) -> bool:
        return _has_strong_role_signal(line)

    def _has_strong_company_signal(self, line: str) -> bool:
        return _has_strong_company_signal(line)

    def _is_meaningful_experience_entry(self, entry: dict[str, Any]) -> bool:
        return _is_meaningful_experience_entry(entry)

    def _detect_employment_type(self, text: str, *, default: str = 'unknown') -> str:
        normalized = text.lower()
        if 'intern' in normalized or 'trainee' in normalized:
            return 'internship'
        if 'freelance' in normalized:
            return 'freelance'
        if 'contract' in normalized:
            return 'contract'
        if 'part time' in normalized or 'part-time' in normalized:
            return 'part_time'
        if 'apprentice' in normalized:
            return 'apprenticeship'
        if 'temporary' in normalized:
            return 'temporary'
        return default if default in EMPLOYMENT_TYPE_VALUES else 'unknown'

    def _extract_education(self, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        section = next((item for item in sections if item['section_key'] == 'education'), None)
        if not section:
            return []
        return self._group_education_entries(_clean_string(section.get('raw_text')).splitlines())

    def _group_education_entries(self, lines: list[str]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in lines:
            clean = line.lstrip('-*• ').strip()
            if not clean:
                continue
            if current is None or self._looks_like_new_entry(clean):
                degree, institution = self._split_education(clean)
                start_date, end_date, _, _, notes = extract_date_range(clean)
                current = {
                    'degree': degree or None,
                    'institution': institution or None,
                    'location': self._extract_location_fragment(clean) or None,
                    'start_date': start_date,
                    'end_date': end_date,
                    'grade': self._extract_grade(clean),
                    'notes': notes,
                }
                entries.append(current)
            else:
                current['notes'].append(clean)
                if not current.get('grade'):
                    current['grade'] = self._extract_grade(clean)
        return entries

    def _looks_like_new_entry(self, line: str) -> bool:
        if len(line) < 100 and ('|' in line or DATE_RANGE_RE.search(line)):
            return True
        return bool(re.search(r'(19|20)\d{2}|present|current', line, re.IGNORECASE))

    def _split_education(self, line: str) -> tuple[str, str]:
        cleaned = DATE_RANGE_RE.sub('', line).strip(' |,-')
        if ' - ' in cleaned:
            parts = [part.strip() for part in cleaned.split(' - ', 1)]
            return parts[0], parts[1] if len(parts) > 1 else ''
        if ',' in cleaned:
            parts = [part.strip() for part in cleaned.split(',', 1)]
            return parts[0], parts[1] if len(parts) > 1 else ''
        return cleaned.strip(), ''

    def _extract_grade(self, line: str) -> str | None:
        grade_match = re.search(r'(cgpa|gpa|percentage|score)[:\s-]*([A-Za-z0-9\./%]+)', line, re.IGNORECASE)
        if grade_match:
            return f'{grade_match.group(1).upper()} {grade_match.group(2)}'
        return None

    def _extract_projects(self, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        section = next((item for item in sections if item['section_key'] == 'projects'), None)
        if not section:
            return []
        return self._group_project_entries(_clean_string(section.get('raw_text')).splitlines())

    def _group_project_entries(self, lines: list[str]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in lines:
            clean = line.lstrip('-*• ').strip()
            if not clean:
                continue
            if current is None or self._looks_like_new_entry(clean):
                start_date, end_date, _, _, notes = extract_date_range(clean)
                tech_stack = self._extract_tech_stack(clean)
                name, organization = self._split_project_header(clean)
                current = {
                    'name': name or None,
                    'role': None,
                    'organization': organization or None,
                    'start_date': start_date,
                    'end_date': end_date,
                    'tech_stack': tech_stack,
                    'bullets': [],
                    'notes': notes,
                }
                entries.append(current)
            else:
                if not current['role'] and len(clean) <= 90 and not clean.startswith(('Built', 'Developed', 'Implemented')):
                    current['role'] = clean
                    continue
                current['bullets'].append(clean)
                current['tech_stack'].extend(self._extract_tech_stack(clean))
        for entry in entries:
            entry['tech_stack'] = self._normalize_skill_items(entry['tech_stack'])
        return entries

    def _split_project_header(self, line: str) -> tuple[str, str]:
        cleaned = DATE_RANGE_RE.sub('', line).strip(' |,-')
        if '|' in cleaned:
            parts = [part.strip() for part in cleaned.split('|') if part.strip()]
            if len(parts) >= 2:
                return parts[0], parts[1]
        return cleaned, ''

    def _extract_tech_stack(self, line: str) -> list[str]:
        if ':' in line and re.search(r'\b(?:tech(?:nologies)?|stack|tools used)\b', line, re.IGNORECASE):
            _, _, tail = line.partition(':')
            return [item.strip() for item in re.split(r'[|,/]', tail) if item.strip()]
        return []

    def _extract_string_section_items(self, sections: list[dict[str, Any]], key: str) -> list[str]:
        section = next((item for item in sections if item['section_key'] == key), None)
        if not section:
            return []
        raw_text = _clean_string(section.get('raw_text'))
        items = [piece.strip('• ').strip() for piece in re.split(r'\n|[|;]', raw_text) if piece.strip()]
        return self._normalize_skill_items(items)

    def _extract_claimed_experience_text(self, text: str) -> str | None:
        match = self.exp_re.search(text)
        return match.group(0).strip() if match else None

    def _infer_headline(self, lines: list[str], summary: str, objective: str) -> str:
        for line in lines[1:8]:
            if len(line) <= 80 and not self.email_re.search(line) and not self.phone_re.search(line):
                return line
        return summary[:120] if summary else objective[:120]

    def _normalize_skill_items(self, items: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in items:
            clean = item.strip('• ').strip()
            if not clean:
                continue
            if self._looks_like_heading(clean):
                continue
            if not _is_likely_skill_item(clean):
                continue
            normalized.append(clean)
        return _clean_string_list(normalized)


class ResumeProcessingService:
    parser_version = 'v2'

    def __init__(self) -> None:
        self.text_extractor = ResumeTextExtractor()
        self.ai_extractor = OpenAIResumeExtractor()
        self.heuristic_extractor = HeuristicResumeExtractor()

    @transaction.atomic
    def process_profile_resume(self, user: User, profile: UserProfile, interview: Interview | None = None) -> CandidateResume:
        if not profile.resume:
            raise ResumeProcessingError('No resume uploaded for processing.')

        CandidateResume.objects.filter(candidate=user, is_active=True).update(is_active=False)
        resume = CandidateResume.objects.create(
            candidate=user,
            interview=interview,
            source_file=profile.resume.name,
            original_filename=Path(profile.resume.name).name,
            file_size=getattr(profile.resume, 'size', 0) or 0,
            status=CandidateResume.ParseStatus.PROCESSING,
            is_active=True,
        )
        try:
            with profile.resume.open('rb') as resume_file:
                raw_text, mime_type = self.text_extractor.extract(
                    resume_file,
                    filename=profile.resume.name,
                    content_type=getattr(profile.resume.file, 'content_type', '') or '',
                )
            ai_result = self.ai_extractor.extract(raw_text)
            parsed = ai_result.payload or self.heuristic_extractor.extract(raw_text)
            normalized = self._normalize_payload(parsed.data, raw_text)
            self._store_resume(
                resume,
                normalized,
                raw_text,
                mime_type,
                parsed.provider,
                profile,
                ai_configured=ai_result.configured,
                ai_attempted=ai_result.attempted,
                ai_model=ai_result.model,
                ai_error=ai_result.error,
                ai_raw_preview=ai_result.raw_preview,
            )
        except Exception as exc:
            resume.status = CandidateResume.ParseStatus.FAILED
            resume.error_message = str(exc)
            resume.processed_at = timezone.now()
            resume.save(update_fields=['status', 'error_message', 'processed_at', 'updated_at'])
        return resume

    def health_check(self) -> dict[str, Any]:
        storage_backend = f'{default_storage.__class__.__module__}.{default_storage.__class__.__name__}'
        storage_reachable = True
        storage_error = ''
        try:
            default_storage.exists('__shortlistii_storage_healthcheck__')
        except Exception as exc:
            storage_reachable = False
            storage_error = str(exc)

        cloud_storage = storage_backend == 'storages.backends.gcloud.GoogleCloudStorage'
        checks = {
            'pdf_parser': self._module_available('pypdf') or self._module_available('PyPDF2'),
            'docx_parser': self._module_available('docx'),
            'storage_backend': storage_backend,
            'storage_reachable': storage_reachable,
            'storage_error': storage_error,
            'cloud_storage': cloud_storage,
            'cloud_bucket_configured': bool(getattr(settings, 'GS_BUCKET_NAME', '').strip()),
        }
        checks['supported_formats'] = ['pdf', 'docx']
        checks['ready'] = bool(checks['pdf_parser'] and checks['storage_reachable'])
        checks['notes'] = {
            'pdf': 'Text-based PDF parsing requires pypdf or PyPDF2.',
            'docx': 'DOCX parsing works best with python-docx, with XML fallback available.',
            'storage': 'For production uploads, confirm cloud_storage is true and storage_reachable is true.',
        }
        return checks

    def _normalize_payload(self, payload: dict[str, Any], raw_text: str) -> dict[str, Any]:
        contact = self._normalize_contact(payload.get('contact'))
        technical_expertise = self._normalize_technical_expertise(payload.get('technical_expertise'))
        summary = _clean_string(payload.get('summary'))
        objective = _clean_string(payload.get('objective'))
        experience = self._normalize_experience_entries(payload.get('experience'))
        projects = self._normalize_project_entries(payload.get('projects'))
        education = self._normalize_education_entries(payload.get('education'))
        skills = self._sanitize_skills(payload.get('skills'), raw_text, experience, summary, objective)
        technical_expertise = self._sanitize_technical_expertise(technical_expertise, skills)
        certifications = _clean_string_list(payload.get('certifications'))
        achievements = _clean_string_list(payload.get('achievements'))
        languages = [item for item in _clean_string_list(payload.get('languages')) if _is_likely_skill_item(item)]
        headline = _clean_string(payload.get('headline'))
        claimed_experience_text = _clean_optional_string(payload.get('claimed_experience_text')) or self._extract_claimed_experience_text(raw_text)

        experience_summary = self._build_experience_summary(experience)
        candidate_type = self._normalize_candidate_type(payload.get('candidate_type'), experience_summary)
        sections = self._build_sections(
            headline=headline,
            summary=summary,
            objective=objective,
            contact=contact,
            technical_expertise=technical_expertise,
            skills=skills,
            experience=experience,
            projects=projects,
            education=education,
            certifications=certifications,
            achievements=achievements,
            languages=languages,
            source_sections=payload.get('sections'),
        )

        return {
            'headline': headline,
            'summary': summary,
            'objective': objective,
            'candidate_type': candidate_type,
            'contact': contact,
            'technical_expertise': technical_expertise,
            'skills': skills,
            'experience': experience,
            'projects': projects,
            'education': education,
            'certifications': certifications,
            'achievements': achievements,
            'languages': languages,
            'claimed_experience_text': claimed_experience_text,
            'sections': sections,
            'total_professional_experience_months': experience_summary.professional_months,
            'total_internship_experience_months': experience_summary.internship_months,
            'total_combined_experience_months': experience_summary.combined_months,
            'calculation_notes': experience_summary.notes,
            'raw_text_preview': raw_text[:4000],
        }

    def _normalize_contact(self, value: Any) -> dict[str, Any]:
        contact = value if isinstance(value, dict) else {}
        return {
            'name': _clean_string(contact.get('name')),
            'email': _clean_string(contact.get('email')),
            'phone': _clean_string(contact.get('phone')),
            'location': _clean_string(contact.get('location')),
            'links': _clean_string_list(contact.get('links')),
        }

    def _normalize_technical_expertise(self, value: Any) -> dict[str, list[str]]:
        expertise = _empty_technical_expertise()
        if isinstance(value, dict):
            for key in TECHNICAL_EXPERTISE_KEYS:
                expertise[key] = [item for item in _clean_string_list(value.get(key)) if _is_likely_skill_item(item)]
        return expertise

    def _sanitize_skills(
        self,
        skills: Any,
        raw_text: str,
        experience: list[dict[str, Any]],
        summary: str,
        objective: str,
    ) -> list[str]:
        raw_items = _clean_string_list(skills)
        experience_titles = {
            _clean_string(entry.get('title')).casefold()
            for entry in experience
            if _clean_string(entry.get('title'))
        }
        blocked_phrases = {
            phrase.casefold()
            for phrase in SKILL_PROSE_PHRASES
        }
        sanitized: list[str] = []
        seen: set[str] = set()
        for skill in raw_items:
            cleaned = _clean_string(skill)
            folded = cleaned.casefold()
            if not _is_likely_skill_item(cleaned):
                continue
            if folded in experience_titles:
                continue
            if any(phrase in folded for phrase in blocked_phrases):
                continue
            if folded in {'software engineer', 'python developer', 'backend engineer', 'frontend developer', 'full stack developer'}:
                continue
            if folded in seen:
                continue
            seen.add(folded)
            sanitized.append(cleaned)
        return sanitized

    def _sanitize_technical_expertise(self, expertise: dict[str, list[str]], skills: list[str]) -> dict[str, list[str]]:
        sanitized = _empty_technical_expertise()
        for key in TECHNICAL_EXPERTISE_KEYS:
            sanitized[key] = [item for item in _clean_string_list(expertise.get(key)) if _is_likely_skill_item(item)]
        known = {item.casefold() for values in sanitized.values() for item in values}
        sanitized['other'] = sanitized.get('other', [])
        for skill in skills:
            if skill.casefold() in known:
                continue
            if _is_likely_skill_item(skill):
                sanitized['other'].append(skill)
        sanitized['other'] = _clean_string_list(sanitized['other'])
        return sanitized

    def _normalize_experience_entries(self, value: Any) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        if not isinstance(value, list):
            return entries
        for item in value:
            if not isinstance(item, dict):
                continue
            title = _clean_optional_string(item.get('title'))
            company = _clean_optional_string(item.get('company'))
            start_date = self._normalize_date_value(item.get('start_date'), boundary='start')
            end_date = self._normalize_date_value(item.get('end_date'), boundary='end')
            duration_text = _clean_optional_string(item.get('duration_text'))
            normalized = {
                'title': title,
                'company': company,
                'location': _clean_optional_string(item.get('location')),
                'employment_type': self._normalize_employment_type(item.get('employment_type'), item),
                'start_date': start_date,
                'end_date': end_date,
                'is_current': bool(item.get('is_current')),
                'duration_text': duration_text,
                'tech_stack': [],
                'bullets': self._clean_experience_bullets(
                    item.get('bullets'),
                    title=title,
                    company=company,
                    start_date=start_date,
                    end_date=end_date,
                    duration_text=duration_text,
                ),
                'notes': [],
            }
            normalized['tech_stack'] = [
                skill
                for skill in _clean_string_list(item.get('tech_stack'))
                if _is_likely_skill_item(skill) and not _is_likely_prose(skill) and not _is_weak_experience_statement(skill)
            ]
            normalized['notes'] = self._clean_experience_notes(
                item.get('notes'),
                title=title,
                company=company,
                start_date=start_date,
                end_date=end_date,
                duration_text=duration_text,
            )
            if normalized['is_current'] and not normalized['end_date']:
                normalized['end_date'] = parse_resume_date('present', boundary='end').iso_value()
            if (
                normalized['start_date']
                and normalized['end_date']
                and month_index_from_iso(normalized['end_date']) is not None
                and month_index_from_iso(normalized['start_date']) is not None
                and month_index_from_iso(normalized['end_date']) < month_index_from_iso(normalized['start_date'])
            ):
                normalized['notes'].append('Dropped invalid normalized date range because end date was earlier than start date.')
                normalized['start_date'] = None
                normalized['end_date'] = None
            strong_bullets = [bullet for bullet in normalized['bullets'] if _has_strong_experience_bullet(bullet)]
            has_identity = bool(normalized['title'] or normalized['company'])
            has_valid_dates = bool(normalized['start_date'] and normalized['end_date'])
            has_strong_header_signal = _has_strong_role_signal(normalized['title'] or '') or _has_strong_company_signal(normalized['company'] or '')
            normalized['bullets'] = strong_bullets
            if not has_identity and len(strong_bullets) < 2:
                continue
            if has_identity and not strong_bullets and not has_valid_dates and not has_strong_header_signal:
                continue
            if not self._is_meaningful_experience_entry(normalized):
                continue
            entries.append(normalized)
        return entries

    def _clean_experience_bullets(
        self,
        value: Any,
        *,
        title: str | None = None,
        company: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        duration_text: str | None = None,
    ) -> list[str]:
        blocked = _entry_identity_fragments({
            'title': title,
            'company': company,
            'start_date': start_date,
            'end_date': end_date,
            'duration_text': duration_text,
        })
        bullets: list[str] = []
        seen: set[str] = set()

        for bullet in _clean_string_list(value):
            folded = bullet.casefold()
            if folded in blocked or folded in seen:
                continue
            if any(fragment and fragment in folded for fragment in blocked):
                continue
            if _is_company_description_bullet(bullet):
                continue
            if not _has_strong_experience_bullet(bullet):
                continue
            seen.add(folded)
            bullets.append(bullet)

        return bullets

    def _clean_experience_notes(
        self,
        value: Any,
        *,
        title: str | None = None,
        company: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        duration_text: str | None = None,
    ) -> list[str]:
        blocked = _entry_identity_fragments({
            'title': title,
            'company': company,
            'start_date': start_date,
            'end_date': end_date,
            'duration_text': duration_text,
        })
        notes: list[str] = []
        seen: set[str] = set()
        for note in _clean_string_list(value):
            folded = note.casefold()
            if not note or folded in blocked or folded in seen:
                continue
            if any(fragment and fragment in folded for fragment in blocked):
                continue
            seen.add(folded)
            notes.append(note)
        return notes

    def _normalize_project_entries(self, value: Any) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        if not isinstance(value, list):
            return entries
        for item in value:
            if not isinstance(item, dict):
                continue
            entries.append({
                'name': _clean_optional_string(item.get('name')),
                'role': _clean_optional_string(item.get('role')),
                'organization': _clean_optional_string(item.get('organization')),
                'start_date': self._normalize_date_value(item.get('start_date'), boundary='start'),
                'end_date': self._normalize_date_value(item.get('end_date'), boundary='end'),
                'tech_stack': _clean_string_list(item.get('tech_stack')),
                'bullets': _clean_string_list(item.get('bullets')),
                'notes': _clean_string_list(item.get('notes')),
            })
        return entries

    def _normalize_education_entries(self, value: Any) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        if not isinstance(value, list):
            return entries
        for item in value:
            if not isinstance(item, dict):
                continue
            entries.append({
                'degree': _clean_optional_string(item.get('degree')),
                'institution': _clean_optional_string(item.get('institution')),
                'location': _clean_optional_string(item.get('location')),
                'start_date': self._normalize_date_value(item.get('start_date'), boundary='start'),
                'end_date': self._normalize_date_value(item.get('end_date'), boundary='end'),
                'grade': _clean_optional_string(item.get('grade')),
                'notes': _clean_string_list(item.get('notes')),
            })
        return entries

    def _normalize_date_value(self, value: Any, *, boundary: Literal['start', 'end']) -> str | None:
        text = _clean_optional_string(value)
        if not text:
            return None
        parsed = parse_resume_date(text, boundary=boundary)
        if parsed:
            return parsed.iso_value()
        compact = _clean_string(text)
        if re.fullmatch(r'\d{4}', compact):
            return compact
        return None

    def _normalize_employment_type(self, value: Any, item: dict[str, Any]) -> str:
        normalized = _clean_string(value).lower().replace('-', '_')
        if normalized in EMPLOYMENT_TYPE_VALUES:
            return normalized
        return ExperienceCalculator.normalize_employment_type(item)

    def _is_meaningful_experience_entry(self, entry: dict[str, Any]) -> bool:
        return _is_meaningful_experience_entry(entry)

    def _build_experience_summary(self, experience: list[dict[str, Any]]) -> ExperienceCalculationResult:
        return ExperienceCalculator.summarize(experience)

    def _normalize_candidate_type(self, value: Any, summary: ExperienceCalculationResult) -> str:
        normalized = _clean_string(value).lower()
        if normalized in {'experienced', 'fresher'}:
            return normalized
        return 'experienced' if summary.professional_months or summary.internship_months else 'fresher'

    def _build_sections(
        self,
        *,
        headline: str,
        summary: str,
        objective: str,
        contact: dict[str, Any],
        technical_expertise: dict[str, list[str]],
        skills: list[str],
        experience: list[dict[str, Any]],
        projects: list[dict[str, Any]],
        education: list[dict[str, Any]],
        certifications: list[str],
        achievements: list[str],
        languages: list[str],
        source_sections: Any,
    ) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        valid_experience_entries: list[dict[str, Any]] = []
        experience_items: list[dict[str, Any]] = []
        for entry in experience:
            item = self._experience_section_item(entry)
            if item is None:
                continue
            valid_experience_entries.append(entry)
            experience_items.append(item)
        experience_text = self._experience_text(valid_experience_entries)

        def add_section(section_key: str, title: str, content: dict[str, Any], raw_text: str) -> None:
            normalized_key = _clean_string(section_key).lower().replace(' ', '_')
            if normalized_key in seen_keys:
                return
            if not raw_text and not content.get('items'):
                return
            sections.append({
                'section_key': normalized_key,
                'title': title,
                'section_type': normalized_key,
                'display_order': len(sections),
                'content': content,
                'raw_text': raw_text,
            })
            seen_keys.add(normalized_key)

        add_section('summary', 'Summary', {'text': summary, 'items': [summary] if summary else []}, summary)
        add_section('objective', 'Objective', {'text': objective, 'items': [objective] if objective else []}, objective)

        expertise_items = [{'label': key.replace('_', ' ').title(), 'value': ', '.join(values)} for key, values in technical_expertise.items() if values]
        expertise_text = '\n'.join(item['value'] for item in expertise_items)
        add_section('technical_expertise', 'Technical Expertise', {'text': expertise_text, 'items': expertise_items}, expertise_text)
        add_section('skills', 'Skills', {'text': '\n'.join(skills), 'items': skills}, '\n'.join(skills))

        if experience_items:
            add_section(
                'experience',
                'Experience',
                {
                    'text': experience_text,
                    'items': experience_items,
                },
                experience_text,
            )
        add_section(
            'projects',
            'Projects',
            {'text': self._project_text(projects), 'items': [self._project_section_item(entry) for entry in projects]},
            self._project_text(projects),
        )
        add_section(
            'education',
            'Education',
            {'text': self._education_text(education), 'items': [self._education_section_item(entry) for entry in education]},
            self._education_text(education),
        )
        add_section('certifications', 'Certifications', {'text': '\n'.join(certifications), 'items': certifications}, '\n'.join(certifications))
        add_section('achievements', 'Achievements', {'text': '\n'.join(achievements), 'items': achievements}, '\n'.join(achievements))
        add_section('languages', 'Languages', {'text': '\n'.join(languages), 'items': languages}, '\n'.join(languages))

        contact_items = [
            {'label': 'name', 'value': contact['name']},
            {'label': 'email', 'value': contact['email']},
            {'label': 'phone', 'value': contact['phone']},
            {'label': 'location', 'value': contact['location']},
        ] + [{'label': 'link', 'value': link} for link in contact['links']]
        contact_items = [item for item in contact_items if item['value']]
        add_section(
            'contact',
            'Contact',
            {'text': '\n'.join(item['value'] for item in contact_items), 'items': contact_items},
            '\n'.join(item['value'] for item in contact_items),
        )

        self._merge_source_sections_as_fallback(sections, source_sections, seen_keys)

        for index, section in enumerate(sections):
            section['display_order'] = index
        return sections

    def _merge_source_sections_as_fallback(self, sections: list[dict[str, Any]], source_sections: Any, seen_keys: set[str]) -> None:
        if not isinstance(source_sections, list):
            return
        for raw_section in source_sections:
            normalized_section = self._normalize_source_section(raw_section, existing_keys=seen_keys)
            if not normalized_section:
                continue
            section_key = normalized_section['section_key']
            if section_key in seen_keys:
                continue
            sections.append({
                'section_key': section_key,
                'title': normalized_section['title'],
                'section_type': normalized_section['section_type'],
                'display_order': len(sections),
                'content': normalized_section['content'],
                'raw_text': normalized_section['raw_text'],
            })
            seen_keys.add(section_key)

    def _normalize_source_section(self, section: Any, *, existing_keys: set[str] | None = None) -> dict[str, Any] | None:
        if not isinstance(section, dict):
            return None
        section_key = _clean_string(section.get('section_key')).lower().replace(' ', '_')
        if not section_key:
            return None
        if section_key not in CANONICAL_SECTION_KEYS and section_key not in KNOWN_EXTRA_SECTION_KEYS:
            return None
        title = _clean_string(section.get('title')) or section_key.replace('_', ' ').title()
        section_type = _clean_string(section.get('section_type')) or section_key
        content = section.get('content') if isinstance(section.get('content'), dict) else {}
        items = content.get('items') if isinstance(content.get('items'), list) else []
        raw_text = _clean_string(content.get('text') or section.get('raw_text'))
        if section_key in {'skills', 'languages'}:
            items = [item for item in items if isinstance(item, str) and _is_likely_skill_item(item)]
        elif section_key == 'contact':
            items = [
                item for item in items
                if isinstance(item, dict) and _clean_string(item.get('value'))
            ]
        elif section_key == 'experience':
            items = [item for item in items if isinstance(item, dict) and any(_clean_string(item.get(field)) for field in ('title', 'company', 'duration', 'start_date', 'end_date'))]
        if not self._is_meaningful_section(section_key, {'text': raw_text, 'items': items}, raw_text):
            return None
        if existing_keys and section_key in existing_keys and section_key in CANONICAL_SECTION_KEYS:
            return None
        if existing_keys and section_key in existing_keys and section_key in {'skills', 'languages', 'contact'} and len(raw_text) > 120:
            return None
        if section_key == 'skills' and items:
            prose_count = sum(1 for item in items if isinstance(item, str) and _is_likely_prose(item))
            if prose_count >= max(1, len(items) // 2 + 1):
                return None
        if section_key == 'experience' and existing_keys and 'experience' in existing_keys and not items:
            return None
        return {
            'section_key': section_key,
            'title': title,
            'section_type': section_type,
            'content': {
                'text': raw_text,
                'items': items,
            },
            'raw_text': raw_text,
        }

    def _is_likely_skill_item(self, text: str) -> bool:
        return _is_likely_skill_item(text)

    def _is_likely_prose(self, text: str) -> bool:
        return _is_likely_prose(text)

    def _is_likely_company_or_role_line(self, text: str) -> bool:
        return _is_likely_company_or_role_line(text)

    def _is_meaningful_section(self, section_key: str, content: dict[str, Any], raw_text: str) -> bool:
        items = content.get('items') if isinstance(content.get('items'), list) else []
        if not raw_text and not items:
            return False
        if section_key in {'skills', 'languages'}:
            skill_items = [item for item in items if isinstance(item, str) and _is_likely_skill_item(item)]
            if skill_items:
                return True
            return any(_is_likely_skill_item(piece) for piece in raw_text.splitlines())
        if section_key == 'contact':
            return any(
                (isinstance(item, dict) and _clean_string(item.get('value')))
                for item in items
            ) or bool(raw_text)
        if section_key == 'experience':
            dict_items = [item for item in items if isinstance(item, dict)]
            if dict_items:
                return any(any(_clean_string(item.get(field)) for field in ('title', 'company', 'duration', 'start_date', 'end_date', 'bullets')) for item in dict_items)
            return bool(DATE_RANGE_RE.search(raw_text) or re.search(r'\b(?:engineer|developer|intern|manager|analyst)\b', raw_text, re.IGNORECASE))
        return bool(raw_text or items)

    def _experience_text(self, experience: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for entry in experience:
            if not self._is_meaningful_experience_entry(entry):
                continue
            display_title = _clean_string(entry.get('title')) or _clean_string(entry.get('company'))
            company = _clean_string(entry.get('company'))
            header_parts = [display_title]
            if company and company != display_title:
                header_parts.append(company)
            header = ' | '.join(part for part in header_parts if part)
            duration = self._display_duration(entry.get('start_date'), entry.get('end_date'), entry.get('duration_text'))
            if duration:
                header = f'{header} | {duration}' if header else duration
            header = header.strip(' |')
            if header:
                lines.append(header)
            lines.extend(self._clean_experience_bullets(entry.get('bullets')))
        return '\n'.join(line for line in lines if line)

    def _project_text(self, projects: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for entry in projects:
            header = ' | '.join(part for part in [entry.get('name'), entry.get('organization')] if part)
            lines.append(header.strip(' |'))
            lines.extend(_clean_string_list(entry.get('bullets')))
        return '\n'.join(line for line in lines if line)

    def _education_text(self, education: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for entry in education:
            lines.append(' | '.join(part for part in [entry.get('degree'), entry.get('institution')] if part).strip(' |'))
            if entry.get('grade'):
                lines.append(_clean_string(entry.get('grade')))
        return '\n'.join(line for line in lines if line)

    def _display_duration(self, start_date: Any, end_date: Any, duration_text: Any = None) -> str:
        explicit = _clean_string(duration_text)
        if explicit:
            return explicit
        start = _clean_string(start_date)
        end = _clean_string(end_date)
        if start and end:
            return f'{start} - {end}'
        return start or end

    def _experience_section_item(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        if not self._is_meaningful_experience_entry(entry):
            return None

        raw_title = _clean_optional_string(entry.get('title'))
        company = _clean_optional_string(entry.get('company'))
        title = raw_title

        credible_identity = _has_credible_identity(_clean_string(raw_title), _clean_string(company))
        has_valid_dates = _has_valid_experience_dates(entry)

        bullets = self._clean_experience_bullets(
            entry.get('bullets'),
            title=title,
            company=company,
            start_date=_clean_optional_string(entry.get('start_date')),
            end_date=_clean_optional_string(entry.get('end_date')),
            duration_text=_clean_optional_string(entry.get('duration_text')),
        )
        strong_bullets = [bullet for bullet in bullets if _has_strong_experience_bullet(bullet)]

        if not (
            (credible_identity and strong_bullets)
            or (credible_identity and has_valid_dates and company)
            or (has_valid_dates and len(strong_bullets) >= 2)
        ):
            return None
    
    def _project_section_item(self, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            'title': entry.get('name'),
            'company': entry.get('organization'),
            'location': None,
            'role': entry.get('role'),
            'start_date': entry.get('start_date'),
            'end_date': entry.get('end_date'),
            'duration': self._display_duration(entry.get('start_date'), entry.get('end_date')),
            'duration_text': self._display_duration(entry.get('start_date'), entry.get('end_date')),
            'tech_stack': _clean_string_list(entry.get('tech_stack')),
            'bullets': _clean_string_list(entry.get('bullets')),
            'details': _clean_string_list(entry.get('bullets')),
            'notes': _clean_string_list(entry.get('notes')),
            'degree': None,
            'institution': None,
            'issuer': None,
            'label': '',
            'value': '',
            'description': '',
        }

    def _education_section_item(self, entry: dict[str, Any]) -> dict[str, Any]:
        duration = self._display_duration(entry.get('start_date'), entry.get('end_date'))
        details = _clean_string_list(entry.get('notes'))
        if entry.get('grade'):
            details = [str(entry.get('grade'))] + details
        return {
            'title': entry.get('degree'),
            'degree': entry.get('degree'),
            'institution': entry.get('institution'),
            'company': None,
            'location': entry.get('location'),
            'start_date': entry.get('start_date'),
            'end_date': entry.get('end_date'),
            'duration': duration,
            'duration_text': duration,
            'role': None,
            'tech_stack': [],
            'bullets': [],
            'details': details,
            'notes': _clean_string_list(entry.get('notes')),
            'issuer': None,
            'label': '',
            'value': '',
            'description': '',
        }

    def _extract_claimed_experience_text(self, raw_text: str) -> str | None:
        match = re.search(r'(\d+(?:\.\d+)?)\+?\s+(?:years?|yrs?)\s+(?:of\s+)?experience', raw_text, re.IGNORECASE)
        return match.group(0).strip() if match else None

    def _store_resume(
        self,
        resume: CandidateResume,
        payload: dict[str, Any],
        raw_text: str,
        mime_type: str,
        provider: str,
        profile: UserProfile,
        ai_configured: bool,
        ai_attempted: bool,
        ai_model: str,
        ai_error: str,
        ai_raw_preview: str,
    ) -> None:
        professional_months = int(payload.get('total_professional_experience_months') or 0)
        experience_decimal = (Decimal(professional_months) / Decimal('12')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        current_role = ExperienceCalculator.select_current_role(payload['experience'])
        current_title = _clean_string((current_role or {}).get('title'))
        current_company = _clean_string((current_role or {}).get('company'))

        resume.mime_type = mime_type
        resume.parser_provider = provider
        resume.parser_version = self.parser_version
        resume.status = CandidateResume.ParseStatus.COMPLETED
        payload['ai_configured'] = ai_configured
        payload['ai_attempted'] = ai_attempted
        payload['ai_model'] = ai_model
        payload['ai_error'] = ai_error
        payload['ai_raw_preview'] = ai_raw_preview
        payload['fallback_used'] = provider != 'openai'
        payload['fallback_provider'] = provider if provider != 'openai' else ''
        resume.structured_data = payload
        resume.raw_text = raw_text
        resume.candidate_type = payload['candidate_type']
        resume.headline = payload['headline']
        resume.summary = payload['summary']
        resume.email = payload['contact']['email'] or profile.user.email
        resume.phone = payload['contact']['phone'] or profile.phone or ''
        resume.location = payload['contact']['location']
        resume.total_experience_years = experience_decimal
        resume.current_title = current_title
        resume.current_company = current_company
        resume.processed_at = timezone.now()
        resume.error_message = ''
        resume.save()

        CandidateResumeSection.objects.filter(resume=resume).delete()
        for section in payload['sections']:
            CandidateResumeSection.objects.create(
                resume=resume,
                section_key=section['section_key'],
                title=section['title'],
                section_type=section['section_type'],
                display_order=section['display_order'],
                content=section['content'],
                raw_text=section['raw_text'],
            )

    def serialize_resume(self, resume: CandidateResume | None) -> dict[str, Any]:
        if not resume:
            return {
                'available': False,
                'headline': '',
                'summary': '',
                'objective': '',
                'candidate_type': '',
                'contact': {},
                'technical_expertise': _empty_technical_expertise(),
                'skills': [],
                'experience': [],
                'projects': [],
                'education': [],
                'certifications': [],
                'achievements': [],
                'languages': [],
                'claimed_experience_text': '',
                'sections': [],
                'status': 'missing',
                'error_message': '',
                'parser_provider': '',
                'parser_version': '',
                'raw_text_preview': '',
                'ai_configured': False,
                'ai_attempted': False,
                'ai_model': '',
                'ai_error': '',
                'ai_raw_preview': '',
                'fallback_used': False,
                'fallback_provider': '',
                'total_professional_experience_months': 0,
                'total_internship_experience_months': 0,
                'total_combined_experience_months': 0,
                'calculation_notes': [],
            }
        structured = resume.structured_data or {}
        return {
            'available': resume.status == CandidateResume.ParseStatus.COMPLETED,
            'status': resume.status,
            'error_message': resume.error_message,
            'headline': resume.headline,
            'summary': resume.summary,
            'objective': structured.get('objective', ''),
            'candidate_type': resume.candidate_type,
            'contact': {
                'email': resume.email,
                'phone': resume.phone,
                'location': resume.location,
                'name': structured.get('contact', {}).get('name', '') if isinstance(structured.get('contact'), dict) else '',
                'links': structured.get('contact', {}).get('links', []) if isinstance(structured.get('contact'), dict) else [],
            },
            'technical_expertise': structured.get('technical_expertise', _empty_technical_expertise()),
            'skills': structured.get('skills') if isinstance(structured, dict) else [],
            'experience': structured.get('experience', []) if isinstance(structured, dict) else [],
            'projects': structured.get('projects', []) if isinstance(structured, dict) else [],
            'education': structured.get('education', []) if isinstance(structured, dict) else [],
            'certifications': structured.get('certifications', []) if isinstance(structured, dict) else [],
            'achievements': structured.get('achievements', []) if isinstance(structured, dict) else [],
            'languages': structured.get('languages', []) if isinstance(structured, dict) else [],
            'claimed_experience_text': structured.get('claimed_experience_text', '') if isinstance(structured, dict) else '',
            'sections': [
                {
                    'section_key': section.section_key,
                    'title': section.title,
                    'section_type': section.section_type,
                    'display_order': section.display_order,
                    'content': section.content,
                    'raw_text': section.raw_text,
                }
                for section in resume.sections.all().order_by('display_order', 'id')
            ],
            'processed_at': resume.processed_at.isoformat() if resume.processed_at else '',
            'source_file': resume.original_filename,
            'parser_provider': resume.parser_provider,
            'parser_version': resume.parser_version,
            'raw_text_preview': structured.get('raw_text_preview', ''),
            'ai_configured': structured.get('ai_configured', False),
            'ai_attempted': structured.get('ai_attempted', False),
            'ai_model': structured.get('ai_model', ''),
            'ai_error': structured.get('ai_error', ''),
            'ai_raw_preview': structured.get('ai_raw_preview', ''),
            'fallback_used': structured.get('fallback_used', False),
            'fallback_provider': structured.get('fallback_provider', ''),
            'total_professional_experience_months': structured.get('total_professional_experience_months', 0),
            'total_internship_experience_months': structured.get('total_internship_experience_months', 0),
            'total_combined_experience_months': structured.get('total_combined_experience_months', 0),
            'calculation_notes': structured.get('calculation_notes', []),
        }

    def _module_available(self, module_name: str) -> bool:
        try:
            __import__(module_name)
            return True
        except Exception:
            return False
