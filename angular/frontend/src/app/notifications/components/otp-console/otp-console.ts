import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NotificationApiService } from '../../services/notification-api.service';
import { DigitsOnlyDirective } from '../../../core/digits-only.directive';

@Component({
  selector: 'app-otp-console',
  standalone: true,
  imports: [CommonModule, FormsModule, DigitsOnlyDirective],
  templateUrl: './otp-console.html',
  styleUrl: './otp-console.scss',
})
export class OtpConsole {
  phone = '';
  purpose = 'login';
  otp = '';
  result = '';
  loading = false;

  constructor(private notificationApi: NotificationApiService) {}

  requestOtp(): void {
    this.loading = true;
    this.notificationApi.requestOtp({ phone: this.phone, purpose: this.purpose }).subscribe({
      next: (resp) => {
        this.result = resp.success ? 'OTP requested.' : resp.error || 'Request failed';
        this.loading = false;
      },
      error: () => {
        this.result = 'Request failed';
        this.loading = false;
      },
    });
  }

  verifyOtp(): void {
    this.loading = true;
    this.notificationApi.verifyOtp({ phone: this.phone, purpose: this.purpose, otp: this.otp }).subscribe({
      next: (resp) => {
        this.result = resp.success ? 'OTP verified.' : resp.error || 'Verification failed';
        this.loading = false;
      },
      error: () => {
        this.result = 'Verification failed';
        this.loading = false;
      },
    });
  }

  resendOtp(): void {
    this.loading = true;
    this.notificationApi.resendOtp({ phone: this.phone, purpose: this.purpose }).subscribe({
      next: (resp) => {
        this.result = resp.success ? 'OTP resent.' : resp.error || 'Resend failed';
        this.loading = false;
      },
      error: () => {
        this.result = 'Resend failed';
        this.loading = false;
      },
    });
  }
}
