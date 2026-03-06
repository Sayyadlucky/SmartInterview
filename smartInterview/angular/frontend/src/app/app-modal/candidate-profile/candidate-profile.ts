import { Component, Inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { catchError, of } from 'rxjs';

interface CandidateData {
  id: number;
  name: string;
  email: string;
  recruiter: string;
  role: string;
  role_id?: number | null;
  status: string;
  score?: number | null;
  date: string;
}

@Component({
  selector: 'app-candidate-profile',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './candidate-profile.html',
  styleUrl: './candidate-profile.scss'
})
export class CandidateProfile {
  candidate: CandidateData;
  loading = false;
  errorMessage = '';
  statusActions: Array<{ key: string; label: string }> = [];
  readonly resumeProfile = {
    name: 'ALTAMASH HASAN',
    email: 'hasanaltamash1993@gmail.com',
    phone: '+91-9307348633',
    location: 'Pune, Maharashtra 411041',
    objective: 'A motivated individual with indepth knowledge of Python, Django and development tools, seeking a position in a growth-oriented company where I can contribute to business outcomes while continuously growing technical skills.'
  };
  readonly professionalSummary: string[] = [
    'Around 6 years of professional experience in Python, Django, Flask, HTML, CSS, JQuery, JSON and MySQL.',
    'Worked on frontend technologies including HTML, CSS, Bootstrap, JavaScript and Angular.',
    'Quick at identifying errors and debugging code with clear root-cause analysis.',
    'Worked on Agile methodology and CI/CD pipelines.',
    'Developed REST APIs using Django REST Framework.',
    'Good understanding of OOP, Python modules, generators and decorators.',
    'Hands-on experience in coding, unit testing and code standardization.',
    'Used GIT for version control and collaborative development.',
    'Strong analytical/problem-solving mindset with proactive ownership.',
    'Experienced in team collaboration and on-time delivery.'
  ];
  readonly workHistory: Array<{ duration: string; title: string; company: string; details: string }> = [
    {
      duration: 'Feb 2023 - Current',
      title: 'Software Engineer',
      company: 'IRIS Software Private LTD - Pune (Remote), Client: Bank Of Montreal',
      details: 'Role: Fullstack Developer. Environment: Python, Django, Django REST Framework, MySQL, Angular. Worked on API-based solutions, Angular module development, platform monitoring, performance tuning, testing/debugging and cross-functional delivery.'
    },
    {
      duration: 'Aug 2019 - Aug 2022',
      title: 'Software Developer',
      company: 'Bajaj Finance LTD - Pune',
      details: 'Role: Python Developer. Environment: Python, Django, MySQL. Modernized legacy code, shipped desktop/mobile web applications, supported production releases and collaborated in lean development cycles.'
    },
    {
      duration: 'Jan 2016 - Apr 2017',
      title: 'Associate Software Engineer',
      company: 'Accenture Solutions PVT LTD - Pune',
      details: 'Role: Associate Software Developer. Environment: Automation Anywhere. Developed internal automation tools, debugged platform issues and documented technical workflows.'
    }
  ];
  readonly technicalExpertise = {
    languages: 'Python 3.x, Angular, C, C++, .NET, Java',
    os: 'Windows, Linux',
    database: 'MySQL, SQL',
    framework: 'Django, Flask',
    web: 'HTML5, CSS, Bootstrap, JavaScript, REST API, Angular',
    tools: 'PyCharm, VS Code, Postman, Thonny'
  };
  readonly education: string[] = [
    'MBA - Pune University, Pune',
    'Bachelor of Science (Computer Science) - SRTM University, Nanded'
  ];

  constructor(
    private http: HttpClient,
    public dialogRef: MatDialogRef<CandidateProfile>,
    @Inject(MAT_DIALOG_DATA) public data: { candidate: CandidateData }
  ) {
    this.candidate = { ...data.candidate };
    this.statusActions = this.getStatusActions(this.candidate.status);
  }

  get initials(): string {
    const parts = (this.candidate?.name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return 'NA';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }

  get formattedStatus(): string {
    return this.candidate.status.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
  }

  close(): void {
    this.dialogRef.close(null);
  }

  openRole(): void {
    this.dialogRef.close({ action: 'openRole', candidate: this.candidate });
  }

  changeStatus(next: string): void {
    this.loading = true;
    this.errorMessage = '';
    const apiBaseUrl = this.getApiBaseUrl();
    const formData = new FormData();
    formData.append('candidateId', String(this.candidate.id));
    formData.append('newStatus', next);

    this.http.post<{ Success: boolean; Error?: string }>(`${apiBaseUrl}/update-candidate-status/`, formData)
      .pipe(
        catchError((error) => {
          console.error('Error updating candidate status', error);
          this.loading = false;
          this.errorMessage = 'Unable to update status. Please try again.';
          return of({ Success: false, Error: 'Request failed' });
        })
      )
      .subscribe((response) => {
        if (!response?.Success) {
          this.errorMessage = response?.Error || 'Unable to update status.';
          this.loading = false;
          return;
        }

        this.candidate.status = next;
        this.statusActions = this.getStatusActions(this.candidate.status);
        this.loading = false;
      });
  }

  saveAndClose(): void {
    this.dialogRef.close({ action: 'updated', candidate: this.candidate });
  }

  private normalizeStatus(value: string): string {
    return (value || '')
      .toString()
      .trim()
      .toLowerCase()
      .replace(/_/g, ' ')
      .replace(/\s+/g, ' ')
      .replace(/assesment/g, 'assessment');
  }

  private getStatusActions(statusRaw: string): Array<{ key: string; label: string }> {
    const status = this.normalizeStatus(statusRaw);

    const transitions: Record<string, Array<{ key: string; label: string }>> = {
      'scheduled': [
        { key: 'shortlisted', label: 'Shortlist' },
        { key: 'rejected', label: 'Disqualify' },
        { key: 'cancelled', label: 'Cancel' }
      ],
      'shortlisted': [
        { key: 'completed', label: 'Mark Hired' },
        { key: 'rejected', label: 'Disqualify' },
        { key: 'cancelled', label: 'Cancel' }
      ],
      'assessment pending': [
        { key: 'scheduled', label: 'Move to Scheduled' },
        { key: 'rejected', label: 'Disqualify' },
        { key: 'cancelled', label: 'Cancel' }
      ],
      'assessment completed': [
        { key: 'scheduled', label: 'Move to Scheduled' },
        { key: 'shortlisted', label: 'Shortlist' },
        { key: 'rejected', label: 'Disqualify' }
      ],
      'auto screening scheduled': [
        { key: 'assessment_pending', label: 'Move to Assessment' },
        { key: 'rejected', label: 'Disqualify' }
      ],
      'rejected': [
        { key: 'assessment_pending', label: 'Reopen' }
      ],
      'cancelled': [
        { key: 'assessment_pending', label: 'Reopen' }
      ],
      'completed': []
    };

    return transitions[status] || [];
  }

  private getApiBaseUrl(): string {
    let portNumber = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      portNumber = '8000';
    }
    return `${window.location.protocol}//${window.location.hostname}:${portNumber}`;
  }
}
