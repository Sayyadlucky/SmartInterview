import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { NotificationRecord } from '../../models/notification.models';
import { NotificationApiService } from '../../services/notification-api.service';

@Component({
  selector: 'app-notification-status',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './notification-status.html',
  styleUrl: './notification-status.scss',
})
export class NotificationStatus {
  notificationId = '';
  loading = false;
  error = '';
  notification: NotificationRecord | null = null;

  constructor(private notificationApi: NotificationApiService) {}

  fetch(): void {
    const id = Number(this.notificationId);
    if (!id) {
      this.error = 'Enter a valid notification id';
      return;
    }

    this.loading = true;
    this.error = '';
    this.notification = null;
    this.notificationApi.getNotification(id).subscribe({
      next: (resp) => {
        this.notification = resp.data;
        this.loading = false;
      },
      error: () => {
        this.error = 'Failed to fetch notification';
        this.loading = false;
      },
    });
  }
}
