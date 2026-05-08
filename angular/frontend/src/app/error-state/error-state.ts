import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

type ErrorVariant = 'not-found' | 'technical';

interface ErrorStateContent {
  code: string;
  statusLabel: string;
  title: string;
  description: string;
  iconClass: string;
  accentLabel: string;
  tips: string[];
}

@Component({
  selector: 'app-error-state',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './error-state.html',
  styleUrl: './error-state.scss',
})
export class ErrorState {
  private readonly route = inject(ActivatedRoute);

  private readonly contentByVariant: Record<ErrorVariant, ErrorStateContent> = {
    'not-found': {
      code: '404',
      statusLabel: 'Page not found',
      title: 'This workspace page does not exist.',
      description: 'The link may be outdated, incomplete, or pointing to a route that is no longer available in the dashboard.',
      iconClass: 'ph-magnifying-glass-minus',
      accentLabel: 'Route mismatch',
      tips: [
        'Return to the dashboard and navigate from a known entry point.',
        'If you opened a saved bookmark, refresh it after reaching the correct page.',
        'Check whether the route should live under the jobs or dashboard workspace.',
      ],
    },
    technical: {
      code: '500',
      statusLabel: 'Technical issue',
      title: 'We hit a technical issue loading this workspace.',
      description: 'The application is available, but this request could not be completed successfully. Reloading or returning to a stable page usually resolves transient failures.',
      iconClass: 'ph-warning-circle',
      accentLabel: 'Service interruption',
      tips: [
        'Reload the page to retry the failed request.',
        'Return to the dashboard if you need to continue working immediately.',
        'If the issue persists, capture the failing action and route for debugging.',
      ],
    },
  };

  get variant(): ErrorVariant {
    return this.route.snapshot.data['variant'] === 'technical' ? 'technical' : 'not-found';
  }

  get content(): ErrorStateContent {
    return this.contentByVariant[this.variant];
  }

  get isTechnical(): boolean {
    return this.variant === 'technical';
  }

  reloadPage(): void {
    window.location.reload();
  }

  goBack(): void {
    if (window.history.length > 1) {
      window.history.back();
      return;
    }
    window.location.assign('/dashboard/');
  }
}
