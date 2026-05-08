import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, Input, OnChanges, OnInit, SimpleChanges } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { catchError, of } from 'rxjs';
import { CandidateProfile } from '../app-modal/candidate-profile/candidate-profile';
import { RoleDetail } from '../app-modal/role-detail/role-detail';
import { getApiBaseUrl } from '../core/api-base';

interface TalentRole {
  id: number;
  name: string;
  location?: string;
  job_type?: string;
  experience_required?: string;
  applications?: number;
  hired?: number;
  inprogress?: number;
  open_positions?: number;
  status?: string;
  status_label?: string;
  company?: {
    display_name?: string;
    legal_name?: string;
  };
}

interface TalentRoleSummary {
  role_id: number;
  title: string;
  position?: string;
  location?: string;
  job_type?: string;
  experience_required?: string;
  required_skills?: string[];
  preferred_skills?: string[];
  company_name?: string;
  status?: string;
  status_label?: string;
}

interface TalentResult {
  candidate_id: number;
  interview_id?: number | null;
  name: string;
  email: string;
  title?: string;
  location?: string;
  experience_years?: number;
  role?: string;
  role_id?: number | null;
  recruiter?: string;
  current_stage?: string;
  latest_interview_date?: string;
  ai_score: number;
  ai_band: 'strong' | 'good' | 'watch';
  match_breakdown?: {
    skills?: number | string | null;
    experience?: number | string | null;
    role_similarity?: number | string | null;
    education?: number | string | null;
    location?: number | string | null;
  } | null;
  top_skills?: string[];
  matched_skills: string[];
  missing_skills: string[];
  explanations: string[];
}

interface TalentApiResponse {
  Success: boolean;
  Error?: string | null;
  Data?: {
    role_summary?: TalentRoleSummary;
    results?: TalentResult[];
  };
}

interface TalentCandidateView extends TalentResult {
  id: number;
  initials: string;
  matchScore: number;
  matchLabel: string;
  matchTone: 'strong' | 'good' | 'watch';
  statusLabel: string;
  dateLabel: string;
  roleDisplay: string;
  searchBlob: string;
  activityTime: number;
}

type TalentSortOption = 'best-match' | 'recent-activity' | 'candidate-name';
type TalentBreakdownKey = 'skills' | 'experience' | 'role_similarity' | 'education' | 'location';

@Component({
  selector: 'app-talent-pool',
  standalone: true,
  imports: [CommonModule, FormsModule, MatDialogModule],
  templateUrl: './talent-pool.html',
  styleUrl: './talent-pool.scss',
})
export class TalentPool implements OnInit, OnChanges {
  @Input() initialRoleId: string | null = null;
  @Input() roleCatalog: TalentRole[] = [];

  loading = false;
  errorMessage = '';
  searchTerm = '';
  roleSearchTerm = '';
  selectedRoleId = 'all';
  fitFilter: 'all' | 'strong' | 'good' | 'watch' = 'all';
  statusFilter = 'all';
  sortOption: TalentSortOption = 'best-match';
  currentPage = 1;
  readonly pageSize = 15;
  rolePickerOpen = false;

  private allRoles: TalentRole[] = [];
  private candidates: TalentCandidateView[] = [];
  private roleSearchBlurTimer: ReturnType<typeof setTimeout> | null = null;
  roleSummary: TalentRoleSummary | null = null;

  readonly fitFilters = [
    { key: 'all', label: 'All Fits' },
    { key: 'strong', label: 'Strong Fit' },
    { key: 'good', label: 'Good Fit' },
    { key: 'watch', label: 'Watchlist' },
  ] as const;

  constructor(private http: HttpClient, private dialog: MatDialog) {}

  ngOnInit(): void {
    this.selectedRoleId = this.initialRoleId || 'all';
    this.allRoles = this.mergeRoles([], this.roleCatalog);
    this.syncRoleSearchTerm();
    if (this.isRoleScoped) {
      this.loadTalentPool();
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['roleCatalog'] && Array.isArray(this.roleCatalog)) {
      this.allRoles = this.mergeRoles(this.allRoles, this.roleCatalog);
      this.syncRoleSearchTerm();
    }

    if (changes['initialRoleId'] && !changes['initialRoleId'].firstChange) {
      this.selectedRoleId = this.initialRoleId || 'all';
      this.syncRoleSearchTerm();
      this.resetPagination();
      this.loadTalentPool();
    }
  }

  get roles(): TalentRole[] {
    return this.allRoles;
  }

