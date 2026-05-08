from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from smartInterviewApp.services.ai_talent_pool.indexer import bulk_rebuild_candidate_search_index


class Command(BaseCommand):
    help = 'Rebuilds the persistent AI Talent Pool candidate search index.'

    def add_arguments(self, parser):
        parser.add_argument('--candidate-id', action='append', dest='candidate_ids', type=int, help='Reindex one or more candidate IDs.')
        parser.add_argument('--stale-only', action='store_true', help='Only rebuild profiles that have changed.')

    def handle(self, *args, **options):
        candidate_ids = options.get('candidate_ids') or None
        stale_only = bool(options.get('stale_only'))
        try:
            results = bulk_rebuild_candidate_search_index(candidate_ids=candidate_ids, stale_only=stale_only)
        except Exception as exc:
            raise CommandError(f'Candidate search index rebuild failed: {exc}') from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Candidate search index rebuild complete: processed={results['processed']} updated={results['updated']} skipped={results['skipped']}"
            )
        )
