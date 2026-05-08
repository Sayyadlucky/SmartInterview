import { Component } from '@angular/core';

import { OtpConsole } from '../otp-console/otp-console';
import { NotificationTrigger } from '../notification-trigger/notification-trigger';
import { NotificationStatus } from '../notification-status/notification-status';

@Component({
  selector: 'app-notification-console',
  standalone: true,
  imports: [OtpConsole, NotificationTrigger, NotificationStatus],
  templateUrl: './notification-console.html',
  styleUrl: './notification-console.scss',
})
export class NotificationConsole {}
