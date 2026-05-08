import { AfterViewInit, ChangeDetectionStrategy, ChangeDetectorRef, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpParams } from '@angular/common/http';
import { catchError, of } from 'rxjs';
import { Chart, registerables } from 'chart.js';

Chart.register(...registerables);

type AlertSeverity = 'high' | 'medium' | 'low';
type SignalSeverity = 'critical' | 'warning' | 'positive' | 'info';
type SignalActionType = 'status' | 'role' | 'recruiter' | 'month' | 'section' | 'clear';

interface ActivityResponse {
  Success: boolean;
  Error?: string | null;
  Data?: {
    summary?: {
      total_interviews?: number;
      upcoming?: number;
      hired?: number;
      active_recruiters?: number;
      open_roles?: number;
      last_30_days?: number;
      hire_rate?: number;
    };
    trend?: {
      title?: string;
      labels?: string[];
      interviews?: number[];
      hired?: number[];
    };
    status_split?: Record<string, number>;
    recruiter_breakdown?: Array<{ recruiter_id?: number; name: string; count: number }>;
    role_breakdown?: Array<{ role_id?: number; role: string; count: number; hired: number }>;
    recent_activity?: Array<{ id: number; title: string; meta: string; date: string }>;
    upcoming_list?: Array<{ id: number; candidate: string; role: string; date: string }>;
    sla_alerts?: Array<{ type: string; title: string; count: number; severity: AlertSeverity; description: string }>;
    stage_movement?: Array<{ stage: string; current: number; previous: number; delta: number }>;
    dropoff_reasons?: Array<{ reason: string; count: number }>;
    insights?: string[];
    response_time?: {
      avg_hours?: number;
      median_hours?: number;
      samples?: number;
      by_recruiter?: Array<{ recruiter_id?: number; name: string; avg_hours: number; count: number }>;
    };
    outcome_quality?: {
      evaluated?: number;
      hired?: number;
      shortlisted?: number;
      rejected?: number;
      score_bands?: Record<string, number>;
      scored_count?: number;
      quality_by_role?: Array<{ role: string; total: number; positive: number; pass_rate: number }>;
    };
    productivity?: {
      daily?: Array<{ key: string; label: string; total: number; hired: number; scheduled: number }>;
      current_week_total?: number;
      previous_week_total?: number;
      current_week_hired?: number;
    };
    upcoming_load_heat?: {
      slots?: string[];
      days?: Array<{ key: string; label: string; cells: Record<string, number> }>;
      max_cell?: number;
      total_scheduled?: number;
    };
    role_risk_score?: Array<{
      role_id: number;
      role: string;
      target: number;
      filled: number;
      remaining: number;
      pipeline: number;
      progress_pct: number;
      risk_score: number;
      severity: AlertSeverity;
      age_days: number;
    }>;
    target_vs_actual?: {
      target_total?: number;
      actual_total?: number;
      gap?: number;
      progress_pct?: number;
      labels?: string[];
      keys?: string[];
      target_series?: number[];
      actual_series?: number[];
    };
    recycled_summary?: {
      total_recycled?: number;
      reopened?: number;
      list?: Array<{ candidate: string; interviews: number; roles: string[]; primary_role_id?: number | null; latest_status: string; reopened: boolean }>;
    };
    export_meta?: {
      generated_at?: string;
      filters?: {
        recruiter?: string;
        role?: string;
        start_date?: string;
        end_date?: string;
      };
    };
    filter_options?: {
      recruiters?: Array<{ id: number; name: string }>;
      roles?: Array<{ id: number; name: string }>;
      statuses?: Array<{ value: string; label: string }>;
    };
  };
}

interface SummaryCard {
  label: string;
  icon: string;
  value: string;
  helper: string;
  tone?: SignalSeverity;
}

interface SignalAction {
  type: SignalActionType;
  value?: string | number;
}

interface ActivitySignal {
  id: string;
  severity: SignalSeverity;
  title: string;
  message: string;
  metric?: string;
  icon: string;
  action?: SignalAction;
  ctaLabel?: string;
}

interface RecommendedAction {
  id: string;
  label: string;
  description: string;
  icon: string;
  severity: SignalSeverity;
  action?: SignalAction;
}

