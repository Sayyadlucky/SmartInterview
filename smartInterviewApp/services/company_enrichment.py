from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.db import close_old_connections
from django.db import transaction

from smartInterviewApp.models import CompanyProfile


logger = logging.getLogger('smartInterview.company_enrichment')
_ENRICHMENT_LOCK = threading.Lock()
_ACTIVE_ENRICHMENTS: set[int] = set()

TBD_VALUE = 'TBD'
DEFAULT_TIMEZONE = 'Asia/Kolkata'
DEFAULT_COUNTRY = 'India'
COMPANY_URL_ATTRIBUTE_CANDIDATES = (
    'company_link',
    'company_url',
    'company_website',
    'website',
)
STRING_FIELDS = {
    'legal_name',
    'display_name',
    'description',
    'industry',
    'sub_industry',
    'website',
    'careers_page',
    'linkedin_url',
    'twitter_url',
    'logo_url',
    'contact_email',
    'contact_phone',
    'alternate_phone',
    'address_line_1',
    'address_line_2',
    'landmark',
    'city',
    'state',
    'postal_code',
    'country',
    'headquarters',
    'registration_number',
    'tax_identifier',
    'currency_code',
    'timezone',
}
INTEGER_FIELDS = {'employee_count', 'founded_year'}
IMPORTANT_STRING_FIELDS = {
    'legal_name',
    'display_name',
    'description',
    'address_line_1',
    'city',
    'state',
    'postal_code',
    'country',
    'headquarters',
    'contact_email',
    'contact_phone',
    'alternate_phone',
}
PROFILE_FIELDS = (
    'legal_name',
    'display_name',
    'description',
    'industry',
    'sub_industry',
    'company_type',
    'company_stage',
    'company_size',
    'employee_count',
    'founded_year',
    'website',
    'careers_page',
    'linkedin_url',
    'twitter_url',
    'logo_url',
    'contact_email',
    'contact_phone',
    'alternate_phone',
    'address_line_1',
    'address_line_2',
    'landmark',
    'city',
    'state',
    'postal_code',
    'country',
    'headquarters',
    'registration_number',
    'tax_identifier',
    'currency_code',
    'timezone',
)


