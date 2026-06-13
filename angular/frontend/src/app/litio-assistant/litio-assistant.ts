import { AfterViewChecked, Component, ElementRef, HostListener, Input, OnChanges, SimpleChanges, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
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
  actions?: Array<{
    label: string;
    action_type: string;
    route?: string;
    query_params?: Record<string, any> | null;
    entity_type?: string;
    entity_id?: number | string | null;
  }>;
}

export interface LitioAssistantContext {
  page?: string;
  section?: string;
  activeTab?: string;
  openModal?: string;
  vacancyId?: number | string | null;
  vacancyTitle?: string;
  candidateId?: number | string | null;
  candidateName?: string;
  candidateStage?: string;
  evaluationStatus?: string;
}

interface LitioChatResponse {
  success: boolean;
  data?: {
    conversation_id: number;
    assistant_message_id: number;
    answer: string;
    intent_key?: string;
    suggestions?: string[];
    actions?: Array<{ label: string; action_type: string; route?: string; query_params?: Record<string, any> | null; entity_type?: string; entity_id?: number | string | null }>;
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
export class LitioAssistant implements AfterViewChecked, OnChanges {
  @ViewChild('conversationLog') private conversationLog?: ElementRef<HTMLElement>;
  @ViewChild('composerInput') private composerInput?: ElementRef<HTMLTextAreaElement>;
  @Input() userDisplayName = '';
  @Input() userEmail = '';
  @Input() explicitUserInitials = '';
  @Input() context: LitioAssistantContext | null = null;
  isOpen = false;
  isSubmitting = false;
  isAssistantTyping = false;
  showSuggestions = true;
  inputText = '';
  conversationId: number | null = null;
  private initialSuggestions: string[] = [
    'How do I post a job?',
    'How do I assign a candidate to a role?',
    'How is role fit score explained?',
    'How do I map a candidate to a vacancy?',
  ];
  suggestions: string[] = [
    'How do I post a job?',
    'How do I assign a candidate to a role?',
    'How is role fit score explained?',
    'How do I map a candidate to a vacancy?',
  ];
  messages: LitioAssistantMessage[] = this.buildInitialMessages();
  private readonly suggestionPrompts: Record<string, string> = {
    'Assign candidates': 'How do I assign candidates to a vacancy?',
    'Explain matching': 'How is role fit score explained?',
    'Explain role fit score': 'How is role fit score explained?',
    'Explain resume score': 'How is resume score explained?',
    'Explain recommendation': 'Explain the candidate recommendation.',
    'View red flags': 'What are candidate red flags in evaluation?',
    'Schedule interview': 'How do I schedule an interview?',
    'Schedule Litio interview': 'How do I schedule a Litio interview?',
    'Send reminder': 'How do I send a candidate reminder?',
    'Next hiring step': 'What is the next hiring step?',
    'WhatsApp status updates': 'How do WhatsApp status updates work?',
    'SMS reminders': 'How do SMS reminders work?',
    'Candidate notifications': 'How do I notify a candidate?',
  };
  private readonly emptyAnswerFallback = 'Litio could not find a complete answer for that. Try asking about candidate assignment, scores, interviews, reminders, or evaluation guidance.';
  private shouldScroll = false;
  private readonly apiTimeoutMs = 12000;
  private readonly minTypingMs = 900;
  private readonly textareaMinHeightPx = 46;
  private readonly textareaMaxHeightPx = 124;
  private typingStartedAt = 0;
  private chatSessionVersion = 0;
  private readonly ignoredNameParts = new Set(['mr', 'mrs', 'ms', 'miss', 'dr', 'prof']);

  constructor(private http: HttpClient, private router: Router) {
    this.fetchSuggestions();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['context']) {
      this.refreshInitialSuggestions();
    }
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
    this.refreshInitialSuggestions();
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

  useSuggestion(suggestion: string | null | undefined): void {
    const label = (suggestion || '').trim();
    if (!label) {
      return;
    }
    this.sendMessage(this.suggestionPrompts[label] || label);
  }

  restartChat(): void {
    this.chatSessionVersion += 1;
    this.messages = this.buildInitialMessages();
    this.inputText = '';
    this.conversationId = null;
    this.isSubmitting = false;
    this.isAssistantTyping = false;
    this.suggestions = this.buildInitialSuggestionsForContext();
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

  get visibleSuggestions(): string[] {
    return this.showSuggestions ? this.suggestions : [];
  }

  get suggestionGroupLabel(): string {
    if (this.hasOnlyInitialMessage() && this.hasContextualSuggestionSurface()) {
      return 'Suggestions for this view';
    }
    if (this.hasOnlyInitialMessage()) {
      return 'Suggested questions';
    }
    return 'Suggested next questions';
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

  sendMessage(explicitMessage?: string | null): void {
    const rawMessage = explicitMessage !== undefined ? explicitMessage : this.inputText;
    const message = (rawMessage || '').trim();
    if (!message || this.isSubmitting) {
      return;
    }
    this.inputText = '';
    this.showSuggestions = false;
    this.appendMessage('user', message);
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
        ...this.buildContextPayload(),
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
      const answer = (response.data.answer || '').trim() || this.emptyAnswerFallback;
      this.appendMessage('litio', answer, {
        id: response.data.assistant_message_id,
        pendingFeedback: true,
        actions: response.data.actions || [],
      });
      this.suggestions = this.buildFollowUpSuggestions(response.data.intent_key, answer);
      this.showSuggestions = this.suggestions.length > 0;
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
    this.appendMessage('litio', text, { tone: 'error' });
  }

  private appendMessage(
    role: 'user' | 'litio',
    text: string | null | undefined,
    options: Partial<Omit<LitioAssistantMessage, 'role' | 'text'>> = {},
  ): void {
    const normalized = (text || '').trim();
    if (!normalized) {
      return;
    }
    this.messages = [
      ...this.messages,
      {
        id: options.id ?? null,
        role,
        text: normalized,
        tone: options.tone,
        pendingFeedback: options.pendingFeedback,
        feedback: options.feedback,
        actions: (options as any).actions || undefined,
      },
    ];
  }

  handleAction(
    action: { label: string; action_type: string; route?: string; query_params?: Record<string, any> | null; entity_type?: string; entity_id?: number | string | null; } | undefined,
    event?: Event,
  ): void {
    event?.preventDefault();
    event?.stopPropagation();

    if (!action || !action.action_type || !action.label) {
      return;
    }

    // Only support safe read/navigation action types
    const allowed = new Set([
      'navigate',
      'open_candidate',
      'open_vacancy',
      'open_interviews',
      'open_aptitude',
      'open_followups',
      'open_pipeline',
      'open_recruiter_activity',
    ]);
    if (!allowed.has(action.action_type)) {
      return;
    }

    const rawRoute = action.route || '/dashboard';
    // normalize route to array form accepted by router.navigate
    const cleaned = String(rawRoute || '').trim();
    const routeCommands: any[] = cleaned.startsWith('/') ? [cleaned] : ['/' + cleaned];
    const params = action.query_params || {};

    try {
      // Trigger navigation and close the assistant panel so destination is visible.
      // We don't wait on the navigation promise to resolve; user intent is to leave the chat.
      this.router.navigate(routeCommands, { queryParams: params }).catch(() => {});
      this.isOpen = false;
    } catch (e) {
      // swallow navigation errors silently to avoid crashing the UI
      this.isOpen = false;
    }
  }

  isVisibleMessage(message: LitioAssistantMessage): boolean {
    return Boolean((message?.text || '').trim());
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
    const text = 'Ask me about Litio workflows, jobs, candidate assignment, and role matching.';
    return text.trim() ? [{ id: null, role: 'litio', text }] : [];
  }

  private buildContextPayload(): { context?: LitioAssistantContext } {
    const context = this.getSafeContext();
    return context ? { context } : {};
  }

  private getSafeContext(): LitioAssistantContext | null {
    const source = this.context || {};
    const context: LitioAssistantContext = {};
    this.assignSafeText(context, 'page', source.page);
    this.assignSafeText(context, 'section', source.section);
    this.assignSafeText(context, 'activeTab', source.activeTab);
    this.assignSafeText(context, 'openModal', source.openModal);
    this.assignSafeId(context, 'vacancyId', source.vacancyId);
    this.assignSafeText(context, 'vacancyTitle', source.vacancyTitle);
    this.assignSafeId(context, 'candidateId', source.candidateId);
    this.assignSafeText(context, 'candidateName', source.candidateName);
    this.assignSafeText(context, 'candidateStage', source.candidateStage);
    this.assignSafeText(context, 'evaluationStatus', source.evaluationStatus);
    return Object.keys(context).length ? context : null;
  }

  private assignSafeText<T extends keyof LitioAssistantContext>(
    target: LitioAssistantContext,
    key: T,
    value: LitioAssistantContext[T],
  ): void {
    if (typeof value !== 'string') {
      return;
    }
    const trimmed = value.trim().replace(/\s+/g, ' ').slice(0, 120);
    if (trimmed) {
      target[key] = trimmed as LitioAssistantContext[T];
    }
  }

  private assignSafeId<T extends keyof LitioAssistantContext>(
    target: LitioAssistantContext,
    key: T,
    value: LitioAssistantContext[T],
  ): void {
    if (value === null || value === undefined) {
      return;
    }
    if (typeof value !== 'string' && typeof value !== 'number') {
      return;
    }
    const normalized = String(value).trim().slice(0, 80);
    if (normalized) {
      target[key] = normalized as LitioAssistantContext[T];
    }
  }

  private buildFollowUpSuggestions(intentKey = '', answer = ''): string[] {
    const context = this.getSafeContext();
    const searchable = `${intentKey} ${answer} ${context?.openModal || ''} ${context?.activeTab || ''}`.toLowerCase();
    if (searchable.includes('send_reminder') || searchable.includes('communication') || searchable.includes('whatsapp') || searchable.includes('sms')) {
      return ['Send reminder', 'WhatsApp status updates', 'SMS reminders', 'Candidate notifications'];
    }
    if (searchable.includes('explain_recommendation') || searchable.includes('next_hiring_step') || searchable.includes('evaluation_red_flags')) {
      return ['Explain recommendation', 'View red flags', 'Next hiring step', 'Send reminder'];
    }
    if (searchable.includes('candidate_job_mapping') || searchable.includes('assign')) {
      return ['Explain matching', 'Schedule Litio interview', 'Send reminder'];
    }
    if (searchable.includes('create_vacancy') || searchable.includes('post') || searchable.includes('vacancy')) {
      return ['Assign candidates', 'Explain role fit score', 'Schedule interview', 'Send reminder'];
    }
    if (searchable.includes('evaluation') || searchable.includes('score') || searchable.includes('profile')) {
      return ['Explain recommendation', 'View red flags', 'Next hiring step', 'Send reminder'];
    }
    if (searchable.includes('interview')) {
      return ['Schedule interview', 'Send reminder', 'Next hiring step'];
    }
    return ['Assign candidates', 'Explain role fit score', 'Schedule interview', 'Send reminder'];
  }

  private buildInitialSuggestionsForContext(): string[] {
    const context = this.getSafeContext();
    const modal = (context?.openModal || '').toLowerCase();
    const activeTab = (context?.activeTab || '').toLowerCase();
    const contextText = `${modal} ${activeTab} ${context?.evaluationStatus || ''}`.toLowerCase();

    if (contextText.includes('evaluation')) {
      return ['Explain recommendation', 'View red flags', 'Next hiring step', 'Send reminder'];
    }
    if (contextText.includes('candidate_profile') || context?.candidateId || context?.candidateName) {
      return ['Explain resume score', 'Explain role fit score', 'View red flags', 'Schedule interview', 'Send reminder', 'Next hiring step'];
    }
    if (contextText.includes('vacancy') || contextText.includes('role') || context?.vacancyId || context?.vacancyTitle) {
      return ['Assign candidates', 'Explain matching', 'Schedule interview', 'Send reminder'];
    }
    if (contextText.includes('communication') || contextText.includes('reminder')) {
      return ['Send reminder', 'WhatsApp status updates', 'SMS reminders', 'Candidate notifications'];
    }
    return this.initialSuggestions.slice();
  }

  private refreshInitialSuggestions(): void {
    if (!this.showSuggestions || this.isSubmitting || !this.hasOnlyInitialMessage()) {
      return;
    }
    this.suggestions = this.buildInitialSuggestionsForContext();
  }

  private hasOnlyInitialMessage(): boolean {
    return this.messages.length === 1 && this.messages[0]?.role === 'litio';
  }

  private hasContextualSuggestionSurface(): boolean {
    const context = this.getSafeContext();
    const contextText = [
      context?.openModal,
      context?.activeTab,
      context?.section,
      context?.evaluationStatus,
    ].filter(Boolean).join(' ').toLowerCase();

    return Boolean(
      context?.candidateId ||
      context?.candidateName ||
      context?.vacancyId ||
      context?.vacancyTitle ||
      contextText.includes('candidate') ||
      contextText.includes('profile') ||
      contextText.includes('evaluation') ||
      contextText.includes('role') ||
      contextText.includes('vacancy'),
    );
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
          this.initialSuggestions = suggestions.map((suggestion) => (suggestion || '').trim()).filter(Boolean);
          this.refreshInitialSuggestions();
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
