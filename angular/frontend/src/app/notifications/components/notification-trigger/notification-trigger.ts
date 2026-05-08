import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NotificationApiService } from '../../services/notification-api.service';
import { DigitsOnlyDirective } from '../../../core/digits-only.directive';

@Component({
  selector: 'app-notification-trigger',
  standalone: true,
  imports: [CommonModule, FormsModule, DigitsOnlyDirective],
  templateUrl: './notification-trigger.html',
  styleUrl: './notification-trigger.scss',
})
export class NotificationTrigger {
  eventType = 'interview_reminder';
  severity: 'low' | 'medium' | 'critical' = 'low';
  to = '';
  templateName = 'default_notification';
  languageCode = 'en';
  smsMessage = 'This is a fallback SMS';
  result = '';
  loading = false;

  constructor(private notificationApi: NotificationApiService) {}

  submit(): void {
    this.loading = true;
    const payload = {
      event_type: this.eventType,
      severity: this.severity,
      payload: {
        to: this.to,
        template_name: this.templateName,
        language_code: this.languageCode,
        sms_message: this.smsMessage,
        message: this.smsMessage,
      },
    };

    this.notificationApi.sendNotification(payload).subscribe({
      next: (resp) => {
        this.result = resp.success ? `Notification queued: #${resp.data.id}` : resp.error || 'Failed';
        this.loading = false;
      },
      error: () => {
        this.result = 'Failed to send notification';
        this.loading = false;
      },
    });
  }
}
