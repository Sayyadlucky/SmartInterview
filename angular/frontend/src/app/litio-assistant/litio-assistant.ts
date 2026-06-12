import { AfterViewChecked, Component, ElementRef, HostListener, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { catchError, finalize, of, timeout } from 'rxjs';
import { getApiBaseUrl } from '../core/api-base';

interface LitioAssistantMessage {
  id: number | null;
  role: 'user' | 'litio';
  text: string;
  pendingFeedback?: boolean;
  feedback?: 'helpful' | 'not_helpful';
}

interface LitioChatResponse {
  success: boolean;
  data?: {
    conversation_id: number;
    assistant_message_id: number;
    answer: string;
    suggestions?: string[];
  };
  error?: string | null;
}

interface LitioSuggestionsResponse {
  success: boolean;
  data?: {
    suggestions?: string[];
  };
}

@Component({
  selector: 'app-litio-assistant',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './litio-assistant.html',
})
export class LitioAssistant implements AfterViewChecked {
  @ViewChild('conversationLog') private conversationLog?: ElementRef<HTMLElement>;
  isOpen = false;
  isSending = false;
  inputText = '';
  conversationId: number | null = null;
  errorMessage = '';
  suggestions: string[] = [
    'How do I post a job?',
    'How do I assign a candidate to a role?',
    'How is role fit score explained?',
  ];
  messages: LitioAssistantMessage[] = [
    {
      id: null,
      role: 'litio',
      text: 'Ask me about Litio workflows, jobs, candidate assignment, and role matching.',
    },
  ];
  private shouldScroll = false;
  private readonly apiTimeoutMs = 12000;

  constructor(private http: HttpClient) {
    this.fetchSuggestions();
  }

  ngAfterViewChecked(): void {
    if (!this.shouldScroll) {
      return;
    }
    this.shouldScroll = false;
    const element = this.conversationLog?.nativeElement;
    if (element) {
      element.scrollTop = element.scrollHeight;
    }
  }

  @HostListener('document:keydown.escape')
  handleEscape(): void {
    if (this.isOpen) {
      this.close();
    }
  }

  open(): void {
    this.isOpen = true;
    this.errorMessage = '';
    this.shouldScroll = true;
  }

  close(): void {
    this.isOpen = false;
  }

  toggle(): void {
    if (this.isOpen) {
      this.close();
      return;
    }
    this.open();
  }

  useSuggestion(suggestion: string): void {
    this.inputText = suggestion;
    this.sendMessage();
  }

  sendMessage(): void {
    const message = this.inputText.trim();
    if (!message || this.isSending) {
      return;
    }
    this.errorMessage = '';
    this.inputText = '';
    this.messages.push({ id: null, role: 'user', text: message });
    this.isSending = true;
    this.shouldScroll = true;

    this.http.post<LitioChatResponse>(
      `${getApiBaseUrl()}/api/litio-assistant/chat/`,
      {
        message,
        conversation_id: this.conversationId,
      },
      { headers: this.buildHeaders() },
    )
      .pipe(
        timeout(this.apiTimeoutMs),
        catchError(() => {
          this.errorMessage = 'Litio could not answer right now. Please try again.';
          return of(null);
        }),
        finalize(() => {
          this.isSending = false;
          this.shouldScroll = true;
        }),
      )
      .subscribe((response) => {
        if (!response?.success || !response.data) {
          this.errorMessage = response?.error || this.errorMessage || 'Litio could not answer right now.';
          return;
        }
        this.conversationId = response.data.conversation_id;
        if (response.data.suggestions?.length) {
          this.suggestions = response.data.suggestions;
        }
        this.messages.push({
          id: response.data.assistant_message_id,
          role: 'litio',
          text: response.data.answer,
          pendingFeedback: true,
        });
      });
  }

  sendFeedback(message: LitioAssistantMessage, rating: 'helpful' | 'not_helpful'): void {
    if (!this.conversationId || !message.id || message.feedback) {
      return;
    }
    message.pendingFeedback = false;
    this.http.post(
      `${getApiBaseUrl()}/api/litio-assistant/feedback/`,
      {
        conversation_id: this.conversationId,
        message_id: message.id,
        rating,
      },
      { headers: this.buildHeaders() },
    )
      .pipe(
        timeout(this.apiTimeoutMs),
        catchError(() => {
          message.pendingFeedback = true;
          return of(null);
        }),
      )
      .subscribe((response) => {
        if (response) {
          message.feedback = rating;
        }
      });
  }

  private fetchSuggestions(): void {
    this.http.get<LitioSuggestionsResponse>(`${getApiBaseUrl()}/api/litio-assistant/suggestions/`)
      .pipe(catchError(() => of(null)))
      .subscribe((response) => {
        const suggestions = response?.data?.suggestions || [];
        if (suggestions.length) {
          this.suggestions = suggestions;
        }
      });
  }

  private buildHeaders(): HttpHeaders {
    const csrfToken = this.getCookie('csrftoken');
    return csrfToken ? new HttpHeaders({ 'X-CSRFToken': csrfToken }) : new HttpHeaders();
  }

  private getCookie(name: string): string {
    const cookie = document.cookie
      .split(';')
      .map((item) => item.trim())
      .find((item) => item.startsWith(`${name}=`));
    return cookie ? decodeURIComponent(cookie.slice(name.length + 1)) : '';
  }
}