  get selectedRole(): TalentRole | null {
    if (this.selectedRoleId === 'all') {
      return null;
    }
    return this.allRoles.find((role) => String(role.id) === this.selectedRoleId) || null;
  }

  get isRoleScoped(): boolean {
    return this.selectedRoleId !== 'all';
  }

  get filteredRoleOptions(): TalentRole[] {
    const query = this.roleSearchTerm.trim().toLowerCase();
    if (query.length < 3) {
      return [];
    }

    return [...this.roles]
      .filter((role) => this.buildRoleSearchBlob(role).includes(query))
      .slice(0, 8);
  }

  get shouldShowRoleOptions(): boolean {
    return this.rolePickerOpen && this.roleSearchTerm.trim().length >= 3;
  }

  get shouldShowRoleEmpty(): boolean {
    return this.shouldShowRoleOptions && !this.filteredRoleOptions.length;
  }

  get filteredCandidates(): TalentCandidateView[] {
    const term = this.searchTerm.trim().toLowerCase();
    return this.candidates.filter((candidate) => {
      const matchesFit = this.fitFilter === 'all' || candidate.matchTone === this.fitFilter;
      if (!matchesFit) {
        return false;
      }

      const matchesStatus = this.statusFilter === 'all' || candidate.current_stage === this.statusFilter;
      if (!matchesStatus) {
        return false;
      }

      if (!term) {
        return true;
      }

      return candidate.searchBlob.includes(term);
    });
  }

