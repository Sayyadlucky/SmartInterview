import { ComponentFixture, fakeAsync, TestBed, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { LitioAssistant } from './litio-assistant';

describe('LitioAssistant', () => {
  let fixture: ComponentFixture<LitioAssistant>;
  let component: LitioAssistant;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    document.body.removeAttribute('data-user-initials');
    document.body.removeAttribute('data-user-name');
    document.body.removeAttribute('data-user-email');

    await TestBed.configureTestingModule({
      imports: [LitioAssistant],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(LitioAssistant);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    const suggestionsRequest = httpMock.expectOne((request) => request.url.endsWith('/api/litio-assistant/suggestions/'));
    suggestionsRequest.flush({
      success: true,
      data: { suggestions: ['How do I post a job?', 'How do I assign a candidate to a role?'] },
    });
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify();
  });

  function flushPaint(): void {
    tick(16);
  }

  it('creates with suggestions', () => {
    expect(component).toBeTruthy();
    expect(component.suggestions).toContain('How do I post a job?');
  });

  it('shows suggestions initially', () => {
    component.open();
    fixture.detectChanges();

    const suggestionButtons = fixture.nativeElement.querySelectorAll('.litio-quick-chips button');
    expect(component.showSuggestions).toBeTrue();
    expect(suggestionButtons.length).toBeGreaterThan(0);
  });

  it('shows launcher when closed and hides it when open', () => {
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.litio-fab')).not.toBeNull();

    component.open();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.litio-fab')).toBeNull();
    expect(fixture.nativeElement.querySelector('.litio-panel.is-open')).not.toBeNull();
  });

  it('renders an accessible restart chat button', () => {
    component.open();
    fixture.detectChanges();

    const restartButton = fixture.nativeElement.querySelector('button[aria-label="Restart Litio chat"]');
    const closeButton = fixture.nativeElement.querySelector('button[aria-label="Close Litio AI Assistant"]');
    expect(restartButton).not.toBeNull();
    expect(closeButton).not.toBeNull();
  });

  it('derives AH from a full display name', () => {
    document.body.dataset['userInitials'] = 'kk';
    component.userDisplayName = 'Altamash Hasan';

    expect(component.getUserInitials()).toBe('AH');
  });

  it('derives A from a single display name', () => {
    component.userDisplayName = ' Altamash ';

    expect(component.getUserInitials()).toBe('A');
  });

  it('falls back to email when display name is empty', () => {
    component.userDisplayName = '';
    component.userEmail = 'hasanaltamash1993@gmail.com';

    expect(component.getUserInitials()).toBe('HA');
  });

  it('falls back to U only when no identity data exists', () => {
    component.userDisplayName = '';
    component.userEmail = '';
    component.explicitUserInitials = '';

    expect(component.getUserInitials()).toBe('U');
  });

  it('renders assistant and user avatars', fakeAsync(() => {
    component.userDisplayName = 'Altamash Hasan';
    component.open();
    component.inputText = 'assign candidate to role';
    component.sendMessage();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.litio-assistant-avatar')).not.toBeNull();
    const userAvatar = fixture.nativeElement.querySelector('.litio-user-avatar');
    expect(userAvatar).not.toBeNull();
    expect(userAvatar.textContent.trim()).toBe('AH');
    expect(fixture.nativeElement.querySelectorAll('.litio-message-row.is-user .litio-user-avatar').length).toBe(1);

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    request.flush({
      success: true,
      data: {
        conversation_id: 4,
        assistant_message_id: 9,
        answer: 'Open Candidates and choose a role or vacancy.',
      },
    });
    tick(900);
    flushPaint();
  }));

  it('shows typing indicator while sending and removes it after response', fakeAsync(() => {
    component.open();
    component.inputText = 'schedule interview';
    component.sendMessage();
    fixture.detectChanges();

    expect(component.isSending).toBeTrue();
    expect(component.isSubmitting).toBeTrue();
    expect(component.isAssistantTyping).toBeTrue();
    expect(fixture.nativeElement.querySelector('.litio-typing')).not.toBeNull();

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    request.flush({
      success: true,
      data: {
        conversation_id: 4,
        assistant_message_id: 9,
        answer: 'Choose the interview action and save the schedule.',
      },
    });
    tick(899);
    fixture.detectChanges();

    expect(component.isAssistantTyping).toBeTrue();
    expect(fixture.nativeElement.querySelector('.litio-typing')).not.toBeNull();
    expect(component.messages.some((message) => message.text.includes('save the schedule'))).toBeFalse();

    tick(1);
    flushPaint();
    fixture.detectChanges();

    expect(component.isSending).toBeFalse();
    expect(component.isSubmitting).toBeFalse();
    expect(component.isAssistantTyping).toBeFalse();
    expect(fixture.nativeElement.querySelector('.litio-typing')).toBeNull();
    expect(component.messages.some((message) => message.text.includes('save the schedule'))).toBeTrue();
  }));

  it('hides suggestions after the first user send', fakeAsync(() => {
    component.open();
    component.inputText = 'schedule interview';
    component.sendMessage();
    fixture.detectChanges();

    expect(component.showSuggestions).toBeFalse();
    expect(fixture.nativeElement.querySelector('.litio-quick-chips')).toBeNull();

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    request.flush({
      success: true,
      data: {
        conversation_id: 4,
        assistant_message_id: 9,
        answer: 'Choose the interview action and save the schedule.',
        suggestions: ['How do I post a job?'],
      },
    });
    tick(900);
    flushPaint();
    fixture.detectChanges();

    expect(component.showSuggestions).toBeFalse();
    expect(fixture.nativeElement.querySelector('.litio-quick-chips')).toBeNull();
  }));

  it('does not create duplicate typing indicators or duplicate requests while pending', fakeAsync(() => {
    component.open();
    component.inputText = 'schedule interview';
    component.sendMessage();
    component.inputText = 'post a job';
    component.sendMessage();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelectorAll('.litio-typing').length).toBe(1);
    expect(component.messages.filter((message) => message.role === 'user').length).toBe(1);

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    request.flush({
      success: true,
      data: {
        conversation_id: 4,
        assistant_message_id: 9,
        answer: 'Choose the interview action and save the schedule.',
      },
    });
    tick(900);
    flushPaint();
  }));

  it('keeps send button available when not submitting', () => {
    component.open();
    component.inputText = 'post a job';
    fixture.detectChanges();

    const button = fixture.nativeElement.querySelector('.litio-composer button') as HTMLButtonElement;
    expect(button).not.toBeNull();
    expect(button.disabled).toBeFalse();
  });

  it('restarts the chat locally and shows suggestions again', fakeAsync(() => {
    component.open();
    component.conversationId = 4;
    component.inputText = 'draft message';
    component.isSubmitting = true;
    component.isAssistantTyping = true;
    component.showSuggestions = false;
    component.messages = [
      { id: null, role: 'litio', text: 'Welcome' },
      { id: null, role: 'user', text: 'schedule interview' },
      { id: 9, role: 'litio', text: 'Answer', pendingFeedback: true },
    ];
    fixture.detectChanges();

    component.restartChat();
    tick(0);
    fixture.detectChanges();

    expect(component.conversationId).toBeNull();
    expect(component.inputText).toBe('');
    expect(component.isSubmitting).toBeFalse();
    expect(component.isAssistantTyping).toBeFalse();
    expect(component.showSuggestions).toBeTrue();
    expect(component.messages.length).toBe(1);
    expect(component.messages[0].role).toBe('litio');
    expect(fixture.nativeElement.querySelector('.litio-quick-chips')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.litio-panel.is-open')).not.toBeNull();
  }));

  it('keeps Shift+Enter available for textarea new lines', fakeAsync(() => {
    component.open();
    fixture.detectChanges();

    const textarea = fixture.nativeElement.querySelector('.litio-composer textarea') as HTMLTextAreaElement;
    const shiftEnter = new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, cancelable: true });
    const eventResult = textarea.dispatchEvent(shiftEnter);
    tick(0);

    textarea.value = 'Line one\nLine two';
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    expect(eventResult).toBeTrue();
    expect(shiftEnter.defaultPrevented).toBeFalse();
    expect(component.inputText).toBe('Line one\nLine two');
    httpMock.expectNone((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
  }));

  it('sends from textarea on Enter without Shift', fakeAsync(() => {
    component.open();
    fixture.detectChanges();

    const textarea = fixture.nativeElement.querySelector('.litio-composer textarea') as HTMLTextAreaElement;
    textarea.value = 'post a job';
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    const enter = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true });
    const eventResult = textarea.dispatchEvent(enter);

    expect(eventResult).toBeFalse();
    expect(enter.defaultPrevented).toBeTrue();
    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    expect(request.request.body.message).toBe('post a job');
    request.flush({
      success: true,
      data: {
        conversation_id: 4,
        assistant_message_id: 9,
        answer: 'Open Jobs and create the posting.',
      },
    });
    tick(900);
    flushPaint();
  }));

  it('caps textarea growth and resets height after send', fakeAsync(() => {
    component.open();
    fixture.detectChanges();

    const textarea = fixture.nativeElement.querySelector('.litio-composer textarea') as HTMLTextAreaElement;
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 180 });
    textarea.value = 'This is a long message that should grow the composer over multiple visible lines.';
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    expect(textarea.style.height).toBe('124px');
    expect(textarea.style.overflowY).toBe('auto');

    component.sendMessage();
    tick(0);

    expect(textarea.style.height).toBe('46px');
    expect(textarea.style.overflowY).toBe('hidden');

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    request.flush({
      success: true,
      data: {
        conversation_id: 4,
        assistant_message_id: 9,
        answer: 'Open Jobs and create the posting.',
      },
    });
    tick(900);
    flushPaint();
  }));

  it('opens and sends a chat message', fakeAsync(() => {
    component.open();
    component.inputText = 'assign candidate to role';
    component.sendMessage();

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    expect(request.request.method).toBe('POST');
    expect(request.request.body.message).toBe('assign candidate to role');
    request.flush({
      success: true,
      data: {
        conversation_id: 4,
        assistant_message_id: 9,
        answer: 'Open Candidates and choose a role or vacancy.',
        suggestions: ['How do I post a job?'],
      },
    });
    tick(900);
    flushPaint();

    expect(component.conversationId).toBe(4);
    expect(component.messages.some((message) => message.role === 'user')).toBeTrue();
    expect(component.messages.some((message) => message.text.includes('role or vacancy'))).toBeTrue();
  }));

  it('shows a clean assistant error bubble after failed send', fakeAsync(() => {
    component.open();
    component.inputText = 'post a job';
    component.sendMessage();
    fixture.detectChanges();

    expect(component.isAssistantTyping).toBeTrue();
    expect(fixture.nativeElement.querySelector('.litio-typing')).not.toBeNull();

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    request.flush({ success: false, error: 'Litio could not answer right now.' });
    tick(899);
    fixture.detectChanges();

    expect(component.isAssistantTyping).toBeTrue();
    expect(fixture.nativeElement.querySelector('.litio-typing')).not.toBeNull();
    expect(component.messages.filter((message) => message.role === 'litio' && message.tone === 'error').length).toBe(0);

    tick(1);
    flushPaint();
    fixture.detectChanges();

    expect(component.isSending).toBeFalse();
    expect(component.isSubmitting).toBeFalse();
    expect(component.isAssistantTyping).toBeFalse();
    expect(component.messages.filter((message) => message.role === 'litio' && message.tone === 'error').length).toBe(1);
    expect(fixture.nativeElement.querySelector('.litio-message-bubble.is-error')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.litio-typing')).toBeNull();
  }));

  it('saves feedback for an assistant message', () => {
    component.conversationId = 4;
    const message: any = {
      id: 9,
      role: 'litio' as const,
      text: 'Answer',
      pendingFeedback: true,
    };

    component.sendFeedback(message, 'helpful');

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/feedback/'));
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({
      conversation_id: 4,
      message_id: 9,
      rating: 'helpful',
    });
    request.flush({ success: true, data: { saved: true } });

    expect(message.feedback).toBe('helpful');
  });
});
