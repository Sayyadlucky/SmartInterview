import { AfterViewChecked, Component, ElementRef, HostListener, Input, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { catchError, of, timeout } from 'rxjs';
import { getApiBaseUrl } from '../core/api-base';

interface LitioAssistantMessage {
  id: number | null;
  role: 'user' | 'litio';
  text: string;
  tone?: 'normal' | 'error';
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
  @ViewChild('composerInput') private composerInput?: ElementRef<HTMLTextAreaElement>;
  @Input() userDisplayName = '';
  @Input() userEmail = '';
  @Input() explicitUserInitials = '';
  isOpen = false;
  isSubmitting = false;
  isAssistantTyping = false;
  showSuggestions = true;
  inputText = '';
  conversationId: number | null = null;
  suggestions: string[] = [
    'How do I post a job?',
    'How do I assign a candidate to a role?',
    'How is role fit score explained?',
  ];
  messages: LitioAssistantMessage[] = this.buildInitialMessages();
  private shouldScroll = false;
  private readonly apiTimeoutMs = 12000;
  private readonly minTypingMs = 900;
  private readonly textareaMinHeightPx = 46;
  private readonly textareaMaxHeightPx = 124;
  private typingStartedAt = 0;
  private chatSessionVersion = 0;
  private readonly ignoredNameParts = new Set(['mr', 'mrs', 'ms', 'miss', 'dr', 'prof']);

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

  restartChat(): void {
    this.chatSessionVersion += 1;
    this.messages = this.buildInitialMessages();
    this.inputText = '';
    this.conversationId = null;
    this.isSubmitting = false;
    this.isAssistantTyping = false;
    this.showSuggestions = true;
    this.typingStartedAt = 0;
    this.resetComposerHeight();
    this.scheduleScrollToBottom();
  }

  get isSending(): boolean {
    return this.isSubmitting;
  }

  get userInitials(): string {
    return this.getUserInitials();
  }

  getUserInitials(): string {
    const nameInitials = this.initialsFromName(
      this.userDisplayName || document.body?.dataset?.['userName'] || '',
    );
    if (nameInitials) {
      return nameInitials;
    }

    const emailInitials = this.initialsFromEmail(
      this.userEmail || document.body?.dataset?.['userEmail'] || '',
    );
    if (emailInitials) {
      return emailInitials;
    }

    const explicit = this.normalizeInitials(this.explicitUserInitials || document.body?.dataset?.['userInitials'] || '');
    return explicit || 'U';
  }

  sendMessage(): void {
    const message = this.inputText.trim();
    if (!message || this.isSubmitting) {
      return;
    }
    this.inputText = '';
    this.showSuggestions = false;
    this.messages.push({ id: null, role: 'user', text: message });
    this.isSubmitting = true;
    this.isAssistantTyping = true;
    this.typingStartedAt = Date.now();
    this.resetComposerHeight();
    this.scheduleScrollToBottom();
    const requestSessionVersion = this.chatSessionVersion;

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
          return of({
            success: false,
            error: 'Litio could not answer right now. Please try again.',
          } as LitioChatResponse);
        }),
      )
      .subscribe((response) => {
        void this.finishChatResponse(response, this.typingStartedAt, requestSessionVersion);
      });
  }

  handleComposerKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Enter') {
      return;
    }
    if (event.shiftKey) {
      window.setTimeout(() => this.autoResizeComposer(), 0);
      return;
    }
    event.preventDefault();
    this.sendMessage();
  }

  autoResizeComposer(textarea: HTMLTextAreaElement | null = this.composerInput?.nativeElement || null): void {
    if (!textarea) {
      return;
    }
    textarea.style.height = 'auto';
    const nextHeight = Math.min(textarea.scrollHeight, this.textareaMaxHeightPx);
    textarea.style.height = `${Math.max(this.textareaMinHeightPx, nextHeight)}px`;
    textarea.style.overflowY = textarea.scrollHeight > this.textareaMaxHeightPx ? 'auto' : 'hidden';
  }

  private async finishChatResponse(
    response: LitioChatResponse | null,
    typingStartedAt: number,
    requestSessionVersion: number,
  ): Promise<void> {
    await this.waitForMinimumTypingTime(typingStartedAt);
    if (requestSessionVersion !== this.chatSessionVersion) {
      return;
    }
    this.isAssistantTyping = false;
    if (!response?.success || !response.data) {
      this.appendErrorMessage(response?.error || 'Litio could not answer right now. Please try again.');
    } else {
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
    }
    this.isSubmitting = false;
    this.scheduleScrollToBottom();
  }

  private waitForMinimumTypingTime(startedAt: number): Promise<void> {
    const elapsedMs = Date.now() - startedAt;
    const remainingMs = Math.max(0, this.minTypingMs - elapsedMs);
    return new Promise((resolve) => window.setTimeout(resolve, remainingMs));
  }

  private scheduleScrollToBottom(): void {
    this.shouldScroll = true;
    const scroll = () => {
      const element = this.conversationLog?.nativeElement;
      if (element) {
        element.scrollTop = element.scrollHeight;
      }
    };
    if (typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(scroll);
      return;
    }
    window.setTimeout(scroll, 0);
  }

  private appendErrorMessage(text: string): void {
    this.messages.push({
      id: null,
      role: 'litio',
      text,
      tone: 'error',
    });
  }

  private resetComposerHeight(): void {
    window.setTimeout(() => {
      const textarea = this.composerInput?.nativeElement;
      if (!textarea) {
        return;
      }
      textarea.style.height = `${this.textareaMinHeightPx}px`;
      textarea.style.overflowY = 'hidden';
    }, 0);
  }

  private buildInitialMessages(): LitioAssistantMessage[] {
    return [
      {
        id: null,
        role: 'litio',
        text: 'Ask me about Litio workflows, jobs, candidate assignment, and role matching.',
      },
    ];
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

  private initialsFromName(value: string): string {
    const parts = this.cleanIdentityText(value)
      .split(/\s+/)
      .map((part) => part.replace(/[^a-zA-Z0-9]/g, ''))
      .filter((part) => part && !this.ignoredNameParts.has(part.toLowerCase()));
    return parts
      .slice(0, 2)
      .map((part) => part.charAt(0))
      .join('')
      .toUpperCase();
  }

  private initialsFromEmail(value: string): string {
    const localPart = (value || '').trim().split('@')[0] || '';
    if (!localPart) {
      return '';
    }
    const parts = localPart
      .split(/[^a-zA-Z0-9]+/)
      .filter(Boolean);
    if (parts.length > 1) {
      return parts
        .slice(0, 2)
        .map((part) => part.charAt(0))
        .join('')
        .toUpperCase();
    }
    return localPart.replace(/[^a-zA-Z]/g, '').slice(0, 2).toUpperCase();
  }

  private normalizeInitials(value: string): string {
    return (value || '').replace(/[^a-zA-Z0-9]/g, '').slice(0, 2).toUpperCase();
  }

  private cleanIdentityText(value: string): string {
    return (value || '').trim().replace(/\s+/g, ' ');
  }
}
