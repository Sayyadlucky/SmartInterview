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
        [class.is-success]="toast.tone === 'success'"
        [class.is-error]="toast.tone === 'error'"
        [class.is-info]="toast.tone === 'info'"
      >
        <div class="app-toast__icon" aria-hidden="true">
          <i [class]="iconClass(toast)"></i>
        </div>
        <div class="app-toast__copy">
          <strong>{{ toast.title }}</strong>
          <span>{{ toast.message }}</span>
        </div>
        <button
          type="button"
          class="app-toast__dismiss"
          (click)="toastService.dismiss(toast.id)"
          [attr.aria-label]="'Dismiss ' + toast.title"
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
      return 'ph ph-warning-circle';
    }
    return 'ph ph-info';
  }
}
