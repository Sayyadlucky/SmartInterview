from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings


logger = logging.getLogger(__name__)


class CloudTasksConfigurationError(RuntimeError):
    pass


class CloudTasksScheduler:
    def is_configured(self) -> bool:
        return all([
            settings.GCP_PROJECT_ID,
            settings.GCP_LOCATION,
            settings.CLOUD_TASKS_QUEUE,
            settings.CLOUD_RUN_BASE_URL,
            settings.CLOUD_TASKS_SHARED_SECRET,
        ])

    def _get_client(self):
        try:
            from google.cloud import tasks_v2
            from google.protobuf import timestamp_pb2
        except ImportError as exc:
            raise CloudTasksConfigurationError('google-cloud-tasks dependency is not installed') from exc
        return tasks_v2.CloudTasksClient(), tasks_v2, timestamp_pb2

    def build_task_id(self, namespace: str, *parts: object) -> str:
        raw = ':'.join(str(part) for part in parts)
        digest = hashlib.sha1(raw.encode('utf-8')).hexdigest()[:24]
        return f'{namespace}-{digest}'

    def create_http_task(self, *, task_id: str, relative_path: str, payload: dict, schedule_for: datetime) -> str:
        if not self.is_configured():
            raise CloudTasksConfigurationError('Cloud Tasks configuration is incomplete')

        client, tasks_v2, timestamp_pb2 = self._get_client()
        queue_path = client.queue_path(settings.GCP_PROJECT_ID, settings.GCP_LOCATION, settings.CLOUD_TASKS_QUEUE)
        schedule_utc = schedule_for.astimezone(dt_timezone.utc)
        schedule_ts = timestamp_pb2.Timestamp()
        schedule_ts.FromDatetime(schedule_utc)
        url = f"{settings.CLOUD_RUN_BASE_URL.rstrip('/')}/{relative_path.lstrip('/')}"
        task_name = client.task_path(settings.GCP_PROJECT_ID, settings.GCP_LOCATION, settings.CLOUD_TASKS_QUEUE, task_id)
        task = {
            'name': task_name,
            'schedule_time': schedule_ts,
            'http_request': {
                'http_method': tasks_v2.HttpMethod.POST,
                'url': url,
                'headers': {
                    'Content-Type': 'application/json',
                    'X-Cloud-Tasks-Secret': settings.CLOUD_TASKS_SHARED_SECRET,
                },
                'body': json.dumps(payload).encode('utf-8'),
            },
        }
        created = client.create_task(parent=queue_path, task=task)
        return created.name

    def delete_task(self, task_name: str) -> bool:
        if not self.is_configured() or not task_name:
            return False

        try:
            client, _, _ = self._get_client()
            client.delete_task(name=task_name)
            return True
        except Exception as exc:
            logger.info('Cloud Task delete skipped', extra={'task_name': task_name, 'error': str(exc)})
            return False