@Component({
  selector: 'app-activity',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './activity.html',
  styleUrl: './activity.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Activity implements OnInit, AfterViewInit, OnDestroy {
  loading = false;
  errorMessage = '';

  summary = {
    total_interviews: 0,
    upcoming: 0,
    hired: 0,
    active_recruiters: 0,
    open_roles: 0,
    last_30_days: 0,
    hire_rate: 0,
  };

  trend = {
    title: 'Interview Trend (Last 6 Months)',
    labels: [] as string[],
    interviews: [] as number[],
    hired: [] as number[],
  };

  statusSplit: Array<{ label: string; value: number; color: string }> = [];
  recruiterBreakdown: Array<{ recruiter_id?: number; name: string; count: number }> = [];
  roleBreakdown: Array<{ role_id?: number; role: string; count: number; hired: number }> = [];
  recentActivity: Array<{ id: number; title: string; meta: string; date: string }> = [];
  upcomingList: Array<{ id: number; candidate: string; role: string; date: string }> = [];
  slaAlerts: Array<{ type: string; title: string; count: number; severity: AlertSeverity; description: string }> = [];
  stageMovement: Array<{ stage: string; current: number; previous: number; delta: number }> = [];
  dropoffReasons: Array<{ reason: string; count: number }> = [];
  insights: string[] = [];
  responseTime = {
    avg_hours: 0,
    median_hours: 0,
    samples: 0,
    by_recruiter: [] as Array<{ recruiter_id?: number; name: string; avg_hours: number; count: number }>,
  };
  outcomeQuality = {
    evaluated: 0,
    hired: 0,
    shortlisted: 0,
    rejected: 0,
    score_bands: {} as Record<string, number>,
    scored_count: 0,
    quality_by_role: [] as Array<{ role: string; total: number; positive: number; pass_rate: number }>,
  };
  productivity = {
    daily: [] as Array<{ key: string; label: string; total: number; hired: number; scheduled: number }>,
    current_week_total: 0,
    previous_week_total: 0,
    current_week_hired: 0,
  };
  upcomingLoadHeat = {
    slots: [] as string[],
    days: [] as Array<{ key: string; label: string; cells: Record<string, number> }>,
    max_cell: 0,
    total_scheduled: 0,
  };
  roleRiskScore: Array<{
    role_id: number;
    role: string;
    target: number;
    filled: number;
    remaining: number;
    pipeline: number;
    progress_pct: number;
    risk_score: number;
    severity: AlertSeverity;
    age_days: number;
  }> = [];
  targetVsActual = {
    target_total: 0,
    actual_total: 0,
    gap: 0,
    progress_pct: 0,
    labels: [] as string[],
    keys: [] as string[],
    target_series: [] as number[],
    actual_series: [] as number[],
  };
  recycledSummary = {
    total_recycled: 0,
    reopened: 0,
    list: [] as Array<{ candidate: string; interviews: number; roles: string[]; primary_role_id?: number | null; latest_status: string; reopened: boolean }>,
  };
  exportMeta = {
    generated_at: '',
    filters: {
      recruiter: 'all',
      role: 'all',
      start_date: '',
      end_date: '',
    },
  };

  summaryCards: SummaryCard[] = [];
  aiSignals: ActivitySignal[] = [];
  attentionSignals: ActivitySignal[] = [];
  positiveSignals: ActivitySignal[] = [];
  recommendedActions: RecommendedAction[] = [];
  scoreBandRowsData: Array<{ label: string; value: number }> = [];
  aiHeadlineText = 'AI activity monitor is ready.';
  aiAttentionCountValue = 0;
  aiPositiveCountValue = 0;
  maxRecruiterCountValue = 1;
  maxDailyTotalValue = 1;
  weeklyDeltaValue = 0;

  recruiterOptions: Array<{ id: number; name: string }> = [];
  roleOptions: Array<{ id: number; name: string }> = [];
  statusOptions: Array<{ value: string; label: string }> = [{ value: 'all', label: 'All Statuses' }];
  filteredRecruiterOptions: Array<{ id: string; name: string }> = [];
  filteredRoleOptions: Array<{ id: string; name: string }> = [];
  selectedRecruiter = 'all';
  selectedRole = 'all';
  selectedStatus = 'all';
  recruiterQuery = 'All Recruiters';
  roleQuery = 'All Roles';
  showRecruiterMenu = false;
  showRoleMenu = false;
  startDate = '';
  endDate = '';
  dateRangeError = '';

  @ViewChild('trendCanvas', { static: false }) trendCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('statusCanvas', { static: false }) statusCanvas?: ElementRef<HTMLCanvasElement>;

  private trendChart?: Chart;
  private statusChart?: Chart;
  private filterTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private chartFrameId: number | null = null;
  private viewInitialized = false;
  private readonly statusUpdateListener = () => this.loadActivityData();

  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) {}

  ngOnInit(): void {
    window.addEventListener('candidate-status-updated', this.statusUpdateListener as EventListener);
    window.addEventListener('global-data-refresh', this.statusUpdateListener as EventListener);
    this.loadActivityData();
  }

  ngAfterViewInit(): void {
    this.viewInitialized = true;
    this.scheduleChartRender();
  }

  ngOnDestroy(): void {
    window.removeEventListener('candidate-status-updated', this.statusUpdateListener as EventListener);
    window.removeEventListener('global-data-refresh', this.statusUpdateListener as EventListener);
    this.destroyCharts();
    if (this.filterTimeoutId) clearTimeout(this.filterTimeoutId);
    if (this.chartFrameId !== null) window.cancelAnimationFrame(this.chartFrameId);
  }

  get hasTrendData(): boolean {
    return this.trend.interviews.some((value) => value > 0) || this.trend.hired.some((value) => value > 0);
  }

  get hasStatusData(): boolean {
    return this.statusSplit.length > 0;
  }

  get hasAnyActivityData(): boolean {
    return this.summary.total_interviews > 0;
  }

  get maxRecruiterCount(): number {
    return this.maxRecruiterCountValue;
  }

  get maxDailyTotal(): number {
    return this.maxDailyTotalValue;
  }

  get scoreBandRows(): Array<{ label: string; value: number }> {
    return this.scoreBandRowsData;
  }

  get aiHeadline(): string {
    return this.aiHeadlineText;
  }

  get aiAttentionCount(): number {
    return this.aiAttentionCountValue;
  }

  get aiPositiveCount(): number {
    return this.aiPositiveCountValue;
  }

  recruiterBar(item: { count: number }): number {
    return Math.max(8, Math.round((item.count / this.maxRecruiterCount) * 100));
  }

  roleHirePercent(item: { count: number; hired: number }): number {
    if (!item.count) return 0;
    return Math.round((item.hired / item.count) * 100);
  }

  formatRoleWithId(role: string, roleId?: number | string | null): string {
    const roleName = this.normalizeRoleDisplay(role);
    const id = (roleId ?? '').toString().trim();
    if (!roleName) return id;
    return id ? `${roleName} - ${id}` : roleName;
  }

  formatRecruiterDisplay(name: string): string {
    return this.normalizeRecruiterDisplay(name);
  }

  formatDurationHours(hours: number): string {
    const safeHours = Number(hours || 0);
    if (!Number.isFinite(safeHours) || safeHours <= 0) return '0h';
    if (safeHours >= 24 * 7) return '> 7d';
    if (safeHours >= 24) {
      const days = Math.floor(safeHours / 24);
      const remainingHours = Math.round(safeHours % 24);
      return remainingHours ? `${days}d ${remainingHours}h` : `${days}d`;
    }
    if (safeHours >= 1) return `${Math.round(safeHours)}h`;
    return `${Math.round(safeHours * 60)}m`;
  }

  formatMetricValue(value: number, suffix = ''): string {
    const safeValue = Number(value || 0);
    return `${safeValue.toLocaleString()}${suffix}`;
  }

  stageDeltaClass(delta: number): string {
    if (delta > 0) return 'up';
    if (delta < 0) return 'down';
    return 'flat';
  }

  dailyBarWidth(value: number): number {
    return Math.round((value / this.maxDailyTotal) * 100);
  }

  weeklyDelta(): number {
    return this.weeklyDeltaValue;
  }

  heatCellClass(count: number): string {
    if (!count) return 'c0';
    const max = this.upcomingLoadHeat.max_cell || 1;
    const ratio = count / max;
    if (ratio >= 0.75) return 'c4';
    if (ratio >= 0.5) return 'c3';
    if (ratio >= 0.25) return 'c2';
    return 'c1';
  }

  severityClass(severity: string): string {
    if (severity === 'high') return 'high';
    if (severity === 'medium') return 'medium';
    return 'low';
  }

  signalSeverityClass(severity: SignalSeverity): string {
    return severity;
  }

  onFiltersChanged(): void {
    if (this.startDate && this.endDate && this.startDate > this.endDate) {
      this.dateRangeError = 'From date cannot be greater than To date.';
      return;
    }
    this.dateRangeError = '';
    if (this.filterTimeoutId) clearTimeout(this.filterTimeoutId);
    this.filterTimeoutId = setTimeout(() => this.loadActivityData(), 250);
  }

  onStartDateChange(value: string): void {
    this.startDate = value;
    if (this.startDate && this.endDate && this.startDate > this.endDate) {
      this.endDate = this.startDate;
    }
    this.onFiltersChanged();
  }

  onEndDateChange(value: string): void {
    this.endDate = value;
    if (this.startDate && this.endDate && this.endDate < this.startDate) {
      this.startDate = this.endDate;
    }
    this.onFiltersChanged();
  }

  onRecruiterInputFocus(): void {
    this.recruiterQuery = '';
    this.refreshRecruiterFilterOptions();
    this.showRecruiterMenu = true;
  }

  onRoleInputFocus(): void {
    this.roleQuery = '';
    this.refreshRoleFilterOptions();
    this.showRoleMenu = true;
  }

  onRecruiterInputChange(value: string): void {
    this.recruiterQuery = value;
    this.refreshRecruiterFilterOptions();
    this.showRecruiterMenu = true;
  }

  onRoleInputChange(value: string): void {
    this.roleQuery = value;
    this.refreshRoleFilterOptions();
    this.showRoleMenu = true;
  }

  onRecruiterInputBlur(): void {
    setTimeout(() => {
      this.showRecruiterMenu = false;
      this.syncFilterInputLabels();
    }, 120);
  }

  onRoleInputBlur(): void {
    setTimeout(() => {
      this.showRoleMenu = false;
      this.syncFilterInputLabels();
    }, 120);
  }

  selectRecruiterOption(id: string, name: string): void {
    this.selectedRecruiter = id;
    this.recruiterQuery = this.normalizeRecruiterDisplay(name);
    this.showRecruiterMenu = false;
    this.onFiltersChanged();
  }

  selectRoleOption(id: string, name: string): void {
    this.selectedRole = id;
    this.roleQuery = this.normalizeRoleDisplay(name);
    this.showRoleMenu = false;
    this.onFiltersChanged();
  }

  selectFirstRecruiterMatch(): void {
    const first = this.filteredRecruiterOptions[0];
    if (first) this.selectRecruiterOption(first.id, first.name);
  }

  selectFirstRoleMatch(): void {
    const first = this.filteredRoleOptions[0];
    if (first) this.selectRoleOption(first.id, first.name);
  }

  clearFilters(): void {
    this.selectedRecruiter = 'all';
    this.selectedRole = 'all';
    this.selectedStatus = 'all';
    this.recruiterQuery = 'All Recruiters';
    this.roleQuery = 'All Roles';
    this.showRecruiterMenu = false;
    this.showRoleMenu = false;
    this.startDate = '';
    this.endDate = '';
    this.dateRangeError = '';
    this.refreshRecruiterFilterOptions();
    this.refreshRoleFilterOptions();
    this.loadActivityData();
  }

  applyRecruiterByName(name: string): void {
    const normalizedTarget = this.normalizeRecruiterDisplay(name).toLowerCase();
    const match = this.recruiterOptions.find((item) => this.normalizeRecruiterDisplay(item.name).toLowerCase() === normalizedTarget);
    if (!match) return;
    this.applyRecruiterById(match.id);
  }

  applyRecruiterById(id: string | number | null | undefined): void {
    if (id === null || id === undefined || id === '') return;
    const match = this.recruiterOptions.find((item) => String(item.id) === String(id));
    if (!match) return;
    this.selectedRecruiter = String(match.id);
    this.recruiterQuery = this.normalizeRecruiterDisplay(match.name);
    this.onFiltersChanged();
  }

  applyRoleByName(role: string): void {
    const normalizedTarget = this.normalizeRoleDisplay(role).toLowerCase();
    const match = this.roleOptions.find((item) => this.normalizeRoleDisplay(item.name).toLowerCase() === normalizedTarget);
    if (!match) return;
    this.applyRoleById(match.id);
  }

  applyRoleById(id: string | number | null | undefined): void {
    if (id === null || id === undefined || id === '') return;
    const match = this.roleOptions.find((item) => String(item.id) === String(id));
    if (!match) return;
    this.selectedRole = String(match.id);
    this.roleQuery = this.normalizeRoleDisplay(match.name);
    this.onFiltersChanged();
  }

  applyStatus(value: string): void {
    this.selectedStatus = value || 'all';
    this.onFiltersChanged();
  }

  applySingleDay(dateKey: string): void {
    if (!dateKey) return;
    this.startDate = dateKey;
    this.endDate = dateKey;
    this.onFiltersChanged();
  }

  applyMonthByKey(monthKey: string): void {
    if (!monthKey) return;
    const [year, month] = monthKey.split('-').map((item) => Number(item));
    if (!year || !month) return;
    const end = new Date(year, month, 0);
    this.startDate = `${year}-${String(month).padStart(2, '0')}-01`;
    this.endDate = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, '0')}-${String(end.getDate()).padStart(2, '0')}`;
    this.onFiltersChanged();
  }

  onSlaAlertClick(type: string): void {
    if (type === 'overdue_interviews') this.applyStatus('scheduled');
    else if (type === 'stale_assessment') this.applyStatus('assessment_pending');
    else if (type === 'stale_shortlisted') this.applyStatus('shortlisted');
    else this.scrollToSection('activity-sla');
  }

  onStageMovementClick(stage: string): void {
    const map: Record<string, string> = {
      'Assessment Pending': 'assessment_pending',
      'Scheduled': 'scheduled',
      'Shortlisted': 'shortlisted',
      'Hired': 'hired_group',
      'Rejected': 'rejected',
      'Cancelled': 'cancelled',
      'Applied': 'all',
    };
    this.applyStatus(map[stage] || 'all');
  }

  onDropoffReasonClick(reason: string): void {
    const normalized = (reason || '').toLowerCase();
    if (normalized.includes('rejected')) this.applyStatus('rejected');
    else if (normalized.includes('cancelled')) this.applyStatus('cancelled');
    else if (normalized.includes('no show')) this.applyStatus('scheduled');
    else if (normalized.includes('screening')) this.applyStatus('assessment_pending');
    else this.applyStatus('all');
  }

  onRecycledClick(roleName: string, roleId?: number | null): void {
    if (roleId) {
      this.applyRoleById(roleId);
      return;
    }
    if (roleName) this.applyRoleByName(roleName);
  }

  runSignalAction(action?: SignalAction): void {
    if (!action) return;
    if (action.type === 'status') this.applyStatus(String(action.value || 'all'));
    else if (action.type === 'role') this.applyRoleById(action.value);
    else if (action.type === 'recruiter') this.applyRecruiterById(action.value);
    else if (action.type === 'month') this.applyMonthByKey(String(action.value || ''));
    else if (action.type === 'section') this.scrollToSection(String(action.value || ''));
    else if (action.type === 'clear') this.clearFilters();
  }

  exportSnapshot(format: 'json' | 'csv'): void {
    const nowStamp = new Date().toISOString().replace(/[:.]/g, '-');
    if (format === 'json') {
      const payload = {
        generated_at: this.exportMeta.generated_at || new Date().toISOString(),
        filters: this.exportMeta.filters,
        summary: this.summary,
        ai_signals: this.aiSignals,
        role_risk_score: this.roleRiskScore,
        target_vs_actual: this.targetVsActual,
        recycled_summary: this.recycledSummary,
        top_recruiters: this.recruiterBreakdown,
        top_roles: this.roleBreakdown,
      };
      this.downloadBlob(JSON.stringify(payload, null, 2), `activity-snapshot-${nowStamp}.json`, 'application/json');
      return;
    }

    const rows: string[] = [];
    rows.push('section,key,value');
    rows.push(`summary,total_interviews,${this.summary.total_interviews}`);
    rows.push(`summary,hires,${this.summary.hired}`);
    rows.push(`summary,upcoming,${this.summary.upcoming}`);
    rows.push(`summary,hire_rate,${this.summary.hire_rate}`);
    rows.push(`summary,avg_response_time,${this.responseTime.avg_hours}`);
    rows.push(`targets,target_total,${this.targetVsActual.target_total}`);
    rows.push(`targets,actual_total,${this.targetVsActual.actual_total}`);
    rows.push(`targets,gap,${this.targetVsActual.gap}`);
    this.aiSignals.forEach((item) => {
      rows.push(`ai_signal,${this.escapeCsv(item.title)},${this.escapeCsv(item.message)}`);
    });
    this.roleRiskScore.forEach((item) => {
      rows.push(`role_risk,${this.escapeCsv(item.role)},${item.risk_score}`);
    });
    this.recycledSummary.list.forEach((item) => {
      rows.push(`recycled,${this.escapeCsv(item.candidate)},${item.interviews}`);
    });
    this.downloadBlob(rows.join('\n'), `activity-snapshot-${nowStamp}.csv`, 'text/csv;charset=utf-8;');
  }

  private getApiBaseUrl(): string {
    let portNumber = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      portNumber = '8000';
    }
    return `${window.location.protocol}//${window.location.hostname}:${portNumber}`;
  }

  private loadActivityData(): void {
    this.loading = true;
    this.errorMessage = '';

    const apiBaseUrl = this.getApiBaseUrl();
    let params = new HttpParams();
    if (this.selectedRecruiter && this.selectedRecruiter !== 'all') params = params.set('recruiter', this.selectedRecruiter);
    if (this.selectedRole && this.selectedRole !== 'all') params = params.set('role', this.selectedRole);
    if (this.selectedStatus && this.selectedStatus !== 'all') params = params.set('status', this.selectedStatus);
    if (this.startDate) params = params.set('start_date', this.startDate);
    if (this.endDate) params = params.set('end_date', this.endDate);

    this.http.get<ActivityResponse>(`${apiBaseUrl}/activity-tab-data/`, { params })
      .pipe(
        catchError((error) => {
          console.error('Error fetching activity data', error);
          this.loading = false;
          this.errorMessage = 'Unable to load activity data.';
          this.cdr.markForCheck();
          return of({ Success: false, Data: {} } as ActivityResponse);
        })
      )
      .subscribe((response) => {
        if (!response?.Success) {
          this.errorMessage = response?.Error || 'Unable to load activity data.';
          this.loading = false;
          this.cdr.markForCheck();
          return;
        }

        const data = response.Data || {};
        this.summary = { ...this.summary, ...(data.summary || {}) };
        this.trend = {
          title: data.trend?.title || 'Interview Trend (Last 6 Months)',
          labels: data.trend?.labels || [],
          interviews: data.trend?.interviews || [],
          hired: data.trend?.hired || [],
        };

        const palette = ['#22d3ee', '#3b82f6', '#10b981', '#ef4444', '#f59e0b', '#9ca3af', '#8b5cf6'];
        this.statusSplit = Object.entries(data.status_split || {})
          .map(([label, value], index) => ({
            label,
            value: Number(value || 0),
            color: palette[index % palette.length]
          }))
          .filter((item) => item.value > 0)
          .sort((left, right) => right.value - left.value);

        this.recruiterBreakdown = (data.recruiter_breakdown || []).map((item) => ({
          ...item,
          name: this.normalizeRecruiterDisplay(item.name),
        }));
        this.roleBreakdown = (data.role_breakdown || []).map((item) => ({
          ...item,
          role: this.normalizeRoleDisplay(item.role),
        }));
        this.recentActivity = (data.recent_activity || []).map((item) => ({
          ...item,
          meta: this.normalizeInlineMeta(item.meta),
        }));
        this.upcomingList = (data.upcoming_list || []).map((item) => ({
          ...item,
          role: this.normalizeRoleDisplay(item.role),
        }));
        this.slaAlerts = data.sla_alerts || [];
        this.stageMovement = data.stage_movement || [];
        this.dropoffReasons = data.dropoff_reasons || [];
        this.insights = data.insights || [];
        this.responseTime = {
          avg_hours: data.response_time?.avg_hours || 0,
          median_hours: data.response_time?.median_hours || 0,
          samples: data.response_time?.samples || 0,
          by_recruiter: (data.response_time?.by_recruiter || []).map((item) => ({
            ...item,
            name: this.normalizeRecruiterDisplay(item.name),
          })),
        };
        this.outcomeQuality = {
          evaluated: data.outcome_quality?.evaluated || 0,
          hired: data.outcome_quality?.hired || 0,
          shortlisted: data.outcome_quality?.shortlisted || 0,
          rejected: data.outcome_quality?.rejected || 0,
          score_bands: data.outcome_quality?.score_bands || {},
          scored_count: data.outcome_quality?.scored_count || 0,
          quality_by_role: (data.outcome_quality?.quality_by_role || []).map((item) => ({
            ...item,
            role: this.normalizeRoleDisplay(item.role),
          })),
        };
        this.productivity = {
          daily: data.productivity?.daily || [],
          current_week_total: data.productivity?.current_week_total || 0,
          previous_week_total: data.productivity?.previous_week_total || 0,
          current_week_hired: data.productivity?.current_week_hired || 0,
        };
        this.upcomingLoadHeat = {
          slots: data.upcoming_load_heat?.slots || [],
          days: data.upcoming_load_heat?.days || [],
          max_cell: data.upcoming_load_heat?.max_cell || 0,
          total_scheduled: data.upcoming_load_heat?.total_scheduled || 0,
        };
        this.roleRiskScore = (data.role_risk_score || []).map((item) => ({
          ...item,
          role: this.normalizeRoleDisplay(item.role),
        }));
        this.targetVsActual = {
          target_total: data.target_vs_actual?.target_total || 0,
          actual_total: data.target_vs_actual?.actual_total || 0,
          gap: data.target_vs_actual?.gap || 0,
          progress_pct: data.target_vs_actual?.progress_pct || 0,
          labels: data.target_vs_actual?.labels || [],
          keys: data.target_vs_actual?.keys || [],
          target_series: data.target_vs_actual?.target_series || [],
          actual_series: data.target_vs_actual?.actual_series || [],
        };
        this.recycledSummary = {
          total_recycled: data.recycled_summary?.total_recycled || 0,
          reopened: data.recycled_summary?.reopened || 0,
          list: (data.recycled_summary?.list || []).map((item) => ({
            ...item,
            roles: (item.roles || []).map((role) => this.normalizeRoleDisplay(role)),
          })),
        };
        this.exportMeta = {
          generated_at: data.export_meta?.generated_at || '',
          filters: {
            recruiter: data.export_meta?.filters?.recruiter || 'all',
            role: data.export_meta?.filters?.role || 'all',
            start_date: data.export_meta?.filters?.start_date || '',
            end_date: data.export_meta?.filters?.end_date || '',
          },
        };
        this.recruiterOptions = (data.filter_options?.recruiters || this.recruiterOptions).map((item) => ({
          ...item,
          name: this.normalizeRecruiterDisplay(item.name),
        }));
        this.roleOptions = (data.filter_options?.roles || this.roleOptions).map((item) => ({
          ...item,
          name: this.normalizeRoleDisplay(item.name),
        }));
        this.statusOptions = data.filter_options?.statuses || this.statusOptions;

        this.buildViewModel();
        this.syncFilterInputLabels();
        this.refreshRecruiterFilterOptions();
        this.refreshRoleFilterOptions();

        this.loading = false;
        this.scheduleChartRender();
        this.cdr.markForCheck();
      });
  }

  private buildViewModel(): void {
    this.summaryCards = this.buildSummaryCards();
    this.aiSignals = this.buildAiSignals();
    this.attentionSignals = this.aiSignals.filter((signal) => signal.severity === 'critical' || signal.severity === 'warning').slice(0, 4);
    this.positiveSignals = this.aiSignals.filter((signal) => signal.severity === 'positive' || signal.severity === 'info').slice(0, 4);
    this.recommendedActions = this.buildRecommendedActions(this.aiSignals);
    this.scoreBandRowsData = Object.entries(this.outcomeQuality.score_bands || {})
      .map(([label, value]) => ({ label, value: Number(value || 0) }))
      .filter((row) => row.value > 0);
    this.aiHeadlineText = this.aiSignals[0] ? `${this.aiSignals[0].title}: ${this.aiSignals[0].message}` : 'AI activity monitor is ready.';
    this.aiAttentionCountValue = this.aiSignals.filter((signal) => signal.severity === 'critical' || signal.severity === 'warning').length;
    this.aiPositiveCountValue = this.aiSignals.filter((signal) => signal.severity === 'positive').length;
    this.maxRecruiterCountValue = this.recruiterBreakdown[0]?.count || 1;
    this.maxDailyTotalValue = Math.max(1, ...this.productivity.daily.map((item) => item.total));
    this.weeklyDeltaValue = (this.productivity.current_week_total || 0) - (this.productivity.previous_week_total || 0);
  }

  private buildSummaryCards(): SummaryCard[] {
    return [
      {
        label: 'Total Interviews',
        icon: 'ph ph-chats-teardrop',
        value: this.formatMetricValue(this.summary.total_interviews),
        helper: 'Activity tracked in the current scope',
      },
      {
        label: 'Hires Closed',
        icon: 'ph ph-check-circle',
        value: this.formatMetricValue(this.summary.hired),
        helper: 'Completed or hired outcomes',
        tone: this.summary.hired > 0 ? 'positive' : 'info',
      },
      {
        label: 'Upcoming',
        icon: 'ph ph-calendar-plus',
        value: this.formatMetricValue(this.summary.upcoming),
        helper: this.summary.upcoming ? 'Scheduled interviews still ahead' : 'No interviews are lined up',
        tone: this.summary.upcoming ? 'info' : 'warning',
      },
      {
        label: 'Hire Rate',
        icon: 'ph ph-percent',
        value: `${this.summary.hire_rate}%`,
        helper: 'Conversion of tracked interviews',
        tone: this.summary.hire_rate >= 20 ? 'positive' : 'info',
      },
      {
        label: 'Response Time',
        icon: 'ph ph-timer',
        value: this.formatDurationHours(this.responseTime.avg_hours),
        helper: 'Average first-touch speed',
        tone: this.responseTime.avg_hours <= 24 && this.responseTime.avg_hours > 0 ? 'positive' : 'warning',
      },
      {
        label: 'Active Recruiters',
        icon: 'ph ph-users-three',
        value: this.formatMetricValue(this.summary.active_recruiters),
        helper: 'Recruiters contributing in the range',
      },
      {
        label: 'Open Roles',
        icon: 'ph ph-briefcase-metal',
        value: this.formatMetricValue(this.summary.open_roles),
        helper: 'Roles still needing pipeline coverage',
      },
      {
        label: 'Last 30 Days',
        icon: 'ph ph-clock-countdown',
        value: this.formatMetricValue(this.summary.last_30_days),
        helper: 'Recent interview velocity snapshot',
      },
    ];
  }

  private buildAiSignals(): ActivitySignal[] {
    const signals: ActivitySignal[] = [];
    const overdueInterviews = this.getSlaCount('overdue_interviews');
    const staleAssessment = this.getSlaCount('stale_assessment');
    const staleShortlisted = this.getSlaCount('stale_shortlisted');
    const unassigned = this.getSlaCount('unassigned_recruiter');
    const topRecruiter = this.recruiterBreakdown[0];
    const totalRecruiterVolume = this.recruiterBreakdown.reduce((sum, item) => sum + item.count, 0);
    const topRole = this.roleBreakdown[0];
    const highRiskRole = this.roleRiskScore.find((item) => item.severity === 'high') || this.roleRiskScore[0];
    const cancellations = this.dropoffReasons.find((item) => item.reason.toLowerCase().includes('cancel'));
    const noShows = this.dropoffReasons.find((item) => item.reason.toLowerCase().includes('no show'));
    const weeklyDelta = this.weeklyDelta();
    const stalledScheduling = this.summary.upcoming === 0 && this.summary.total_interviews > 0;
    const imbalanceRatio = topRecruiter && totalRecruiterVolume ? topRecruiter.count / totalRecruiterVolume : 0;

    if (overdueInterviews > 0) {
      signals.push({
        id: 'overdue-interviews',
        severity: 'critical',
        icon: 'ph ph-warning-octagon',
        title: `${overdueInterviews} overdue scheduled interviews need closure`,
        message: 'Move them to the correct outcome so downstream reporting and recruiter queues stay accurate.',
        metric: `${overdueInterviews} pending`,
        ctaLabel: 'Review overdue interviews',
        action: { type: 'status', value: 'scheduled' },
      });
    }

    if (staleAssessment > 0) {
      signals.push({
        id: 'assessment-backlog',
        severity: 'warning',
        icon: 'ph ph-hourglass-medium',
        title: 'Assessment backlog is building up',
        message: `${staleAssessment} candidates are stuck beyond SLA and need follow-up or disposition.`,
        metric: `${staleAssessment} stale`,
        ctaLabel: 'Review assessments',
        action: { type: 'status', value: 'assessment_pending' },
      });
    }

    if (staleShortlisted > 0) {
      signals.push({
        id: 'stale-shortlist',
        severity: 'warning',
        icon: 'ph ph-user-focus',
        title: 'Shortlisted candidates are going stale',
        message: `${staleShortlisted} candidates have not progressed on time and are at drop-off risk.`,
        metric: `${staleShortlisted} stale`,
        ctaLabel: 'Follow up on shortlist',
        action: { type: 'status', value: 'shortlisted' },
      });
    }

    if (highRiskRole && highRiskRole.remaining > 0) {
      signals.push({
        id: 'role-risk',
        severity: highRiskRole.severity === 'high' ? 'critical' : 'warning',
        icon: 'ph ph-siren',
        title: `${this.normalizeRoleDisplay(highRiskRole.role)} is under hiring pressure`,
        message: `Risk score is ${highRiskRole.risk_score} with ${highRiskRole.remaining} seats still open and ${highRiskRole.pipeline} active in pipeline.`,
        metric: `${highRiskRole.progress_pct}% filled`,
        ctaLabel: 'Inspect risk role',
        action: { type: 'role', value: highRiskRole.role_id },
      });
    }

    if (stalledScheduling) {
      signals.push({
        id: 'scheduling-slowdown',
        severity: 'warning',
        icon: 'ph ph-calendar-x',
        title: 'No interviews are upcoming',
        message: 'This usually means scheduling throughput is slowing down or pipeline follow-ups are stuck.',
        metric: '0 upcoming',
        ctaLabel: 'Check load heat',
        action: { type: 'section', value: 'activity-load' },
      });
    }

    if (unassigned > 0) {
      signals.push({
        id: 'unowned-activity',
        severity: 'warning',
        icon: 'ph ph-user-minus',
        title: `${unassigned} activity items are unowned`,
        message: 'Not Assigned work needs recruiter coverage to keep SLAs moving.',
        metric: `${unassigned} unowned`,
        ctaLabel: 'Review SLA queue',
        action: { type: 'section', value: 'activity-sla' },
      });
    }

    if (topRole && topRole.count > 0) {
      signals.push({
        id: 'top-role-volume',
        severity: 'positive',
        icon: 'ph ph-trend-up',
        title: `${this.normalizeRoleDisplay(topRole.role)} shows the strongest interview volume`,
        message: `${topRole.count} interviews and ${topRole.hired} hires are currently concentrated in this role.`,
        metric: `${topRole.count} interviews`,
        ctaLabel: 'Open role throughput',
        action: topRole.role_id ? { type: 'role', value: topRole.role_id } : { type: 'section', value: 'activity-roles' },
      });
    }

    if (topRecruiter && topRecruiter.count > 0) {
      const severity: SignalSeverity = imbalanceRatio >= 0.45 && this.recruiterBreakdown.length > 1 ? 'warning' : 'positive';
      signals.push({
        id: 'top-recruiter',
        severity,
        icon: 'ph ph-identification-card',
        title: `${this.normalizeRecruiterDisplay(topRecruiter.name)} is leading interview activity`,
        message: severity === 'warning'
          ? 'Volume is concentrated with one recruiter, so rebalance may help protect responsiveness.'
          : 'Recruiter activity is healthy and visibly driving pipeline movement.',
        metric: `${topRecruiter.count} interviews`,
        ctaLabel: 'View recruiter load',
        action: topRecruiter.recruiter_id
          ? { type: 'recruiter', value: topRecruiter.recruiter_id }
          : { type: 'section', value: 'activity-recruiters' },
      });
    }

    if (this.targetVsActual.gap > 0) {
      signals.push({
        id: 'target-gap',
        severity: this.targetVsActual.gap >= 3 ? 'warning' : 'info',
        icon: 'ph ph-target',
        title: 'Hiring pace is below target',
        message: `${this.targetVsActual.gap} open target slots still need to be closed in the current planning window.`,
        metric: `${this.targetVsActual.progress_pct}% achieved`,
        ctaLabel: 'Review target vs actual',
        action: { type: 'section', value: 'activity-targets' },
      });
    }

    if ((cancellations?.count || 0) > 0 || (noShows?.count || 0) > 0) {
      const totalDropRisk = (cancellations?.count || 0) + (noShows?.count || 0);
      signals.push({
        id: 'dropoff-risk',
        severity: 'warning',
        icon: 'ph ph-arrow-bend-down-right',
        title: 'Recent cancellations may indicate candidate drop-off risk',
        message: `${totalDropRisk} recent cancellation or no-show events are hurting pipeline reliability.`,
        metric: `${totalDropRisk} risk events`,
        ctaLabel: 'Review drop-off reasons',
        action: { type: 'section', value: 'activity-dropoff' },
      });
    }

    if (this.summary.hired > 0 && this.summary.hire_rate >= 20) {
      signals.push({
        id: 'hiring-momentum',
        severity: 'positive',
        icon: 'ph ph-rocket-launch',
        title: 'Hiring momentum is healthy',
        message: `${this.summary.hired} hires are closed with a ${this.summary.hire_rate}% hire rate in the selected scope.`,
        metric: `${this.summary.hired} hires`,
        ctaLabel: 'Check trend',
        action: { type: 'section', value: 'activity-trend' },
      });
    }

    if (weeklyDelta > 0) {
      signals.push({
        id: 'weekly-velocity',
        severity: 'positive',
        icon: 'ph ph-chart-line-up',
        title: 'This week is moving faster than the previous one',
        message: `Interview throughput is up by ${weeklyDelta} compared with the prior week.`,
        metric: `${this.productivity.current_week_total} this week`,
        ctaLabel: 'View productivity',
        action: { type: 'section', value: 'activity-productivity' },
      });
    }

    if (!signals.length) {
      signals.push({
        id: 'all-clear',
        severity: 'info',
        icon: 'ph ph-shield-check',
        title: 'All clear',
        message: 'No immediate backlog or risk pattern stands out in the selected activity window.',
        metric: 'Healthy',
        ctaLabel: 'Reset filters',
        action: { type: 'clear' },
      });
    }

    const severityOrder: Record<SignalSeverity, number> = {
      critical: 0,
      warning: 1,
      positive: 2,
      info: 3,
    };
    return signals.sort((left, right) => severityOrder[left.severity] - severityOrder[right.severity]).slice(0, 8);
  }

  private buildRecommendedActions(signals: ActivitySignal[]): RecommendedAction[] {
    const actions: RecommendedAction[] = [];
    const pushAction = (action: RecommendedAction) => {
      if (actions.some((item) => item.id === action.id)) return;
      actions.push(action);
    };

    signals.forEach((signal) => {
      if (!signal.action) return;
      pushAction({
        id: signal.id,
        label: signal.ctaLabel || signal.title,
        description: signal.message,
        icon: signal.icon,
        severity: signal.severity,
        action: signal.action,
      });
    });

    if (!actions.length) {
      pushAction({
        id: 'default-review',
        label: 'Review activity snapshot',
        description: 'Use the AI brief and top operational panels to validate pipeline health.',
        icon: 'ph ph-compass-tool',
        severity: 'info',
        action: { type: 'section', value: 'activity-trend' },
      });
    }

    return actions.slice(0, 5);
  }

  private getSlaCount(type: string): number {
    return this.slaAlerts.find((item) => item.type === type)?.count || 0;
  }

  private scheduleChartRender(): void {
    if (!this.viewInitialized) return;
    if (this.chartFrameId !== null) window.cancelAnimationFrame(this.chartFrameId);
    this.chartFrameId = window.requestAnimationFrame(() => {
      this.chartFrameId = null;
      this.renderCharts();
    });
  }

  private renderCharts(): void {
    const trendCtx = this.trendCanvas?.nativeElement?.getContext('2d');
    if (this.trendCanvas?.nativeElement && trendCtx && this.hasTrendData) {
      if (this.trendChart) this.trendChart.destroy();
      this.trendChart = new Chart(trendCtx, {
        type: 'line',
        data: {
          labels: this.trend.labels,
          datasets: [
            {
              label: 'Interviews',
              data: this.trend.interviews,
              borderColor: '#53dbff',
              backgroundColor: 'rgba(83, 219, 255, 0.12)',
              fill: true,
              tension: 0.35,
              pointRadius: 2.5,
              pointHoverRadius: 4,
              pointBackgroundColor: '#baf6ff'
            },
            {
              label: 'Hires',
              data: this.trend.hired,
              borderColor: '#4ce0a1',
              backgroundColor: 'rgba(76, 224, 161, 0.1)',
              fill: false,
              tension: 0.28,
              pointRadius: 2.5,
              pointHoverRadius: 4,
              pointBackgroundColor: '#d7ffe8'
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              labels: {
                color: '#b7d9f3',
                boxWidth: 12,
                usePointStyle: true,
              }
            },
            tooltip: {
              backgroundColor: 'rgba(3, 16, 34, 0.96)',
              borderColor: 'rgba(102, 211, 255, 0.25)',
              borderWidth: 1,
              titleColor: '#f5fbff',
              bodyColor: '#cce8ff',
              displayColors: true,
            }
          },
          scales: {
            x: {
              ticks: { color: '#90b8d8' },
              grid: { color: 'rgba(111, 170, 214, 0.08)' }
            },
            y: {
              beginAtZero: true,
              ticks: { color: '#90b8d8', stepSize: 1 },
              grid: { color: 'rgba(111, 170, 214, 0.08)' }
            }
          }
        }
      });
    } else if (this.trendChart) {
      this.trendChart.destroy();
      this.trendChart = undefined;
    }

    const statusCtx = this.statusCanvas?.nativeElement?.getContext('2d');
    if (this.statusCanvas?.nativeElement && statusCtx && this.hasStatusData) {
      if (this.statusChart) this.statusChart.destroy();
      this.statusChart = undefined;
      this.statusChart = new Chart(statusCtx, {
        type: 'doughnut',
        data: {
          labels: this.statusSplit.map((item) => item.label),
          datasets: [{
            data: this.statusSplit.map((item) => item.value),
            backgroundColor: this.statusSplit.map((item) => item.color),
            borderColor: 'rgba(3, 16, 34, 0.9)',
            borderWidth: 3,
            hoverOffset: 6,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '68%',
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: 'rgba(3, 16, 34, 0.96)',
              borderColor: 'rgba(102, 211, 255, 0.25)',
              borderWidth: 1,
              titleColor: '#f5fbff',
              bodyColor: '#cce8ff',
            }
          }
        }
      });
    } else if (this.statusChart) {
      this.statusChart.destroy();
      this.statusChart = undefined;
    }
  }

  private destroyCharts(): void {
    if (this.trendChart) {
      this.trendChart.destroy();
      this.trendChart = undefined;
    }
    if (this.statusChart) {
      this.statusChart.destroy();
      this.statusChart = undefined;
    }
  }

  private scrollToSection(sectionId: string): void {
    const section = document.getElementById(sectionId);
    if (!section) return;
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  private downloadBlob(content: string, filename: string, mime: string): void {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  private escapeCsv(value: string): string {
    const normalized = String(value ?? '');
    if (normalized.includes(',') || normalized.includes('"') || normalized.includes('\n')) {
      return `"${normalized.replace(/"/g, '""')}"`;
    }
    return normalized;
  }

  private syncFilterInputLabels(): void {
    if (this.selectedRecruiter === 'all') {
      this.recruiterQuery = 'All Recruiters';
    } else {
      const recruiterMatch = this.recruiterOptions.find((item) => String(item.id) === this.selectedRecruiter);
      this.recruiterQuery = recruiterMatch ? this.normalizeRecruiterDisplay(recruiterMatch.name) : 'All Recruiters';
      if (!recruiterMatch) this.selectedRecruiter = 'all';
    }

    if (this.selectedRole === 'all') {
      this.roleQuery = 'All Roles';
    } else {
      const roleMatch = this.roleOptions.find((item) => String(item.id) === this.selectedRole);
      this.roleQuery = roleMatch ? this.normalizeRoleDisplay(roleMatch.name) : 'All Roles';
      if (!roleMatch) this.selectedRole = 'all';
    }
  }

  private refreshRecruiterFilterOptions(): void {
    const search = this.recruiterQuery.trim().toLowerCase();
    const base = [
      { id: 'all', name: 'All Recruiters' },
      ...this.recruiterOptions.map((item) => ({ id: String(item.id), name: this.normalizeRecruiterDisplay(item.name) })),
    ];
    this.filteredRecruiterOptions = (search ? base.filter((item) => item.name.toLowerCase().includes(search)) : base).slice(0, 60);
  }

  private refreshRoleFilterOptions(): void {
    const search = this.roleQuery.trim().toLowerCase();
    const base = [
      { id: 'all', name: 'All Roles' },
      ...this.roleOptions.map((item) => ({ id: String(item.id), name: this.normalizeRoleDisplay(item.name) })),
    ];
    this.filteredRoleOptions = (search ? base.filter((item) => item.name.toLowerCase().includes(search)) : base).slice(0, 60);
  }

  private normalizeRecruiterDisplay(name: string): string {
    const value = (name || '').trim();
    if (!value) return 'Not Assigned';
    const lowered = value.toLowerCase();
    if (lowered === 'tbd tbd' || lowered === 'tbd' || lowered === 'unassigned') return 'Not Assigned';
    return value;
  }

  private normalizeRoleDisplay(role: string): string {
    const value = (role || '').trim();
    if (!value) return 'Unassigned';
    if (value.toLowerCase() === 'salesfore developer') return 'Salesforce Developer';
    return value;
  }

  private normalizeInlineMeta(meta: string): string {
    return (meta || '')
      .replace(/Salesfore Developer/g, 'Salesforce Developer')
      .replace(/\bTbd Tbd\b/g, 'Not Assigned')
      .replace(/\bUnassigned\b/g, 'Not Assigned');
  }
}
