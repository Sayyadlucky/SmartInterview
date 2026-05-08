import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { getApiBaseUrl } from '../../core/api-base';
import {
  ApiResponse,
  NotificationRecord,
  NotificationSendPayload,
  OtpPayload,
  OtpVerifyPayload,
} from '../models/notification.models';

@Injectable({ providedIn: 'root' })
export class NotificationApiService {
  private readonly baseUrl = `${getApiBaseUrl()}/api`;

  constructor(private http: HttpClient) {}

  requestOtp(payload: OtpPayload): Observable<ApiResponse<Record<string, unknown>>> {
    return this.http.post<ApiResponse<Record<string, unknown>>>(`${this.baseUrl}/auth/request-otp/`, payload);
  }

  verifyOtp(payload: OtpVerifyPayload): Observable<ApiResponse<Record<string, unknown>>> {
    return this.http.post<ApiResponse<Record<string, unknown>>>(`${this.baseUrl}/auth/verify-otp/`, payload);
  }

  resendOtp(payload: OtpPayload): Observable<ApiResponse<Record<string, unknown>>> {
    return this.http.post<ApiResponse<Record<string, unknown>>>(`${this.baseUrl}/auth/resend-otp/`, payload);
  }

  sendNotification(payload: NotificationSendPayload): Observable<ApiResponse<NotificationRecord>> {
    return this.http.post<ApiResponse<NotificationRecord>>(`${this.baseUrl}/notifications/send/`, payload);
  }

  getNotification(id: number): Observable<ApiResponse<NotificationRecord>> {
    return this.http.get<ApiResponse<NotificationRecord>>(`${this.baseUrl}/notifications/${id}/`);
  }
}
