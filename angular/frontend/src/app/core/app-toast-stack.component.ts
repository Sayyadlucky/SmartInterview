import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { AppToastItem, AppToastService } from './app-toast.service';

@Component({
  selector: 'app-toast-stack',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="app-toast-stack" aria-live="polite" aria-atomic="true">
      <article
        *ngFor="let toast of toastService.toasts(); trackBy: trackToast"
        class="app-toast"
        [class.app-toast--success]="toast.tone === 'success'"
        [class.app-toast--error]="toast.tone === 'error'"
        [class.app-toast--info]="toast.tone === 'info'"
        [class.app-toast--warning]="toast.tone === 'warning'"
      >
        <div class="app-toast__icon-orb" aria-hidden="true">
          <i [class]="iconClass(toast)"></i>
        </div>
        <div class="app-toast__copy">
          <strong>{{ toast.title }}</strong>
          <span>{{ toast.message }}</span>
        </div>
        <time class="app-toast__time" [attr.datetime]="toast.createdAt | date:'yyyy-MM-ddTHH:mm:ss'">
          {{ timeLabel(toast) }}
        </time>
        <button
          type="button"
          class="app-toast__dismiss"
          (click)="toastService.dismiss(toast.id)"
          [attr.aria-label]="'Dismiss notification: ' + toast.title"
        >
          <i class="ph ph-x"></i>
        </button>
      </article>
    </div>
  `,
})
export class AppToastStackComponent {
  readonly toastService = inject(AppToastService);

  trackToast(_: number, toast: AppToastItem): number {
    return toast.id;
  }

  iconClass(toast: AppToastItem): string {
    if (toast.tone === 'success') {
      return 'ph ph-check-circle';
    }
    if (toast.tone === 'error') {
      return 'ph ph-x-circle';
    }
    if (toast.tone === 'warning') {
      return 'ph ph-warning';
    }
    return 'ph ph-info';
  }

  timeLabel(toast: AppToastItem): string {
    const elapsedMs = Date.now() - toast.createdAt;
    if (elapsedMs < 60_000) {
      return 'Just now';
    }
    const elapsedMinutes = Math.max(1, Math.floor(elapsedMs / 60_000));
    return `${elapsedMinutes}m ago`;
  }
}
