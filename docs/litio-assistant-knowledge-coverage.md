# Litio Assistant Knowledge Coverage

## Purpose
This document inventories user-facing dashboard sections and maps them to Litio Assistant intents and suggested user questions. It is intended for product and developer teams to ensure assistant coverage for visible workflows (no internal implementation details or secrets included).

## Coverage Status Legend
- Covered: Assistant provides deterministic answers for this area.
- Partially covered: Assistant provides some guidance but may lack depth or context-aware responses.
- Missing: No assistant guidance exists yet.
- Needs product confirmation: Clarification required from product on intended behavior or wording.

## Dashboard / Recruiter Sections

### 1. Overview / Dashboard Home
- Visible UI elements: KPI cards, AI Hiring Insight, company card, utility chips, tabs (Overview, Activity, Analytics), pending actions.
- What users may ask:
  - "What do the dashboard KPIs mean?"
  - "How do I review pending actions?"
  - "What is AI Hiring Insight?"
- Assistant intents: `known_feature`, `dashboard_analytics`, `candidate_pipeline`.
- Current coverage: Partially covered
- Missing answer gaps: Deeper per-KPI explanations, export steps, and filtering guidance.

### 2. Job Postings / Vacancy Management
- Visible UI elements: Job Postings tab, vacancy detail modal, create vacancy action.
- What users may ask:
  - "How do I post a job?"
  - "How do I edit a vacancy?"
- Assistant intents: `create_vacancy`
- Current coverage: Covered
- Missing answer gaps: Bulk edit guidance, template fields explanation (needs product confirmation).

### 3. Candidate List / Candidate Profile
- Visible UI elements: Candidate table/list, profile modal, profile sections (resume, scores, notes), action menu.
- What users may ask:
  - "How do I open a candidate profile?"
  - "What is the resume score?"
  - "How do I interpret this evaluation?"
- Assistant intents: `candidate_pipeline`, `resume_score`, `evaluation_report`, `role_fit_score`
- Current coverage: Covered
- Missing answer gaps: Exact provenance for automated scores (product confirmation), privacy or contact options.

### 4. Candidate Assignment / Mapping / Matching
- Visible UI elements: Assign/match actions from vacancy and candidate views, bulk assignment workflows.
- What users may ask:
  - "How do I assign a candidate to a role?"
  - "How does candidate-role matching work?"
- Assistant intents: `candidate_job_mapping`, `explain_recommendation`
- Current coverage: Covered
- Missing answer gaps: Bulk mapping edge cases, match tuning (needs product confirmation).

### 5. Role Fit Score
- Visible UI elements: Role fit score on candidate/vacancy contexts and evaluation summaries.
- What users may ask:
  - "How is role fit score computed?"
  - "Should I trust the role fit score?"
- Assistant intents: `role_fit_score`
- Current coverage: Covered
- Missing answer gaps: Do not include internals; recommend product-approved phrasing for final messaging.

### 6. Resume Score
- Visible UI elements: Resume/ profile completeness and score.
- What users may ask:
  - "What does the resume score mean?"
- Assistant intents: `resume_score`
- Current coverage: Covered
- Missing answer gaps: Specific signals contributing to the score (needs product confirmation).

### 7. Manual Interview
- Visible UI elements: Schedule interview flow, calendar, participants.
- What users may ask:
  - "How do I schedule an interview?"
- Assistant intents: `schedule_interview`
- Current coverage: Covered
- Missing answer gaps: Calendar integration details and conflict handling (product confirmation).

### 8. Litio Auto Interview
- Visible UI elements: Litio interview / auto-screening action on candidate flows.
- What users may ask:
  - "How do I start a Litio interview?"
- Assistant intents: `litio_interview`
- Current coverage: Covered
- Missing answer gaps: Limitations and availability per customer (product confirmation).

### 9. Evaluation Report
- Visible UI elements: Evaluation summary, skill breakdown, evidence highlights, recommendation.
- What users may ask:
  - "How do I read the evaluation report?"
  - "What does this recommendation mean?"
- Assistant intents: `evaluation_report`, `explain_recommendation`
- Current coverage: Covered
- Missing answer gaps: More example-driven guidance for reviewers.

### 10. Red Flags / Integrity Signals
- Visible UI elements: Red flags list in evaluation, integrity alerts, off-screen events.
- What users may ask:
  - "What are red flags?"
  - "How should I act on an integrity signal?"
- Assistant intents: `evaluation_red_flags`
- Current coverage: Covered
- Missing answer gaps: Post-flag workflows and appeal paths (needs product confirmation).

### 11. Aptitude Test
- Visible UI elements: Aptitude assignment, status, score breakdown, integrity summary.
- What users may ask:
  - "How do I assign an aptitude test?"
  - "How do I interpret the aptitude result?"
