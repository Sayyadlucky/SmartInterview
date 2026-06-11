import { CommonModule } from '@angular/common';
import { Component, DestroyRef, ElementRef, ViewChild, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { finalize } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { LitioAssistantService } from './litio-assistant.service';

type LitioMessageSender = 'user' | 'assistant';
type LitioFeedbackRating = 'yes' | 'no' | 'needs_help';
type LitioFeedbackState = 'idle' | 'collecting-no' | 'saving' | 'saved';

interface LitioChatMessage {
  localId: string;
  sender: LitioMessageSender;
  text: string;
  messageId?: number;
  showFeedback?: boolean;
  feedbackState?: LitioFeedbackState;
  feedbackComment?: string;
  feedbackLabel?: string;
  isError?: boolean;
}

@Component({
  selector: 'app-litio-assistant',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './litio-assistant.html',
  styleUrls: ['./litio-assistant.scss'],
})
export class LitioAssistantComponent {
  private readonly assistantService = inject(LitioAssistantService);
  private readonly destroyRef = inject(DestroyRef);

  @ViewChild('messageViewport') messageViewport?: ElementRef<HTMLElement>;
  @ViewChild('composerInput') composerInput?: ElementRef<HTMLTextAreaElement>;

  readonly quickChips = [
    'Create a vacancy',
    'Add candidates',
    'Explain AI Talent Pool',
    'Assign Litio interview',
    'Assign aptitude test',
    'Understand candidate scores',
    'Share feedback',
  ];

  isOpen = false;
  hasOpened = false;
  isSending = false;
  composerValue = '';
  conversationId: number | null = null;
  latestSuggestions: string[] = [];
  messages: LitioChatMessage[] = [
    {
      localId: 'welcome',
      sender: 'assistant',
      text: "Hi, I'm Litio AI Assistant. I can help you use Shortlistii, understand candidate scores, assign interviews, manage aptitude tests, review reports, and share feedback.",
      showFeedback: false,
    },
  ];

  openAssistant(): void {
    this.isOpen = true;
    this.hasOpened = true;
    this.scrollToLatest();
    setTimeout(() => this.composerInput?.nativeElement.focus(), 160);
  }

  closeAssistant(): void {
    this.isOpen = false;
  }

  resetChat(): void {
    this.conversationId = null;
    this.latestSuggestions = [];
    this.composerValue = '';
    this.messages = [
      {
        localId: 'welcome',
        sender: 'assistant',
        text: "Hi, I'm Litio AI Assistant. I can help you use Shortlistii, understand candidate scores, assign interviews, manage aptitude tests, review reports, and share feedback.",
        showFeedback: false,
      },
    ];
    this.scrollToLatest();
  }

  sendQuickChip(chip: string): void {
    this.openAssistant();
    this.sendMessage(chip);
  }

  onComposerKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
  }

  sendMessage(explicitMessage?: string): void {
    const message = (explicitMessage ?? this.composerValue).trim();
    if (!message || this.isSending) {
      return;
    }
    this.messages.push({
      localId: this.createLocalId('user'),
      sender: 'user',
      text: message,
    });
    this.composerValue = '';
    this.isSending = true;
    this.scrollToLatest();

    this.assistantService.chat({
      message,
      conversation_id: this.conversationId,
      page_context: this.currentPageContext(),
      page_url: this.currentPageUrl(),
    })
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => {
          this.isSending = false;
          this.scrollToLatest();
        }),
      )
      .subscribe({
        next: (response) => {
          if (!response.success || !response.data) {
            this.addErrorMessage();
            return;
          }
          this.conversationId = response.data.conversation_id;
          this.latestSuggestions = response.data.suggestions || [];
          this.messages.push({
            localId: this.createLocalId('assistant'),
            sender: 'assistant',
            text: response.data.answer,
            messageId: response.data.message_id,
            showFeedback: response.data.show_feedback,
            feedbackState: 'idle',
            feedbackComment: '',
          });
        },
        error: () => this.addErrorMessage(),
      });
  }

  submitFeedback(message: LitioChatMessage, rating: LitioFeedbackRating): void {
    if (!this.conversationId || message.feedbackState === 'saving' || message.feedbackState === 'saved') {
      return;
    }
    if (rating === 'no' && message.feedbackState !== 'collecting-no') {
      message.feedbackState = 'collecting-no';
      message.feedbackComment = '';
      return;
    }
    message.feedbackState = 'saving';
    this.assistantService.feedback({
      conversation_id: this.conversationId,
      message_id: message.messageId || null,
      rating,
      comment: message.feedbackComment || '',
      page_context: this.currentPageContext(),
      page_url: this.currentPageUrl(),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          message.feedbackState = 'saved';
          message.feedbackLabel = rating === 'yes'
            ? 'Thanks for the feedback.'
            : rating === 'needs_help'
              ? 'Marked. Keep chatting and I will help further.'
              : 'Thanks. Your feedback was saved.';
          if (rating === 'needs_help') {
            setTimeout(() => this.composerInput?.nativeElement.focus(), 80);
          }
        },
        error: () => {
          message.feedbackState = 'idle';
          message.feedbackLabel = 'Feedback could not be saved. Please try again.';
        },
      });
  }

  private addErrorMessage(): void {
    this.messages.push({
      localId: this.createLocalId('assistant-error'),
      sender: 'assistant',
      text: "I couldn't answer that right now. Please try again.",
      showFeedback: false,
      isError: true,
    });
  }

  private currentPageContext(): string {
    return 'dashboard';
  }

  private currentPageUrl(): string {
    return `${window.location.pathname}${window.location.search}`;
  }

  private createLocalId(prefix: string): string {
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  private scrollToLatest(): void {
    setTimeout(() => {
      const viewport = this.messageViewport?.nativeElement;
      if (viewport) {
        viewport.scrollTop = viewport.scrollHeight;
      }
    }, 0);
  }
}
