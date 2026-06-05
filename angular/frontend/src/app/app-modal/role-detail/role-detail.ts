import { Component, Inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { HttpClient } from '@angular/common/http';  // Import HttpClient
import { catchError, of, timeout } from 'rxjs';

interface SummaryCard {
  key: string;
  label: string;
  icon: string;
  value: string | number;
  helper: string;
  tone?: string;
}

interface DetailHighlight {
  label: string;
  value: string;
  icon: string;
  helper: string;
  tone?: string;
}

interface DetailRow {
  label: string;
  value: string | number;
  icon: string;
}

@Component({
  selector: 'app-role-detail',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './role-detail.html',
  styleUrl: './role-detail.scss'
})
export class RoleDetail {
  constructor(
    private http: HttpClient,
    public dialogRef: MatDialogRef<RoleDetail>,
    @Inject(MAT_DIALOG_DATA) public data: any
  ) {}

  loading: boolean = false;
  errorMessage = '';
  roleDetails: any = '';
  totalVacancies: number = 0;
  appliedCandidates: number = 0;
  shortlistedCandidates: number = 0;
  hiredCandidates: number = 0;
  description: string = '';
  roleStatus = '';
  roleDate = '';
  jobType = '';
  location = '';
  salaryRange = '';
  experienceRequired = '';
  companyName = '';
  adminName = '';
  recruiters: string[] = [];
  descriptionExpanded = false;
  daysOpenValue = 0;
  fulfillmentRingBackground = 'conic-gradient(#20c8ff 0 0%, rgba(27, 61, 104, 0.72) 0% 100%)';
  roleDescriptionDisplay = 'No role description has been published for this requisition.';
  readonly summaryCards: SummaryCard[] = [
    { key: 'vacancies', label: 'Approved Headcount', icon: 'ph-briefcase-metal', value: 0, helper: 'Total Vacancies', tone: 'blue' },
    { key: 'applied', label: 'Applicants Received', icon: 'ph-users-three', value: 0, helper: 'Total Applicants', tone: 'purple' },
    { key: 'inProgress', label: 'Active Pipeline', icon: 'ph-path', value: 0, helper: 'In Progress', tone: 'cyan' },
    { key: 'hired', label: 'Closed Hires', icon: 'ph-handshake', value: 0, helper: 'Hired', tone: 'green' },
    { key: 'conversion', label: 'Conversion Rate', icon: 'ph-funnel', value: '0%', helper: 'Applicants to Hire', tone: 'amber' },
    { key: 'daysOpen', label: 'Time to Fill', icon: 'ph-clock', value: 0, helper: 'Days Open', tone: 'pink' },
  ];
  detailHighlights: DetailHighlight[] = [];
  requisitionRows: DetailRow[] = [];
  ownershipRows: DetailRow[] = [];

  get roleTitleWithId(): string {
    const roleName = (this.roleDetails || '').toString().trim();
    const id = (this.data?.role_id ?? '').toString().trim();
    if (!roleName) return id || 'Role Details';
    return id ? `${roleName} - ${id}` : roleName;
  }

  get initialRoleLoading(): boolean {
    return this.loading && !this.roleDetails && !this.errorMessage;
  }

  get roleId(): string {
    return (this.data?.role_id ?? '').toString().trim();
  }

  private calculateDaysOpen(): number {
    if (!this.roleDate) return 0;
    const createdAt = new Date(this.roleDate);
    if (Number.isNaN(createdAt.getTime())) return 0;
    const elapsed = Date.now() - createdAt.getTime();
    return Math.max(Math.ceil(elapsed / 86400000), 0);
  }

  private getRoleDescriptionDisplay(): string {
    if (!this.description) return 'No role description has been published for this requisition.';
    if (this.descriptionExpanded || this.description.length <= 260) return this.description;
    return `${this.description.slice(0, 260).trim()}...`;
  }

  get hasLongDescription(): boolean {
    return this.description.length > 260;
  }

  get recruiterSummary(): string {
    if (this.recruiters.length) return this.recruiters.join(', ');
    return this.adminName || 'TBD';
  }

  closeModal() {
    this.dialogRef.close();
  }

  done(): void {
    this.closeModal();
  }

  openRolePage(): void {
    const roleParam = this.roleId ? `?role=${encodeURIComponent(this.roleId)}` : '';
    window.open(`/dashboard/jobs${roleParam}`, '_blank', 'noopener');
  }

  toggleFullDescription(): void {
    this.descriptionExpanded = !this.descriptionExpanded;
    this.roleDescriptionDisplay = this.getRoleDescriptionDisplay();
  }

  ngOnInit(): void {
    this.fetchRoleDetails(this.data.role_id);
  }
  fetchRoleDetails(role_id: any) {
    this.loading = true;
    this.errorMessage = '';
        let port_number = ''
        if(window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"){
          port_number = '8080'
        }
        const apiBaseUrl = `${window.location.protocol}//${window.location.hostname}:${port_number}`;
        this.http.get(apiBaseUrl + '/get-role-data/' + role_id)
          .pipe(
            timeout(12000),
            catchError(error => {
              console.error('Error fetching data', error);
              this.loading = false;
              this.errorMessage = 'Unable to load role details.';
              return of([]); // Return empty array on error
            })
          )
          .subscribe((response: any) => {
            this.loading = false;
            if (response && response?.Success && response.RoleData) {
              const role = response.RoleData;
              this.roleDetails = role.name || role.role;
              this.description = role.description || '';
              this.totalVacancies = this.extractNumber(role.position);
              this.appliedCandidates = this.extractNumber(role.applications);
              this.shortlistedCandidates = this.extractNumber(role.inprogress);
              this.hiredCandidates = this.extractNumber(role.hired);
              this.roleStatus = (role.status || '').toString();
              this.roleDate = role.date || '';
              this.jobType = role.job_type || '';
              this.location = role.location || '';
              this.salaryRange = role.salary_range || '';
              this.experienceRequired = role.experience_required || '';
              this.companyName = role.company?.display_name || role.company?.legal_name || '';
              this.adminName = role.admin_name || '';
              this.recruiters = Array.isArray(role.recruiters) ? role.recruiters.filter(Boolean) : [];
              this.descriptionExpanded = false;
              this.updatePresentationState();
            } else {
              this.errorMessage = 'No role data found.';
            }
          });
  }

  get openPositions(): number {
    return Math.max(this.totalVacancies - this.hiredCandidates, 0);
  }

  get fulfillmentRate(): number {
    if (!this.totalVacancies) return 0;
    return Math.min(100, Math.round((this.hiredCandidates / this.totalVacancies) * 100));
  }

  get inProgressRate(): number {
    if (!this.appliedCandidates) return 0;
    return Math.min(100, Math.round((this.shortlistedCandidates / this.appliedCandidates) * 100));
  }

  get conversionRate(): number {
    if (!this.appliedCandidates) return 0;
    return Math.min(100, Math.round((this.hiredCandidates / this.appliedCandidates) * 100));
  }

  get urgencyLabel(): string {
    if (!this.openPositions) return 'Hiring target met';
    if (this.appliedCandidates < this.totalVacancies) return 'Pipeline needs immediate attention';
    if (this.fulfillmentRate >= 60) return 'Delivery on track';
    return 'Open positions still require coverage';
  }

  get roleStatusLabel(): string {
    const status = this.roleStatus.trim().toLowerCase();
    if (!status) return 'Status pending';
    if (status === 'active') return 'Active requisition';
    if (status === 'closed') return 'Closed requisition';
    return `${this.roleStatus} requisition`;
  }

  private updatePresentationState(): void {
    this.summaryCards[0].value = this.totalVacancies;
    this.summaryCards[1].value = this.appliedCandidates;
    this.summaryCards[2].value = this.shortlistedCandidates;
    this.summaryCards[3].value = this.hiredCandidates;
    this.summaryCards[4].value = `${this.conversionRate}%`;
    this.daysOpenValue = this.calculateDaysOpen();
    this.summaryCards[5].value = this.daysOpenValue;
    this.fulfillmentRingBackground = `conic-gradient(#20c8ff 0 ${this.fulfillmentRate}%, rgba(27, 61, 104, 0.72) ${this.fulfillmentRate}% 100%)`;
    this.roleDescriptionDisplay = this.getRoleDescriptionDisplay();

    this.detailHighlights = [
      {
        label: 'Employment Type',
        value: this.jobType || 'Not specified',
        icon: 'ph-bag-simple',
        helper: 'Contract structure for the role',
        tone: 'blue',
      },
      {
        label: 'Location',
        value: this.location || 'Not specified',
        icon: 'ph-map-pin',
        helper: 'Primary delivery or work location',
        tone: 'purple',
      },
      {
        label: 'Compensation',
        value: this.salaryRange || 'Not specified',
        icon: 'ph-currency-circle-dollar',
        helper: 'Published salary guidance',
        tone: 'green',
      },
      {
        label: 'Experience',
        value: this.experienceRequired || 'Not specified',
        icon: 'ph-chart-line-up',
        helper: 'Target experience range',
        tone: 'amber',
      },
    ];

    this.requisitionRows = [
      { label: 'Requisition Status', value: this.roleStatus || 'Pending', icon: 'ph-clipboard-text' },
      { label: 'Created On', value: this.roleDate || 'Not available', icon: 'ph-calendar-blank' },
      { label: 'Requested Headcount', value: this.totalVacancies || 0, icon: 'ph-users-three' },
      { label: 'Open Positions', value: this.openPositions, icon: 'ph-briefcase' },
      { label: 'Days Open', value: `${this.daysOpenValue} Days`, icon: 'ph-clock' },
    ];

    this.ownershipRows = [
      { label: 'Hiring Manager', value: this.recruiterSummary, icon: 'ph-user-circle' },
      { label: 'Evaluator', value: 'TBD', icon: 'ph-identification-badge' },
    ];
  }

  private extractNumber(value: any): number {
    if (Array.isArray(value)) return Number(value[0] || 0);
    return Number(value || 0);
  }

}