  get sortedCandidates(): TalentCandidateView[] {
    const candidates = [...this.filteredCandidates];

    switch (this.sortOption) {
      case 'candidate-name':
        return candidates.sort((a, b) =>
          a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) ||
          b.matchScore - a.matchScore
        );
      case 'recent-activity':
        return candidates.sort((a, b) =>
          b.activityTime - a.activityTime ||
          b.matchScore - a.matchScore ||
          a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
        );
      case 'best-match':
      default:
        return candidates.sort((a, b) =>
          b.matchScore - a.matchScore ||
          b.activityTime - a.activityTime ||
          a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
        );
    }
  }

  get paginatedCandidates(): TalentCandidateView[] {
    const start = (this.currentPage - 1) * this.pageSize;
    return this.sortedCandidates.slice(start, start + this.pageSize);
  }

  get totalPages(): number {
    if (!this.sortedCandidates.length) {
      return 0;
    }
    return Math.ceil(this.sortedCandidates.length / this.pageSize);
  }

  get pageStart(): number {
    if (!this.totalCandidates) {
      return 0;
    }
    return (this.currentPage - 1) * this.pageSize + 1;
  }

  get pageEnd(): number {
    if (!this.totalCandidates) {
      return 0;
    }
    return Math.min(this.currentPage * this.pageSize, this.totalCandidates);
  }

  get visiblePageNumbers(): number[] {
    const total = this.totalPages;
    const start = Math.max(1, this.currentPage - 2);
    const end = Math.min(total, start + 4);
    const adjustedStart = Math.max(1, end - 4);
    const pages: number[] = [];

    for (let page = adjustedStart; page <= end; page += 1) {
      pages.push(page);
    }

    return pages;
  }

  get totalCandidates(): number {
    return this.filteredCandidates.length;
  }

  get strongFitCount(): number {
    return this.filteredCandidates.filter((candidate) => candidate.matchTone === 'strong').length;
  }

  get readyNowCount(): number {
    return this.filteredCandidates.filter((candidate) =>
      ['shortlisted', 'scheduled', 'assessment completed', 'hired', 'completed'].includes(candidate.current_stage || '')
    ).length;
  }

  get averageMatchScore(): number {
    if (!this.filteredCandidates.length) {
      return 0;
    }
    const total = this.filteredCandidates.reduce((sum, candidate) => sum + candidate.matchScore, 0);
    return Math.round(total / this.filteredCandidates.length);
  }

  get recruiterCoverageCount(): number {
    return new Set(
      this.filteredCandidates
        .map((candidate) => candidate.recruiter)
        .filter((value) => !!value && value !== 'Unassigned')
    ).size;
  }

  get spotlightStats(): Array<{ label: string; value: string; icon: string }> {
    if (!this.isRoleScoped || !this.selectedRole) {
      return [
        { label: 'Live Roles', value: String(this.roles.length), icon: 'ph-briefcase' },
        { label: 'Open Positions', value: String(this.roles.reduce((sum, role) => sum + Number(role.open_positions || 0), 0)), icon: 'ph-briefcase-metal' },
        { label: 'Strong Fits', value: String(this.strongFitCount), icon: 'ph-sparkle' },
      ];
    }

    return [
      { label: 'Open Positions', value: String(this.selectedRole.open_positions || 0), icon: 'ph-briefcase-metal' },
      { label: 'Required Skills', value: String(this.roleSummary?.required_skills?.length || 0), icon: 'ph-stack' },
      { label: 'Preferred Skills', value: String(this.roleSummary?.preferred_skills?.length || 0), icon: 'ph-star-four' },
    ];
  }

  get stageSummary(): Array<{ label: string; value: number; icon: string }> {
    const counts = new Map<string, number>();
    for (const candidate of this.filteredCandidates) {
      const stage = candidate.current_stage || 'unknown';
      counts.set(stage, (counts.get(stage) || 0) + 1);
    }

    const stageIconMap: Record<string, string> = {
      shortlisted: 'ph-check-circle',
      'offer made': 'ph-paper-plane-tilt',
      'offer accepted': 'ph-seal-check',
      'offer declined': 'ph-x-square',
      scheduled: 'ph-calendar-check',
      'assessment pending': 'ph-clipboard-text',
      'assessment completed': 'ph-checks',
      'auto screening scheduled': 'ph-robot',
      hired: 'ph-handshake',
      completed: 'ph-handshake',
      rejected: 'ph-x-circle',
      cancelled: 'ph-prohibit',
      unknown: 'ph-dots-three-outline',
    };

    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
      .map(([status, value]) => ({
        label: this.toTitleCase(status),
        value,
        icon: stageIconMap[status] || 'ph-dots-three-outline',
      }));
  }

  get recruiterLoad(): Array<{ recruiter: string; count: number }> {
    const counts = new Map<string, number>();
    for (const candidate of this.filteredCandidates) {
      const recruiter = candidate.recruiter || 'Unassigned';
      counts.set(recruiter, (counts.get(recruiter) || 0) + 1);
    }

    return Array.from(counts.entries())
      .map(([recruiter, count]) => ({ recruiter, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 4);
  }

  get requiredSkills(): string[] {
    return this.roleSummary?.required_skills || [];
  }

  get preferredSkills(): string[] {
    return this.roleSummary?.preferred_skills || [];
  }

  roleOptionLabel(role: TalentRole): string {
    return `${role.name} • ${role.id}`;
  }

  onRoleSearchInput(value: string): void {
    this.roleSearchTerm = value;
    this.rolePickerOpen = value.trim().length >= 3;
  }

  onRoleSearchFocus(): void {
    if (this.roleSearchBlurTimer) {
      clearTimeout(this.roleSearchBlurTimer);
      this.roleSearchBlurTimer = null;
    }
    this.rolePickerOpen = this.roleSearchTerm.trim().length >= 3;
  }

  onRoleSearchBlur(): void {
    this.roleSearchBlurTimer = setTimeout(() => {
      this.rolePickerOpen = false;

      const query = this.roleSearchTerm.trim();
      if (!query) {
        if (this.selectedRoleId !== 'all') {
          this.selectAllRoles();
        }
        return;
      }

      const exactMatch = this.roles.find((role) =>
        this.roleOptionLabel(role).toLowerCase() === query.toLowerCase()
      );

      if (exactMatch) {
        this.roleSearchTerm = this.roleOptionLabel(exactMatch);
        return;
      }

      this.syncRoleSearchTerm();
    }, 120);
  }

  selectRole(role: TalentRole): void {
    this.selectedRoleId = String(role.id);
    this.roleSearchTerm = this.roleOptionLabel(role);
    this.rolePickerOpen = false;
    this.onRoleChange();
  }

  selectAllRoles(): void {
    this.selectedRoleId = 'all';
    this.roleSearchTerm = '';
    this.rolePickerOpen = false;
    this.onRoleChange();
  }

  clearRoleSearch(): void {
    this.selectAllRoles();
  }

  stageIcon(status: string | null | undefined): string {
    const normalized = this.normalizeStatus(status || '');

    const stageIconMap: Record<string, string> = {
      shortlisted: 'ph-check-circle',
      'offer made': 'ph-paper-plane-tilt',
      'offer accepted': 'ph-seal-check',
      'offer declined': 'ph-x-square',
      scheduled: 'ph-calendar-check',
      'assessment pending': 'ph-hourglass-medium',
      'assessment completed': 'ph-checks',
      'auto screening scheduled': 'ph-robot',
      hired: 'ph-handshake',
      completed: 'ph-handshake',
      rejected: 'ph-x-circle',
      cancelled: 'ph-prohibit',
      unknown: 'ph-dots-three-outline',
    };

    return stageIconMap[normalized || 'unknown'] || 'ph-dots-three-outline';
  }

  onRoleChange(): void {
    this.errorMessage = '';
    this.syncRoleSearchTerm();
    this.resetPagination();
    if (!this.isRoleScoped) {
      this.candidates = [];
      this.roleSummary = null;
      return;
    }
    this.loadTalentPool();
  }

  onSearchChange(): void {
    this.resetPagination();
  }

  onStatusChange(): void {
    this.resetPagination();
  }

  onSortChange(): void {
    this.resetPagination();
  }

  setFitFilter(filter: 'all' | 'strong' | 'good' | 'watch'): void {
    if (this.fitFilter === filter) {
      return;
    }
    this.fitFilter = filter;
    this.resetPagination();
  }

  resetFilters(): void {
    this.searchTerm = '';
    this.roleSearchTerm = '';
    this.fitFilter = 'all';
    this.statusFilter = 'all';
    this.sortOption = 'best-match';
    this.selectedRoleId = this.initialRoleId || 'all';
    this.syncRoleSearchTerm();
    this.resetPagination();
    this.onRoleChange();
  }

  goToPage(page: number): void {
    const nextPage = Math.min(Math.max(1, page), this.totalPages);
    this.currentPage = nextPage;
  }

  nextPage(): void {
    this.goToPage(this.currentPage + 1);
  }

  prevPage(): void {
    this.goToPage(this.currentPage - 1);
  }

  resetPagination(): void {
    this.currentPage = 1;
  }

  visibleMissingSkills(candidate: TalentCandidateView): string[] {
    return (candidate.missing_skills || []).slice(0, 3);
  }

  remainingMissingSkillCount(candidate: TalentCandidateView): number {
    return Math.max(0, (candidate.missing_skills || []).length - 3);
  }

  displayMatchedSkills(candidate: TalentCandidateView): string[] {
    if (Array.isArray(candidate.matched_skills) && candidate.matched_skills.length) {
      return candidate.matched_skills;
    }
    return Array.isArray(candidate.top_skills) ? candidate.top_skills : [];
  }

  hasMatchBreakdown(candidate: TalentCandidateView): boolean {
    return this.getMatchBreakdownRows(candidate).length > 0;
  }

  getMatchBreakdownRows(candidate: TalentCandidateView): Array<{ key: TalentBreakdownKey; label: string; value: number }> {
    const breakdown = candidate.match_breakdown;
    if (!breakdown) {
      return [];
    }

    const rowMap: Array<{ key: TalentBreakdownKey; label: string }> = [
      { key: 'skills', label: 'Skill Match' },
      { key: 'experience', label: 'Experience Fit' },
      { key: 'role_similarity', label: 'Role Similarity' },
      { key: 'education', label: 'Education Fit' },
      { key: 'location', label: 'Location Match' },
    ];

    return rowMap
      .map(({ key, label }) => ({
        key,
        label,
        value: this.normalizeBreakdownValue(breakdown[key]),
      }))
      .filter((row) => row.value >= 0);
  }

  breakdownBarWidth(value: number): number {
    return Math.max(0, Math.min(100, Math.round(value || 0)));
  }

  openCandidate(candidate: TalentCandidateView): void {
    this.dialog.open(CandidateProfile, {
      width: '95vw',
      maxWidth: '980px',
      maxHeight: '92vh',
      panelClass: 'candidate-profile-dialog',
      autoFocus: false,
      data: { candidate: { ...candidate, id: candidate.id, role: candidate.role, role_id: candidate.role_id, status: candidate.current_stage } }
    });
  }

  openRole(roleId: number | null | undefined): void {
    if (!roleId) {
      return;
    }
    this.dialog.open(RoleDetail, {
      width: 'min(1120px, 96vw)',
      maxWidth: '96vw',
      maxHeight: '92vh',
      panelClass: 'role-detail-dialog',
      autoFocus: false,
      data: { role_id: roleId }
    });
  }

  trackByCandidate(index: number, candidate: TalentCandidateView): number {
    return candidate.id || index;
  }

  private loadTalentPool(): void {
    if (!this.isRoleScoped) {
      this.loading = false;
      this.candidates = [];
      this.roleSummary = null;
      return;
    }

    this.loading = true;
    this.errorMessage = '';

    this.http.post<TalentApiResponse>(`${getApiBaseUrl()}/api/ai-talent-pool/match`, {
      role_id: Number(this.selectedRoleId),
      top_k: 60,
    })
      .pipe(
        catchError(() => of({
          Success: false,
          Error: 'Unable to load AI talent matches right now.',
        } as TalentApiResponse))
      )
      .subscribe((response) => {
        this.loading = false;
        if (!response?.Success || !response.Data) {
          this.errorMessage = response?.Error || 'Unable to load AI talent matches right now.';
          this.candidates = [];
          this.roleSummary = null;
          this.resetPagination();
          return;
        }

        this.roleSummary = response.Data.role_summary || null;
        this.candidates = Array.isArray(response.Data.results)
          ? response.Data.results.map((candidate) => this.decorateCandidate(candidate))
          : [];
        this.resetPagination();
      });
  }

  private decorateCandidate(candidate: TalentResult): TalentCandidateView {
    const currentStage = this.normalizeStatus(candidate.current_stage || '');
    return {
      ...candidate,
      id: candidate.interview_id || candidate.candidate_id,
      initials: this.getInitials(candidate.name),
      matchScore: candidate.ai_score,
      matchLabel: this.matchLabel(candidate.ai_band),
      matchTone: candidate.ai_band,
      statusLabel: this.toTitleCase(currentStage || 'unknown'),
      dateLabel: this.formatDate(candidate.latest_interview_date || ''),
      roleDisplay: candidate.role_id ? `${candidate.role || 'Role pending'} • ${candidate.role_id}` : (candidate.role || 'Role pending'),
      searchBlob: [
        candidate.name,
        candidate.email,
        candidate.title,
        candidate.role,
        candidate.recruiter,
        currentStage,
        ...(candidate.top_skills || []),
        ...(candidate.matched_skills || []),
        ...(candidate.missing_skills || []),
        ...(candidate.explanations || []),
      ].join(' ').toLowerCase(),
      activityTime: this.toTimestamp(candidate.latest_interview_date || ''),
      current_stage: currentStage,
    };
  }

  private mergeRoles(primary: TalentRole[], secondary: TalentRole[]): TalentRole[] {
    const roleMap = new Map<string, TalentRole>();
    for (const role of [...(primary || []), ...(secondary || [])]) {
      if (!role?.id) {
        continue;
      }
      roleMap.set(String(role.id), { ...roleMap.get(String(role.id)), ...role });
    }
    return Array.from(roleMap.values());
  }

  private syncRoleSearchTerm(): void {
    this.roleSearchTerm = this.selectedRole ? this.roleOptionLabel(this.selectedRole) : '';
  }

  private buildRoleSearchBlob(role: TalentRole): string {
    return [
      role.name,
      role.id,
      role.location,
      role.job_type,
      role.company?.display_name,
      role.company?.legal_name,
    ].join(' ').toLowerCase();
  }

  private normalizeStatus(value: string): string {
    return (value || '').trim().toLowerCase().replace(/_/g, ' ');
  }

  private toTitleCase(value: string): string {
    return (value || '')
      .split(' ')
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  private getInitials(name: string): string {
    const parts = (name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) {
      return 'NA';
    }
    if (parts.length === 1) {
      return parts[0].slice(0, 2).toUpperCase();
    }
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }

  private formatDate(value: string): string {
    if (!value) {
      return 'No recent activity';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return 'No recent activity';
    }
    return parsed.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }

  private toTimestamp(value: string): number {
    if (!value) {
      return 0;
    }
    const parsed = new Date(value).getTime();
    return Number.isNaN(parsed) ? 0 : parsed;
  }

  private matchLabel(band: 'strong' | 'good' | 'watch'): string {
    switch (band) {
      case 'strong':
        return 'Strong fit';
      case 'good':
        return 'Good fit';
      default:
        return 'Watchlist';
    }
  }

  private normalizeBreakdownValue(value: number | string | null | undefined): number {
    if (value === null || value === undefined || value === '') {
      return -1;
    }

    const parsed = typeof value === 'string' ? Number(value) : value;
    if (!Number.isFinite(parsed)) {
      return -1;
    }

    const normalized = parsed > 0 && parsed <= 1 ? parsed * 100 : parsed;
    return Math.max(0, Math.min(100, Math.round(normalized)));
  }
}
