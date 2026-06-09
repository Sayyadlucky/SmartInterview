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

  function setSubmittedAptitudeSummary(): void {
    component.evaluationSummary = {
      ...component.evaluationSummary,
      aptitude_assessment: {
        available: true,
        status: 'submitted',
        status_label: 'Submitted',
        assignment_id: 12,
        title: 'Aptitude Assessment',
        scheduled_at: '',
        submitted_at: '2026-06-01T10:00:00Z',
        started_at: '2026-06-01T09:30:00Z',
        expires_at: '',
        score: 0,
        score_percent: 0,
        max_score: 16,
        passed: false,
        result_label: 'Not Passed',
        passing_score_percent: 60,
        total_questions: 16,
        answered_count: 8,
        unanswered_count: 8,
        early_exit: false,
        early_exit_reason: '',
        section_results: [
          {
            section_code: 'verbal_ability',
            section_name: 'Verbal Ability',
            score: 0,
            max_score: 16,
            score_percent: 0,
            correct_count: 0,
            incorrect_count: 0,
            unanswered_count: 8,
            total_questions: 8,
            answer_schema: 'hidden',
            correct_answer: 'hidden',
            explanations: 'hidden',
          } as any,
        ],
        integrity_summary: {
          review_required: true,
          event_count: 2,
          flags: ['Face missing', 'Tab switch'],
        },
      },
    };
  }

  it('renders submitted aptitude section rows with separate section metrics', () => {
    setSubmittedAptitudeSummary();

    const sectionHtml = component.renderAptitudeSectionBreakdown();

    expect(component.getAptitudeSectionRows().length).toBe(1);
    expect(component.getAptitudeSectionScoreText(component.getAptitudeSectionRows()[0])).toBe('0% · 0/16');
    expect(sectionHtml).toContain('<span>Correct</span>');
    expect(sectionHtml).toContain('<span>Incorrect</span>');
    expect(sectionHtml).toContain('<span>Unanswered</span>');
    expect(sectionHtml).toContain('Verbal Ability');
  });

  it('renames the assessment progress step when aptitude is scheduled for the candidate', () => {
    component.evaluationSummaryCandidate = { id: 21, candidate_action_link_type: 'aptitude' };

    const steps = component.getReportProgressSteps();

    expect(steps[1].label).toBe('Aptitude Assessment');
  });

  it('keeps the technical assessment progress step when aptitude is not scheduled', () => {
    component.evaluationSummaryCandidate = { id: 22, candidate_action_link_type: 'interview' };
    component.evaluationSummary = {
      ...component.evaluationSummary,
      aptitude_assessment: {
        ...component.evaluationSummary.aptitude_assessment,
        available: false,
        assignment_id: null,
      },
    };

    const steps = component.getReportProgressSteps();

    expect(steps[1].label).toBe('Technical Assessment');
  });

  it('renders aptitude integrity flags as report chips', () => {
    setSubmittedAptitudeSummary();

    const integrityHtml = component.renderAptitudeIntegritySummary();

    expect(component.getAptitudeIntegrityFlags()).toEqual(['Face missing', 'Tab switch']);
    expect(integrityHtml).toContain('report-aptitude-integrity-flags');
    expect(integrityHtml).toContain('Face missing');
    expect(integrityHtml).toContain('Tab switch');
  });

  it('does not render aptitude answer keys or schemas in the detailed report', () => {
    setSubmittedAptitudeSummary();

    const reportHtml = component.renderAptitudeReportSection();

    expect(reportHtml).not.toContain('answer_schema');
    expect(reportHtml).not.toContain('correct_answer');
    expect(reportHtml).not.toContain('explanations');
    expect(reportHtml).not.toContain('hidden');
  });
});
