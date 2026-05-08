from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone

from smartInterviewApp.services.ai_talent_pool.indexer import CandidateSearchIndexer
from smartInterviewApp.services.cloud_tasks import CloudTasksConfigurationError, CloudTasksScheduler


logger = logging.getLogger(__name__)

cloud_tasks_scheduler = CloudTasksScheduler()


def _cache_key(candidate_id: int) -> str:
    return f'ai-talent-pool:reindex:{candidate_id}'


def _debounce_seconds() -> int:
    return max(5, int(getattr(settings, 'AI_TALENT_POOL_REINDEX_DEBOUNCE_SECONDS', 30)))


def process_candidate_reindex(candidate_id: int) -> dict:
    try:
        candidate = User.objects.select_related('profile').get(id=candidate_id)
    except User.DoesNotExist:
        cache.delete(_cache_key(candidate_id))
        return {
            'ok': True,
            'status': 'skipped',
            'candidate_id': candidate_id,
            'message': 'Candidate no longer exists.',
        }

    try:
        profile = CandidateSearchIndexer().rebuild_candidate(candidate=candidate, force=True)
        logger.info('Candidate search profile background reindex completed', extra={'candidate_id': candidate_id})
        return {
            'ok': True,
            'status': 'processed',
            'candidate_id': candidate_id,
            'search_profile_id': getattr(profile, 'id', None),
        }
    except Exception as exc:
        logger.exception('Candidate search profile background reindex failed candidate_id=%s', candidate_id)
        return {
            'ok': False,
            'status': 'failed',
            'candidate_id': candidate_id,
            'message': str(exc),
        }
    finally:
        cache.delete(_cache_key(candidate_id))


def queue_candidate_reindex(candidate_id: int | None, scheduler: CloudTasksScheduler | None = None) -> dict:
    if not candidate_id:
        return {'queued': False, 'mode': 'noop'}

    scheduler = scheduler or cloud_tasks_scheduler
    cache_key = _cache_key(candidate_id)
    if not cache.add(cache_key, '1', timeout=_debounce_seconds()):
        return {'queued': False, 'mode': 'deduped', 'candidate_id': candidate_id}

    payload = {'candidate_id': int(candidate_id)}
    try:
        task_name = scheduler.create_http_task(
            task_id=scheduler.build_task_id('candidate-search-reindex', candidate_id, timezone.now().isoformat()),
            relative_path='/internal/tasks/rebuild-candidate-search-profile/',
            payload=payload,
            schedule_for=timezone.now(),
        )
        return {
            'queued': True,
            'mode': 'cloud_tasks',
            'candidate_id': candidate_id,
            'task_name': task_name,
        }
    except CloudTasksConfigurationError as exc:
        cache.delete(cache_key)
        logger.warning(
            'Cloud Tasks unavailable for candidate search reindex; skipping background queue instead of blocking request',
            extra={'candidate_id': candidate_id, 'error': str(exc)},
        )
        return {
            'queued': False,
            'mode': 'cloud_tasks_unavailable',
            'candidate_id': candidate_id,
            'message': str(exc),
        }
