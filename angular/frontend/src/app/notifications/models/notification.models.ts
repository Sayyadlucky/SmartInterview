export interface ApiResponse<T> {
  success: boolean;
  error: string | null;
  data: T;
}

export interface OtpPayload {
  phone: string;
  purpose: string;
}

export interface OtpVerifyPayload extends OtpPayload {
  otp: string;
}

export interface NotificationSendPayload {
  event_type: string;
  severity: 'low' | 'medium' | 'critical';
  user_id?: number;
  payload: Record<string, unknown>;
  idempotency_key?: string;
}

export interface NotificationAttempt {
  id: number;
  channel: string;
  provider: string;
  status: string;
  provider_message_id: string;
  attempted_at: string;
  updated_at: string;
}

export interface NotificationRecord {
  id: number;
  event_type: string;
  severity: string;
  status: string;
  final_channel: string;
  payload: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  attempts: NotificationAttempt[];
}