- Assistant intents: `aptitude_test`
- Current coverage: Covered
- Missing answer gaps: Grading norms and passing thresholds (product confirmation).

### 12. Communication / Reminders / Status Updates
- Visible UI elements: Reminder actions, WhatsApp/SMS status indicators, notification UI.
- What users may ask:
  - "How do I send a reminder?"
  - "How do WhatsApp updates work?"
- Assistant intents: `send_reminder`, `communication_updates`
- Current coverage: Covered
- Missing answer gaps: Delivery retries, opt-out handling (product confirmation).

### 13. Candidate Dashboard / Candidate Side
- Visible UI elements: Candidate-facing profiles and public resume pages (if available).
- What users may ask:
  - "What does the candidate see?"
- Assistant intents: `candidate_pipeline`, `known_feature`
- Current coverage: Partially covered
- Missing answer gaps: Candidate-visible fields and privacy controls (needs product confirmation).

### 14. Settings / Profile / Account
- Visible UI elements: Company profile modal, account avatar and settings.
- What users may ask:
  - "How do I update company details?"
  - "How do I change my profile?"
- Assistant intents: (none deterministic)
- Current coverage: Missing / Needs product confirmation
- Missing answer gaps: Billing/contact/SSO behaviors require product confirmation.

### 15. Analytics / Reports
- Visible UI elements: Analytics tab, charts, export and filter controls.
- What users may ask:
  - "How do I view and export analytics?"
  - "What KPIs are available?"
- Assistant intents: `dashboard_analytics`
- Current coverage: Partially covered
- Missing answer gaps: Export formats, date range semantics, and custom metrics (needs product confirmation).

## Assistant Intent Map
| Intent Key | Covered Questions | Current Answer Source | Status | Notes |
|---|---|---|---|---|
| candidate_job_mapping | How to assign/map/tag candidate to a role | `DEFAULT_KNOWLEDGE` / contextual answers | Covered | Contextual response when vacancy present
| create_vacancy | How to post a job | `DEFAULT_KNOWLEDGE` | Covered | Basic steps
| role_fit_score | Explain role fit score | `DEFAULT_KNOWLEDGE` | Covered | High-level, avoids internals
| resume_score | Explain resume score | `DEFAULT_KNOWLEDGE` | Covered | High-level
| schedule_interview | Scheduling interviews | `DEFAULT_KNOWLEDGE` | Covered | Calendar integration not detailed
| litio_interview | Litio auto-interview | `DEFAULT_KNOWLEDGE` | Covered | Availability caveats need product confirmation
| aptitude_test | Aptitude tests assignment and review | `DEFAULT_KNOWLEDGE` | Covered | Integrity signals present
| evaluation_report | Read evaluation report | `DEFAULT_KNOWLEDGE` | Covered | Good coverage
| evaluation_red_flags | Red flags meaning and action | `DEFAULT_KNOWLEDGE` | Covered | Action guidance present
| send_reminder | How to send reminders | `DEFAULT_KNOWLEDGE` | Covered | Channel specifics limited
| communication_updates | WhatsApp/SMS status | `DEFAULT_KNOWLEDGE` | Covered | Delivery details limited
| ai_talent_pool | What is the AI Talent Pool | `DEFAULT_KNOWLEDGE` | Covered (new) | Added to DEFAULT_KNOWLEDGE
| dashboard_analytics | Dashboard analytics and exports | `DEFAULT_KNOWLEDGE` | Partially covered (new) | Added to DEFAULT_KNOWLEDGE; needs product confirmation for exports

## Suggested Prompt Library
Group by workflow (examples):
- Job posting: "How do I post a job?"; "Can I bulk import roles?"
- Candidate assignment: "How do I assign candidates to this vacancy?"; "How do I bulk assign shortlisted candidates?"
- Candidate profile: "Why is this resume score X?"; "What does the recommendation mean?"
- Interviews: "How do I schedule an interview?"; "How do I start a Litio interview?"
- Evaluation: "What are red flags?"; "How should I act on a low score?"
- Communication: "How do WhatsApp reminders work?"; "How do I send an SMS reminder?"
- Aptitude: "How do I assign an aptitude test?"; "How do I interpret the result?"
- Dashboard navigation: "What do KPIs mean?"; "How do I export analytics?"

## Missing / Phase 3 Backlog
- Per-KPI explanation and drill-down guidance (overview).
- Export formats and analytics custom metrics (product confirmation).
- Privacy and candidate-visible fields documentation (product confirmation).
- Billing, SSO, and account-level settings guidance.
- Deeper bulk-assignment edge cases and match-tuning controls.

---

File maintained as source-controlled knowledge map for Litio Assistant. Update when new dashboard features appear or assistant knowledge is extended.
