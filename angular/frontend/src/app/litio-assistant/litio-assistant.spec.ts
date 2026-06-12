import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { LitioAssistant } from './litio-assistant';

describe('LitioAssistant', () => {
  let fixture: ComponentFixture<LitioAssistant>;
  let component: LitioAssistant;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
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

  it('creates with suggestions', () => {
    expect(component).toBeTruthy();
    expect(component.suggestions).toContain('How do I post a job?');
  });

  it('opens and sends a chat message', () => {
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

    expect(component.conversationId).toBe(4);
    expect(component.messages.some((message) => message.role === 'user')).toBeTrue();
    expect(component.messages.some((message) => message.text.includes('role or vacancy'))).toBeTrue();
  });

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
