from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count
from datetime import timedelta

from smartInterviewApp.models import LitioAssistantKnowledgeGap


class Command(BaseCommand):
    help = 'Print a lightweight summary of Litio Assistant knowledge gaps'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7, help='Window in days to consider for recent gaps')
        parser.add_argument('--limit', type=int, default=10, help='Limit for top lists')

    def handle(self, *args, **options):
        days = options.get('days', 7) or 7
        limit = options.get('limit', 10) or 10
        now = timezone.now()
        window_start = now - timedelta(days=days)

        total = LitioAssistantKnowledgeGap.objects.count()
        open_count = LitioAssistantKnowledgeGap.objects.filter(status=LitioAssistantKnowledgeGap.Status.OPEN).count()
        reviewed_count = LitioAssistantKnowledgeGap.objects.filter(status=LitioAssistantKnowledgeGap.Status.REVIEWED).count()
        resolved_count = LitioAssistantKnowledgeGap.objects.filter(status=LitioAssistantKnowledgeGap.Status.RESOLVED).count()
        ignored_count = LitioAssistantKnowledgeGap.objects.filter(status=LitioAssistantKnowledgeGap.Status.IGNORED).count()
        recent_count = LitioAssistantKnowledgeGap.objects.filter(created_at__gte=window_start).count()

        self.stdout.write('Litio Assistant Knowledge Gap Summary')
        self.stdout.write('-----------------------------------')
        self.stdout.write(f'Total gaps: {total}')
        self.stdout.write(f'Open: {open_count} | Reviewed: {reviewed_count} | Resolved: {resolved_count} | Ignored: {ignored_count}')
        self.stdout.write(f'Created in last {days} day(s): {recent_count}')
        self.stdout.write('')

        # Top normalized questions
        top_qs = (
            LitioAssistantKnowledgeGap.objects
            .values('normalized_question')
            .annotate(count=Count('id'))
            .order_by('-count')[:limit]
        )
        self.stdout.write(f'Top {limit} normalized questions (safe):')
        if top_qs:
            for row in top_qs:
                q = row['normalized_question'] or '<empty>'
                self.stdout.write(f'  {row["count"]:4d}  {q[:200]}')
        else:
            self.stdout.write('  (none)')
        self.stdout.write('')

        # Top fallback reasons
        top_reasons = (
            LitioAssistantKnowledgeGap.objects
            .values('fallback_reason')
            .annotate(count=Count('id'))
            .order_by('-count')[:limit]
        )
        self.stdout.write('Top fallback reasons:')
        if top_reasons:
            for row in top_reasons:
                reason = row['fallback_reason'] or '<empty>'
                self.stdout.write(f'  {row["count"]:4d}  {reason}')
        else:
            self.stdout.write('  (none)')
        self.stdout.write('')

        # Top context pages/sections aggregated safely
        # context is a jsonfield; extract page/section keys if present
        page_counts = {}
        section_counts = {}
        for gap in LitioAssistantKnowledgeGap.objects.filter(context__isnull=False).exclude(context={})[:1000]:
            ctx = gap.context or {}
            if not isinstance(ctx, dict):
                continue
            page = ctx.get('page') or ctx.get('openModal')
            section = ctx.get('section') or ctx.get('activeTab')
            if page:
                page_counts[page] = page_counts.get(page, 0) + 1
            if section:
                section_counts[section] = section_counts.get(section, 0) + 1
        self.stdout.write(f'Top {limit} context pages (best-effort):')
        if page_counts:
            for page, cnt in sorted(page_counts.items(), key=lambda i: -i[1])[:limit]:
                self.stdout.write(f'  {cnt:4d}  {page[:200]}')
        else:
            self.stdout.write('  (none)')
        self.stdout.write('')

        self.stdout.write(f'Top {limit} context sections (best-effort):')
        if section_counts:
            for section, cnt in sorted(section_counts.items(), key=lambda i: -i[1])[:limit]:
                self.stdout.write(f'  {cnt:4d}  {section[:200]}')
        else:
            self.stdout.write('  (none)')

        self.stdout.write('\nDone.')
