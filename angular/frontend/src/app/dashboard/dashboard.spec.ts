import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

import { Dashboard } from './dashboard';

describe('Dashboard', () => {
  let component: Dashboard;
  let fixture: ComponentFixture<Dashboard>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Dashboard],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    })
    .compileComponents();

    fixture = TestBed.createComponent(Dashboard);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('uses aptitude action link metadata when aptitude is pending', () => {
    const candidate = {
      id: 7,
      candidate_action_link: 'https://litio.shortlistii.com/aptitude/token/',
      candidate_action_link_type: 'aptitude',
      candidate_action_link_label: 'Aptitude Test Link',
      interview_link: 'https://litio.shortlistii.com/i/interview',
    };

    expect(component.getCandidateActionLink(candidate)).toBe(candidate.candidate_action_link);
    expect(component.getCandidateActionLinkType(candidate)).toBe('aptitude');
    expect(component.getCandidateActionLinkLabel(candidate)).toBe('Aptitude Test Link');
    expect(component.getCandidateActionCopyLabel(candidate)).toBe('Copy Aptitude Link');
    expect(component.getCandidateActionVisitLabel(candidate)).toBe('Open Aptitude Test');
    expect(component.getCandidateActionEmailLabel(candidate)).toBe('Send Schedule Email');
  });

  it('falls back to interview link behavior when aptitude is complete or absent', () => {
    const candidate = {
      id: 9,
      candidate_action_link_type: 'interview',
      interview_link: 'https://litio.shortlistii.com/i/interview',
    };

    expect(component.getCandidateActionLink(candidate)).toBe(candidate.interview_link);
    expect(component.getCandidateActionLinkType(candidate)).toBe('interview');
    expect(component.getCandidateActionLinkLabel(candidate)).toBe('Interview Link');
    expect(component.getCandidateActionCopyLabel(candidate)).toBe('Copy Interview Link');
    expect(component.getCandidateActionVisitLabel(candidate)).toBe('Visit Interview Link');
    expect(component.getCandidateActionEmailLabel(candidate)).toBe('Send Email');
  });
});