def extract_company_details_from_url(company_url: str) -> dict[str, Any]:
    """Extract company fields from a public company URL via OpenAI structured output."""
    api_key = getattr(settings, 'OPENAI_API_KEY', '').strip()
    model = getattr(settings, 'OPENAI_MODEL', '').strip() or getattr(settings, 'OPENAI_RESUME_MODEL', 'gpt-4.1-mini').strip()
    if not api_key:
        raise RuntimeError('Company enrichment requires OPENAI_API_KEY.')

    page_context = _fetch_company_url_context(company_url)
    prompt = (
        'Extract company details from the given URL. '
        'Use the exact company operating on that domain. '
        'Prefer facts from the provided homepage content and only use other public sources if they clearly match the same company. '
        'Do not confuse this company with similarly named companies in other countries. '
        'If unsure, return null. '
        'Do not hallucinate. '
        'Map only to the provided schema. '
        'Return JSON only.\n\n'
        f'Input URL: {company_url}\n'
        f'Normalized domain: {page_context["domain"]}\n'
        f'Fetched URL: {page_context["resolved_url"]}\n'
        f'Homepage title: {page_context["title"]}\n'
        f'Homepage site name: {page_context["site_name"]}\n'
        f'Homepage meta description: {page_context["description"]}\n'
        f'Homepage logo URL candidate: {page_context["logo_url"]}\n'
        f'Homepage text excerpt:\n{page_context["body_excerpt"]}'
    )
    body = json.dumps({
        'model': model,
        'input': prompt,
        'temperature': 0.1,
        'text': {
            'format': {
                'type': 'json_schema',
                'name': 'company_profile_extract',
                'strict': True,
                'schema': _response_schema(),
            }
        },
    }).encode('utf-8')

    request = urllib.request.Request(
        'https://api.openai.com/v1/responses',
        data=body,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'OpenAI company enrichment HTTP error {exc.code}: {detail[:400]}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'OpenAI company enrichment network error: {exc.reason}') from exc

    output_text = _extract_output_text(payload)
    if not output_text:
        raise RuntimeError('OpenAI company enrichment returned no structured output.')
    extracted = json.loads(output_text)
    if not isinstance(extracted, dict):
        raise RuntimeError('OpenAI company enrichment returned an invalid payload.')
    if not _clean_string(extracted.get('logo_url')):
        extracted['logo_url'] = page_context.get('logo_url', '')
    return extracted


def ensure_company_profile_for_user(user: User) -> CompanyProfile | None:
    """Ensure an admin user has a profile and bootstrap enrichment only on first create."""
    if not getattr(user, 'is_authenticated', False):
        return None

    profile = getattr(user, 'profile', None)
    role = getattr(profile, 'role', '')
    if role != 'admin':
        logger.debug('Skipping company bootstrap for non-admin user_id=%s role=%s', user.id, role)
        return None

    company_url = _resolve_company_url_for_user(user)
    if not company_url:
        logger.info('No company URL linked for user_id=%s', user.id)
        return None

    logger.info('Company URL found for user_id=%s url=%s', user.id, company_url)
    fallback_payload = _normalize_company_payload({}, company_url)

    with transaction.atomic():
        company_profile, created = CompanyProfile.objects.get_or_create(
            admin=user,
            defaults=fallback_payload,
        )
    logger.info(
        'Company profile %s for user_id=%s profile_id=%s',
        'created' if created else 'loaded',
        user.id,
        company_profile.id,
    )

    if profile and getattr(profile, 'company_id', None) != company_profile.id:
        profile.company = company_profile
        profile.save(update_fields=['company'])

    if not created:
        logger.info('Company profile already exists for user_id=%s; skipping dashboard-triggered enrichment', user.id)
        return company_profile

    if created:
        logger.info('Fallback company profile created for user_id=%s with default placeholders', user.id)
    _trigger_company_enrichment_in_background(user.id, company_url)

    return company_profile


def _trigger_company_enrichment_in_background(user_id: int, company_url: str) -> None:
    with _ENRICHMENT_LOCK:
        if user_id in _ACTIVE_ENRICHMENTS:
            logger.info('Company enrichment already running for user_id=%s', user_id)
            return
        _ACTIVE_ENRICHMENTS.add(user_id)

    worker = threading.Thread(
        target=_run_company_enrichment,
        args=(user_id, company_url),
        daemon=True,
        name=f'company-enrichment-{user_id}',
    )
    worker.start()
    logger.info('Company enrichment scheduled in background for user_id=%s', user_id)


def _run_company_enrichment(user_id: int, company_url: str) -> None:
    close_old_connections()
    try:
        user = User.objects.select_related('profile', 'company_profile').get(id=user_id)
        company_profile = getattr(user, 'company_profile', None)
        if not company_profile:
            logger.warning('Company enrichment skipped because no profile exists for user_id=%s', user_id)
            return
        if not _is_company_profile_incomplete(company_profile):
            logger.info('Company enrichment skipped because profile is already complete for user_id=%s', user_id)
            return

        extracted_data: dict[str, Any] = {}
        try:
            extracted_data = extract_company_details_from_url(company_url)
            logger.info('OpenAI company enrichment succeeded for user_id=%s', user_id)
        except Exception:
            logger.exception('OpenAI company enrichment failed for user_id=%s url=%s', user_id, company_url)

        normalized_payload = _normalize_company_payload(extracted_data, company_url)
        updated_fields = _apply_company_profile_updates(company_profile, normalized_payload)
        if updated_fields:
            company_profile.save(update_fields=updated_fields + ['updated_at'])
            logger.info('Company profile populated for user_id=%s fields=%s', user_id, ','.join(updated_fields))
        else:
            logger.info('No company profile fields needed updates for user_id=%s', user_id)
    finally:
        with _ENRICHMENT_LOCK:
            _ACTIVE_ENRICHMENTS.discard(user_id)
        close_old_connections()


def _resolve_company_url_for_user(user: User) -> str:
    """Check likely user/profile URL attributes without assuming one schema name."""
    profile = getattr(user, 'profile', None)
    for source in (profile, user):
        if not source:
            continue
        for attr in COMPANY_URL_ATTRIBUTE_CANDIDATES:
            value = _clean_string(getattr(source, attr, ''))
            if value:
                return value
    return ''


def _fetch_company_url_context(company_url: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(company_url)
    domain = (parsed.netloc or '').lower()
    if domain.startswith('www.'):
        domain = domain[4:]

    request = urllib.request.Request(
        company_url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36',
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read(150000).decode('utf-8', errors='ignore')
            resolved_url = response.geturl()
    except Exception as exc:
        logger.warning('Unable to fetch company homepage context for url=%s error=%s', company_url, exc)
        return {
            'domain': domain,
            'resolved_url': company_url,
            'title': '',
            'site_name': '',
            'description': '',
            'logo_url': '',
            'body_excerpt': '',
        }

    return {
        'domain': domain,
        'resolved_url': resolved_url,
        'title': _extract_html_tag(html, 'title'),
        'site_name': _extract_meta_content(html, 'property', 'og:site_name'),
        'description': _extract_meta_content(html, 'name', 'description') or _extract_meta_content(html, 'property', 'og:description'),
        'logo_url': _extract_logo_url(html, resolved_url),
        'body_excerpt': _extract_body_excerpt(html),
    }


def _extract_html_tag(html: str, tag_name: str) -> str:
    match = re.search(rf'<{tag_name}[^>]*>(.*?)</{tag_name}>', html, flags=re.IGNORECASE | re.DOTALL)
    return _collapse_whitespace(_strip_html(match.group(1))) if match else ''


def _extract_meta_content(html: str, attr_name: str, attr_value: str) -> str:
    pattern = rf'<meta[^>]+{attr_name}=["\']{re.escape(attr_value)}["\'][^>]+content=["\'](.*?)["\']'
    match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        pattern = rf'<meta[^>]+content=["\'](.*?)["\'][^>]+{attr_name}=["\']{re.escape(attr_value)}["\']'
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
    return _collapse_whitespace(_strip_html(match.group(1))) if match else ''


def _extract_body_excerpt(html: str) -> str:
    cleaned = re.sub(r'<script.*?>.*?</script>', ' ', html, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r'<style.*?>.*?</style>', ' ', cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r'<noscript.*?>.*?</noscript>', ' ', cleaned, flags=re.IGNORECASE | re.DOTALL)
    text = _collapse_whitespace(_strip_html(cleaned))
    return text[:4000]


def _extract_logo_url(html: str, base_url: str) -> str:
    candidates: list[tuple[str, str]] = [
        ('og:image', _extract_meta_content(html, 'property', 'og:image')),
        ('twitter:image', _extract_meta_content(html, 'name', 'twitter:image')),
    ]
    link_patterns = (
        ('icon-link', r'<link[^>]+rel=["\'][^"\']*(?:icon|apple-touch-icon)[^"\']*["\'][^>]+href=["\'](.*?)["\']'),
        ('icon-link', r'<link[^>]+href=["\'](.*?)["\'][^>]+rel=["\'][^"\']*(?:icon|apple-touch-icon)[^"\']*["\']'),
        ('logo-img', r'<img[^>]+(?:class|id|alt|src)=["\'][^"\']*(?:logo|brand|navbar-brand|site-logo|header-logo)[^"\']*["\'][^>]+src=["\'](.*?)["\']'),
        ('logo-img', r'<img[^>]+src=["\'](.*?)["\'][^>]+(?:class|id|alt)=["\'][^"\']*(?:logo|brand|navbar-brand|site-logo|header-logo)[^"\']*["\']'),
    )
    for source, pattern in link_patterns:
        for match in re.finditer(pattern, html, flags=re.IGNORECASE | re.DOTALL):
            candidates.append((source, match.group(1)))

    best_url = ''
    best_score = -10_000
    for source, candidate in candidates:
        normalized = _normalize_asset_url(candidate, base_url)
        if not normalized:
            continue
        score = _score_logo_candidate(normalized, source)
        if score > best_score:
            best_score = score
            best_url = normalized
    if best_score > 0:
        return best_url
    return ''


def _score_logo_candidate(url: str, source: str) -> int:
    lowered = url.lower()
    score = 0

    if source == 'logo-img':
        score += 120
    elif source == 'icon-link':
        score += 40
    elif source in {'og:image', 'twitter:image'}:
        score += 5

    preferred_terms = (
        'logo',
        'brand',
        'site-logo',
        'header-logo',
        'navbar-brand',
        'logotype',
    )
    for term in preferred_terms:
        if term in lowered:
            score += 80

    discouraged_terms = (
        'hero',
        'banner',
        'slider',
        'stock',
        'working',
        'laptop',
        'employee',
        'leader',
        'people',
        'team',
        'office',
        'scaled',
        'background',
    )
    for term in discouraged_terms:
        if term in lowered:
            score -= 120

    if '/wp-content/uploads/' in lowered:
        score -= 40

    if lowered.endswith('.svg'):
        score += 90
    elif lowered.endswith('.png') or lowered.endswith('.webp'):
        score += 35
    elif lowered.endswith('.jpg') or lowered.endswith('.jpeg'):
        score -= 10

    if 'favicon' in lowered or 'apple-touch-icon' in lowered or '/icon' in lowered:
        score += 15

    return score


def _normalize_asset_url(value: str, base_url: str) -> str:
    raw = _clean_string(value)
    if not raw:
        return ''
    if raw.startswith('data:'):
        return ''
    absolute = urllib.parse.urljoin(base_url, raw)
    parsed = urllib.parse.urlparse(absolute)
    if parsed.scheme not in {'http', 'https'}:
        return ''
    return absolute


def _strip_html(value: str) -> str:
    return re.sub(r'<[^>]+>', ' ', value or '')


def _collapse_whitespace(value: str) -> str:
    return ' '.join((value or '').split())


def _normalize_company_payload(raw_data: dict[str, Any] | None, company_url: str) -> dict[str, Any]:
    data = raw_data or {}
    normalized: dict[str, Any] = {}

    for field in STRING_FIELDS:
        value = _clean_string(data.get(field))
        if not value and field in IMPORTANT_STRING_FIELDS:
            if field == 'country':
                value = DEFAULT_COUNTRY
            elif field == 'timezone':
                value = DEFAULT_TIMEZONE
            else:
                value = TBD_VALUE
        normalized[field] = value

    for field in INTEGER_FIELDS:
        normalized[field] = _clean_integer(data.get(field))

    normalized['website'] = normalized.get('website') or _clean_string(company_url) or TBD_VALUE
    normalized['logo_url'] = _normalize_asset_url(data.get('logo_url') or '', normalized['website'])
    normalized['legal_name'] = normalized.get('legal_name') or normalized.get('display_name') or TBD_VALUE
    normalized['display_name'] = normalized.get('display_name') or normalized.get('legal_name') or TBD_VALUE
    normalized['description'] = normalized.get('description') or TBD_VALUE
    normalized['contact_email'] = normalized.get('contact_email') or TBD_VALUE
    normalized['contact_phone'] = normalized.get('contact_phone') or TBD_VALUE
    normalized['alternate_phone'] = normalized.get('alternate_phone') or TBD_VALUE
    normalized['address_line_1'] = normalized.get('address_line_1') or TBD_VALUE
    normalized['city'] = normalized.get('city') or TBD_VALUE
    normalized['state'] = normalized.get('state') or TBD_VALUE
    normalized['postal_code'] = normalized.get('postal_code') or TBD_VALUE
    normalized['country'] = normalized.get('country') or DEFAULT_COUNTRY
    normalized['headquarters'] = normalized.get('headquarters') or TBD_VALUE
    normalized['timezone'] = normalized.get('timezone') or DEFAULT_TIMEZONE
    normalized['company_type'] = _normalize_choice(
        data.get('company_type'),
        CompanyProfile.CompanyType.values,
        CompanyProfile.CompanyType.OTHER,
        {
            'private limited': CompanyProfile.CompanyType.PRIVATE,
            'private company': CompanyProfile.CompanyType.PRIVATE,
            'public company': CompanyProfile.CompanyType.PUBLIC,
            'sole proprietorship': CompanyProfile.CompanyType.SOLE,
            'consultancy': CompanyProfile.CompanyType.AGENCY,
            'consulting': CompanyProfile.CompanyType.AGENCY,
        },
    )
    normalized['company_stage'] = _normalize_choice(
        data.get('company_stage'),
        CompanyProfile.CompanyStage.values,
        CompanyProfile.CompanyStage.OTHER,
        {
            'series c+': CompanyProfile.CompanyStage.SERIES_C,
            'public': CompanyProfile.CompanyStage.PUBLIC,
            'public market': CompanyProfile.CompanyStage.PUBLIC,
        },
    )
    normalized['company_size'] = _normalize_choice(
        data.get('company_size'),
        CompanyProfile.CompanySize.values,
        '',
        {
            '1-10': CompanyProfile.CompanySize.SOLO,
            '11-50': CompanyProfile.CompanySize.SMALL,
            '51-200': CompanyProfile.CompanySize.MID_SMALL,
            '201-500': CompanyProfile.CompanySize.MID,
            '501-1000': CompanyProfile.CompanySize.LARGE,
            '1001-5000': CompanyProfile.CompanySize.XL,
            '5001-10000': CompanyProfile.CompanySize.XXL,
            '10000+': CompanyProfile.CompanySize.ENTERPRISE,
        },
    )

    return normalized


def _apply_company_profile_updates(company_profile: CompanyProfile, payload: dict[str, Any]) -> list[str]:
    updated_fields: list[str] = []
    for field in PROFILE_FIELDS:
        incoming = payload.get(field)
        current = getattr(company_profile, field)
        if _should_update_field(field, current, incoming):
            setattr(company_profile, field, incoming)
            updated_fields.append(field)
    return updated_fields


def _should_update_field(field: str, current: Any, incoming: Any) -> bool:
    if field in INTEGER_FIELDS:
        return current is None and incoming is not None

    current_value = _clean_string(current)
    incoming_value = _clean_string(incoming)
    if not incoming_value:
        return False
    if not current_value:
        return True
    if current_value == TBD_VALUE and incoming_value != TBD_VALUE:
        return True
    if field == 'website' and current_value == TBD_VALUE and incoming_value:
        return True
    return False


def _is_company_profile_incomplete(company_profile: CompanyProfile) -> bool:
    for field in (
        'legal_name',
        'display_name',
        'description',
        'address_line_1',
        'city',
        'state',
        'postal_code',
        'country',
        'headquarters',
        'contact_email',
        'contact_phone',
    ):
        if not _clean_string(getattr(company_profile, field, '')) or _clean_string(getattr(company_profile, field, '')) == TBD_VALUE:
            return True
    if not _clean_string(company_profile.website):
        return True
    return False


def _clean_string(value: Any) -> str:
    if value is None:
        return ''
    text = str(value).strip()
    if text.lower() in {'', 'null', 'none', 'n/a', 'unknown'}:
        return ''
    return text


def _clean_integer(value: Any) -> int | None:
    if value in (None, ''):
        return None
    text = _clean_string(value)
    if not text:
        return None
    try:
        number = int(float(text))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _normalize_choice(value: Any, valid_values: list[str], fallback: str, aliases: dict[str, str] | None = None) -> str:
    normalized = _clean_string(value).lower().replace('-', '_')
    normalized = '_'.join(normalized.split())
    if normalized in valid_values:
        return normalized
    aliases = aliases or {}
    return aliases.get(normalized.replace('_', ' '), fallback)


def _extract_output_text(payload: dict[str, Any]) -> str:
    output_text = str(payload.get('output_text') or '').strip()
    if output_text:
        return output_text
    for item in payload.get('output') or []:
        for content in item.get('content') or []:
            text = str(content.get('text') or '').strip()
            if text:
                return text
    return ''


def _response_schema() -> dict[str, Any]:
    return {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'legal_name': {'type': ['string', 'null']},
            'display_name': {'type': ['string', 'null']},
            'description': {'type': ['string', 'null']},
            'industry': {'type': ['string', 'null']},
            'sub_industry': {'type': ['string', 'null']},
            'company_type': {'type': ['string', 'null']},
            'company_stage': {'type': ['string', 'null']},
            'company_size': {'type': ['string', 'null']},
            'employee_count': {'type': ['integer', 'null']},
            'founded_year': {'type': ['integer', 'null']},
            'website': {'type': ['string', 'null']},
            'careers_page': {'type': ['string', 'null']},
            'linkedin_url': {'type': ['string', 'null']},
            'twitter_url': {'type': ['string', 'null']},
            'logo_url': {'type': ['string', 'null']},
            'contact_email': {'type': ['string', 'null']},
            'contact_phone': {'type': ['string', 'null']},
            'alternate_phone': {'type': ['string', 'null']},
            'address_line_1': {'type': ['string', 'null']},
            'address_line_2': {'type': ['string', 'null']},
            'landmark': {'type': ['string', 'null']},
            'city': {'type': ['string', 'null']},
            'state': {'type': ['string', 'null']},
            'postal_code': {'type': ['string', 'null']},
            'country': {'type': ['string', 'null']},
            'headquarters': {'type': ['string', 'null']},
            'registration_number': {'type': ['string', 'null']},
            'tax_identifier': {'type': ['string', 'null']},
            'currency_code': {'type': ['string', 'null']},
            'timezone': {'type': ['string', 'null']},
        },
        'required': [
            'legal_name',
            'display_name',
            'description',
            'industry',
            'sub_industry',
            'company_type',
            'company_stage',
            'company_size',
            'employee_count',
            'founded_year',
            'website',
            'careers_page',
            'linkedin_url',
            'twitter_url',
            'logo_url',
            'contact_email',
            'contact_phone',
            'alternate_phone',
            'address_line_1',
            'address_line_2',
            'landmark',
            'city',
            'state',
            'postal_code',
            'country',
            'headquarters',
            'registration_number',
            'tax_identifier',
            'currency_code',
            'timezone',
        ],
    }
