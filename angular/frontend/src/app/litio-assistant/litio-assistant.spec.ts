import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { By } from '@angular/platform-browser';

import { LitioAssistantComponent } from './litio-assistant';

describe('LitioAssistantComponent', () => {
  let component: LitioAssistantComponent;
  let fixture: ComponentFixture<LitioAssistantComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LitioAssistantComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(LitioAssistantComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('opens the chat drawer from the floating Ask Litio button', () => {
    fixture.debugElement.query(By.css('.litio-fab')).nativeElement.click();
    fixture.detectChanges();

    expect(component.isOpen).toBeTrue();
    expect(fixture.debugElement.query(By.css('.litio-panel')).nativeElement.classList).toContain('is-open');
  });

  it('aligns user messages right and assistant messages left after a response', () => {
    component.openAssistant();
    component.composerValue = 'Create a vacancy';
    component.sendMessage();
    fixture.detectChanges();

    expect(fixture.debugElement.query(By.css('.litio-message.is-user'))).toBeTruthy();
    expect(fixture.debugElement.query(By.css('.litio-message.is-typing'))).toBeTruthy();

    const request = httpMock.expectOne((req) => req.url.endsWith('/api/litio-assistant/chat/'));
    expect(request.request.body.message).toBe('Create a vacancy');
    request.flush({
      success: true,
      error: null,
      data: {
        conversation_id: 44,
        message_id: 88,
        answer: 'Open Job Postings and click Create Vacancy.',
        intent: 'how_to',
        category: 'vacancy',
        suggestions: ['Add candidates'],
        show_feedback: true,
      },
    });
    fixture.detectChanges();

    const assistantMessages = fixture.debugElement.queryAll(By.css('.litio-message.is-assistant'));
    expect(assistantMessages.length).toBeGreaterThan(0);
    expect(fixture.nativeElement.textContent).toContain('Open Job Postings and click Create Vacancy.');
    expect(fixture.debugElement.query(By.css('.litio-feedback'))).toBeTruthy();
  });

  it('sends a quick chip as a chat message', () => {
    component.openAssistant();
    fixture.detectChanges();

    fixture.debugElement.query(By.css('.litio-quick-chips button')).nativeElement.click();
    fixture.detectChanges();

    const request = httpMock.expectOne((req) => req.url.endsWith('/api/litio-assistant/chat/'));
    expect(request.request.body.message).toBe('Create a vacancy');
    request.flush({
      success: true,
      error: null,
      data: {
        conversation_id: 45,
        message_id: 89,
        answer: 'Use Create Vacancy from Job Postings.',
        intent: 'how_to',
        category: 'vacancy',
        suggestions: [],
        show_feedback: true,
      },
    });
  });

  it('submits feedback for assistant answers', () => {
    component.openAssistant();
    component.sendMessage('Understand candidate scores');

    const chatRequest = httpMock.expectOne((req) => req.url.endsWith('/api/litio-assistant/chat/'));
    chatRequest.flush({
      success: true,
      error: null,
      data: {
        conversation_id: 46,
        message_id: 90,
        answer: 'Scores are fit indicators.',
        intent: 'score_explanation',
        category: 'score',
        suggestions: [],
        show_feedback: true,
      },
    });
    fixture.detectChanges();

    fixture.debugElement.query(By.css('.litio-feedback-actions button')).nativeElement.click();
    const feedbackRequest = httpMock.expectOne((req) => req.url.endsWith('/api/litio-assistant/feedback/'));
    expect(feedbackRequest.request.body.rating).toBe('yes');
    expect(feedbackRequest.request.body.conversation_id).toBe(46);
    feedbackRequest.flush({
      success: true,
      error: null,
      data: { success: true, feedback_id: 12 },
    });
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Thanks for the feedback.');
  });
});
