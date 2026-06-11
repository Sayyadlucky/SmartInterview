import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { getApiBaseUrl } from '../core/api-base';

export interface LitioAssistantChatRequest {
  message: string;
  conversation_id?: number | null;
  page_context?: string;
  page_url?: string;
}

export interface LitioAssistantChatData {
  conversation_id: number;
  message_id: number;
  answer: string;
  intent: string;
  category: string;
  suggestions: string[];
  show_feedback: boolean;
}

export interface LitioAssistantFeedbackRequest {
  conversation_id: number;
  rating: 'yes' | 'no' | 'needs_help';
  comment?: string;
  message_id?: number | null;
  page_context?: string;
  page_url?: string;
}

export interface LitioApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
}

@Injectable({ providedIn: 'root' })
export class LitioAssistantService {
  private readonly apiBaseUrl = getApiBaseUrl();

  constructor(private http: HttpClient) {}

  chat(payload: LitioAssistantChatRequest): Observable<LitioApiResponse<LitioAssistantChatData>> {
    return this.http.post<LitioApiResponse<LitioAssistantChatData>>(
      `${this.apiBaseUrl}/api/litio-assistant/chat/`,
      payload,
      { headers: this.headers() },
    );
  }

  feedback(payload: LitioAssistantFeedbackRequest): Observable<LitioApiResponse<{ success: boolean; feedback_id: number }>> {
    return this.http.post<LitioApiResponse<{ success: boolean; feedback_id: number }>>(
      `${this.apiBaseUrl}/api/litio-assistant/feedback/`,
      payload,
      { headers: this.headers() },
    );
  }

  private headers(): HttpHeaders {
    const csrfToken = this.getCookie('csrftoken');
    let headers = new HttpHeaders({ 'Content-Type': 'application/json' });
    if (csrfToken) {
      headers = headers.set('X-CSRFToken', csrfToken);
    }
    return headers;
  }

  private getCookie(name: string): string {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
      return decodeURIComponent(parts.pop()?.split(';').shift() || '');
    }
    return '';
  }
}
