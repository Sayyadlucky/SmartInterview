import { ComponentFixture, fakeAsync, TestBed, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { Router } from '@angular/router';
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
      imports: [LitioAssistant, RouterTestingModule.withRoutes([{ path: 'dashboard', children: [] }])],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
      teardown: { destroyAfterEach: false },
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
    expect(fixture.nativeElement.querySelector('.litio-suggestions-label')?.textContent.trim()).toBe('Suggested questions');
  });

  it('hides suggestions label when suggestions are hidden', () => {
    component.open();
    component.showSuggestions = false;
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.litio-suggestions')).toBeNull();
    expect(fixture.nativeElement.querySelector('.litio-suggestions-label')).toBeNull();
  });

  it('shows launcher when closed and hides it when open', () => {
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.litio-fab')).not.toBeNull();

    component.open();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.litio-fab')).toBeNull();
    expect(fixture.nativeElement.querySelector('.litio-panel.is-open')).not.toBeNull();
  });

  it('renders the launcher when context is null', () => {
    component.context = null;
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.litio-fab')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.litio-panel.is-open')).toBeNull();
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

  it('renders action chips and navigates on click', fakeAsync(() => {
    component.open();
    component.inputText = 'show SLA breaches';
    component.sendMessage();
    fixture.detectChanges();

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    request.flush({
      success: true,
      data: {
        conversation_id: 5,
        assistant_message_id: 11,
        answer: 'You have 1 SLA breached candidate.',
        intent_key: 'data_sla_breaches',
        actions: [
          { label: 'View SLA breached candidates', action_type: 'navigate', route: '/dashboard', query_params: { section: 'candidates', filter: 'sla_breached' } }
        ]
      }
    });
    tick(900);
    fixture.detectChanges();

    const actionButtons = fixture.nativeElement.querySelectorAll('.litio-action-chip');
    expect(actionButtons.length).toBeGreaterThan(0);
    const router = TestBed.inject(Router);
    const navSpy = spyOn(router, 'navigate').and.callThrough();
    (actionButtons[0] as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(navSpy).toHaveBeenCalled();
    // assistant panel should close after navigation action
    expect(component.isOpen).toBeFalse();
  }));

  it('ignores unknown action types', fakeAsync(() => {
    component.open();
    component.inputText = 'show unknown action';
    component.sendMessage();
    fixture.detectChanges();

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    request.flush({
      success: true,
      data: {
        conversation_id: 6,
        assistant_message_id: 12,
        answer: 'Unknown action present.',
        intent_key: 'data_unknown',
        actions: [
          { label: 'Do something unsafe', action_type: 'unknown', route: '/dashboard', query_params: { } }
        ]
      }
    });
    tick(900);
    fixture.detectChanges();

    const actionButtons = fixture.nativeElement.querySelectorAll('.litio-action-chip');
    expect(actionButtons.length).toBeGreaterThan(0);
    const router = TestBed.inject(Router);
    const navSpy = spyOn(router, 'navigate').and.callThrough();
    (actionButtons[0] as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(navSpy).not.toHaveBeenCalled();
  }));

  it('handles missing route by falling back to dashboard', fakeAsync(() => {
    component.open();
    component.inputText = 'missing route action';
    component.sendMessage();
    fixture.detectChanges();

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    request.flush({
      success: true,
      data: {
        conversation_id: 7,
        assistant_message_id: 13,
        answer: 'Missing route action.',
        intent_key: 'data_missing_route',
        actions: [
          { label: 'Open candidates', action_type: 'navigate', query_params: { section: 'candidates' } }
        ]
      }
    });
    tick(900);
    fixture.detectChanges();

    const actionButtons = fixture.nativeElement.querySelectorAll('.litio-action-chip');
    expect(actionButtons.length).toBeGreaterThan(0);
    const router = TestBed.inject(Router);
    const navSpy = spyOn(router, 'navigate').and.callThrough();
    (actionButtons[0] as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(navSpy).toHaveBeenCalled();
    expect(component.isOpen).toBeFalse();
  }));

  it('hides suggestions while sending and shows contextual follow-ups after the assistant response', fakeAsync(() => {
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
        intent_key: 'schedule_interview',
      },
    });
    tick(900);
    flushPaint();
    fixture.detectChanges();

    expect(component.showSuggestions).toBeTrue();
    expect(fixture.nativeElement.querySelector('.litio-suggestions-label')?.textContent.trim()).toBe('Suggested next questions');
    const suggestionButtons = Array.from<Element>(
      fixture.nativeElement.querySelectorAll('.litio-quick-chips button'),
    ).map((button: Element) => button.textContent?.trim());
    expect(suggestionButtons).toContain('Schedule interview');
    expect(suggestionButtons).not.toContain('Prepare candidate');
    expect(suggestionButtons).not.toContain('Review evaluation');
  }));

  it('clicking Assign candidates suggestion sends a non-empty mapped prompt', fakeAsync(() => {
    component.open();
    component.inputText = '';
    component.suggestions = ['Assign candidates'];
    component.showSuggestions = true;
    fixture.detectChanges();

    const suggestionButton = fixture.nativeElement.querySelector('.litio-quick-chips button') as HTMLButtonElement;
    suggestionButton.click();
    fixture.detectChanges();

    const userMessages = component.messages.filter((message) => message.role === 'user');
    expect(userMessages.length).toBe(1);
    expect(userMessages[0].text).toBe('How do I assign candidates to a vacancy?');
    // suggestion clicks should NOT close the assistant panel
    expect(component.isOpen).toBeTrue();
    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    expect(request.request.body.message).toBe('How do I assign candidates to a vacancy?');
    request.flush({
      success: true,
      data: {
        conversation_id: 4,
        assistant_message_id: 9,
        answer: 'Use the assignment or matching action from the vacancy view.',
        intent_key: 'candidate_job_mapping',
      },
    });
    tick(900);
    flushPaint();
  }));

  it('clicking Send reminder suggestion sends a non-empty prompt and renders no blank rows', fakeAsync(() => {
    component.open();
    component.inputText = '';
    component.suggestions = ['Send reminder'];
    component.showSuggestions = true;
    fixture.detectChanges();

    const suggestionButton = fixture.nativeElement.querySelector('.litio-quick-chips button') as HTMLButtonElement;
    suggestionButton.click();
    fixture.detectChanges();

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    expect(request.request.body.message).toBe('How do I send a candidate reminder?');
    expect(component.messages.filter((message) => message.role === 'user')[0].text).toBe('How do I send a candidate reminder?');
    // suggestion clicks should not close the assistant panel
    expect(component.isOpen).toBeTrue();
    request.flush({
      success: true,
      data: {
        conversation_id: 4,
        assistant_message_id: 9,
        answer: 'Use the configured communication action from the candidate workflow.',
        intent_key: 'send_reminder',
      },
    });
    tick(900);
    flushPaint();
    fixture.detectChanges();

    const renderedText = Array.from<Element>(
      fixture.nativeElement.querySelectorAll('.litio-message-bubble p'),
    ).map((element: Element) => element.textContent?.trim() || '');
    expect(renderedText.every(Boolean)).toBeTrue();
  }));

  it('ignores blank suggestion clicks without creating a user message', () => {
    component.open();
    component.useSuggestion('   ');
    fixture.detectChanges();

    expect(component.messages.filter((message) => message.role === 'user').length).toBe(0);
    httpMock.expectNone((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
  });

  it('does not append a blank message for empty or whitespace composer submits', () => {
    component.open();
    component.inputText = '   ';
    component.sendMessage();
    component.inputText = '';
    component.sendMessage();
    fixture.detectChanges();

    expect(component.messages.filter((message) => message.role === 'user').length).toBe(0);
    httpMock.expectNone((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
  });

  it('does not render blank rows for empty message content', () => {
    component.open();
    component.messages = [
      { id: null, role: 'litio', text: 'Welcome' },
      { id: null, role: 'user', text: '   ' },
      { id: 9, role: 'litio', text: '' },
    ];
    fixture.detectChanges();

    const rows = fixture.nativeElement.querySelectorAll('.litio-conversation .litio-message-row:not(.litio-typing-row)');
    const renderedText = Array.from<Element>(
      fixture.nativeElement.querySelectorAll('.litio-message-bubble p'),
    ).map((element: Element) => element.textContent?.trim() || '');
    expect(rows.length).toBe(1);
    expect(renderedText).toEqual(['Welcome']);
  });

  it('uses fallback text for an empty assistant response', fakeAsync(() => {
    component.open();
    component.inputText = 'send reminder';
    component.sendMessage();

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    request.flush({
      success: true,
      data: {
        conversation_id: 4,
        assistant_message_id: 9,
        answer: '   ',
        intent_key: 'send_reminder',
      },
    });
    tick(900);
    flushPaint();
    fixture.detectChanges();

    const assistantMessages = component.messages.filter((message) => message.role === 'litio');
    expect(assistantMessages.some((message) => message.text.includes('complete answer'))).toBeTrue();
    const renderedText = Array.from<Element>(
      fixture.nativeElement.querySelectorAll('.litio-message-bubble p'),
    ).map((element: Element) => element.textContent?.trim() || '');
    expect(renderedText.every(Boolean)).toBeTrue();
  }));

  it('shows candidate profile suggestions without post-job chip', () => {
    component.context = {
      page: 'Recruiter dashboard',
      activeTab: 'candidates',
      openModal: 'candidate_profile',
      candidateId: 42,
      candidateName: 'Asha Hire',
      candidateStage: 'shortlisted',
    };
    component.open();
    fixture.detectChanges();

    const suggestionButtons = Array.from<Element>(
      fixture.nativeElement.querySelectorAll('.litio-quick-chips button'),
    ).map((button: Element) => button.textContent?.trim());
    expect(suggestionButtons).toContain('Explain resume score');
    expect(suggestionButtons).toContain('View red flags');
    expect(suggestionButtons).not.toContain('How do I post a job?');
  });

  it('shows evaluation context suggestions', () => {
    component.context = {
      page: 'Recruiter dashboard',
      activeTab: 'candidates',
      openModal: 'candidate_evaluation_summary',
      candidateId: 42,
      evaluationStatus: 'available',
    };
    component.open();
    fixture.detectChanges();

    const suggestionButtons = Array.from<Element>(
      fixture.nativeElement.querySelectorAll('.litio-quick-chips button'),
    ).map((button: Element) => button.textContent?.trim());
    expect(suggestionButtons).toContain('Explain recommendation');
    expect(suggestionButtons).toContain('View red flags');
    expect(suggestionButtons).toContain('Next hiring step');
  });

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
    const suggestionButtons = Array.from<Element>(
      fixture.nativeElement.querySelectorAll('.litio-quick-chips button'),
    ).map((button: Element) => button.textContent?.trim());
    expect(suggestionButtons).toContain('How do I post a job?');
    expect(component.messages.length).toBe(1);
    expect(component.messages[0].role).toBe('litio');
    expect(fixture.nativeElement.querySelector('.litio-quick-chips')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.litio-suggestions-label')?.textContent.trim()).toBe('Suggested questions');
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

  it('includes safe context in chat requests when context input is available', fakeAsync(() => {
    component.context = {
      page: 'Recruiter dashboard',
      activeTab: 'ai-talent-pool',
      openModal: 'vacancy_detail',
      vacancyId: 12,
      vacancyTitle: 'Backend Engineer',
      candidateName: '',
    };
    component.open();
    component.inputText = 'how do I assign candidates here?';
    component.sendMessage();

    const request = httpMock.expectOne((incoming) => incoming.url.endsWith('/api/litio-assistant/chat/'));
    expect(request.request.body.context).toEqual({
      page: 'Recruiter dashboard',
      activeTab: 'ai-talent-pool',
      openModal: 'vacancy_detail',
      vacancyId: '12',
      vacancyTitle: 'Backend Engineer',
    });
    request.flush({
      success: true,
      data: {
        conversation_id: 4,
        assistant_message_id: 9,
        answer: 'From this vacancy view, use candidate matching.',
        intent_key: 'candidate_job_mapping',
      },
    });
    tick(900);
    flushPaint();
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
