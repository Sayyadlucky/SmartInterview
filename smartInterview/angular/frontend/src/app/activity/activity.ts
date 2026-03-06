import { AfterViewChecked, AfterViewInit, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpParams } from '@angular/common/http';
import { catchError, of } from 'rxjs';
import { Chart, registerables } from 'chart.js';

Chart.register(...registerables);

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
    recruiter_breakdown?: Array<{ name: string; count: number }>;
    role_breakdown?: Array<{ role: string; count: number; hired: number }>;
    recent_activity?: Array<{ id: number; title: string; meta: string; date: string }>;
    upcoming_list?: Array<{ id: number; candidate: string; role: string; date: string }>;
    sla_alerts?: Array<{ type: string; title: string; count: number; severity: 'high' | 'medium' | 'low'; description: string }>;
    stage_movement?: Array<{ stage: string; current: number; previous: number; delta: number }>;
    dropoff_reasons?: Array<{ reason: string; count: number }>;
    insights?: string[];
    response_time?: {
      avg_hours?: number;
      median_hours?: number;
      samples?: number;
      by_recruiter?: Array<{ name: string; avg_hours: number; count: number }>;
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
      severity: 'high' | 'medium' | 'low';
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
      list?: Array<{ candidate: string; interviews: number; roles: string[]; latest_status: string; reopened: boolean }>;
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

@Component({
  selector: 'app-activity',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './activity.html',
  styleUrl: './activity.scss'
})
export class Activity implements OnInit, AfterViewInit, AfterViewChecked, OnDestroy {
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
  recruiterBreakdown: Array<{ name: string; count: number }> = [];
  roleBreakdown: Array<{ role: string; count: number; hired: number }> = [];
  recentActivity: Array<{ id: number; title: string; meta: string; date: string }> = [];
  upcomingList: Array<{ id: number; candidate: string; role: string; date: string }> = [];
  slaAlerts: Array<{ type: string; title: string; count: number; severity: 'high' | 'medium' | 'low'; description: string }> = [];
  stageMovement: Array<{ stage: string; current: number; previous: number; delta: number }> = [];
  dropoffReasons: Array<{ reason: string; count: number }> = [];
  insights: string[] = [];
  responseTime = {
    avg_hours: 0,
    median_hours: 0,
    samples: 0,
    by_recruiter: [] as Array<{ name: string; avg_hours: number; count: number }>,
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
    severity: 'high' | 'medium' | 'low';
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
    list: [] as Array<{ candidate: string; interviews: number; roles: string[]; latest_status: string; reopened: boolean }>,
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
  private chartRenderPending = false;
  private filterTimeoutId: ReturnType<typeof setTimeout> | null = null;

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    this.loadActivityData();
  }

  ngAfterViewInit(): void {
    if (this.chartRenderPending) {
      const rendered = this.renderCharts();
      this.chartRenderPending = !rendered;
    }
  }

  ngAfterViewChecked(): void {
    if (!this.chartRenderPending || this.loading) return;
    const rendered = this.renderCharts();
    this.chartRenderPending = !rendered;
  }

  ngOnDestroy(): void {
    this.destroyCharts();
    if (this.filterTimeoutId) clearTimeout(this.filterTimeoutId);
  }

  get hasTrendData(): boolean {
    return this.trend.interviews.some((x) => x > 0) || this.trend.hired.some((x) => x > 0);
  }

  get hasStatusData(): boolean {
    return this.statusSplit.length > 0;
  }

  get hasAnyActivityData(): boolean {
    return this.summary.total_interviews > 0;
  }

  get maxRecruiterCount(): number {
    return this.recruiterBreakdown[0]?.count || 1;
  }

  recruiterBar(item: { count: number }): number {
    return Math.max(8, Math.round((item.count / this.maxRecruiterCount) * 100));
  }

  roleHirePercent(item: { count: number; hired: number }): number {
    if (!item.count) return 0;
    return Math.round((item.hired / item.count) * 100);
  }

  get maxDailyTotal(): number {
    const values = this.productivity.daily.map((x) => x.total);
    return Math.max(1, ...values);
  }

  get scoreBandRows(): Array<{ label: string; value: number }> {
    return Object.entries(this.outcomeQuality.score_bands || {})
      .map(([label, value]) => ({ label, value: Number(value || 0) }))
      .filter((x) => x.value > 0);
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
    return (this.productivity.current_week_total || 0) - (this.productivity.previous_week_total || 0);
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
    this.recruiterQuery = name;
    this.showRecruiterMenu = false;
    this.onFiltersChanged();
  }

  selectRoleOption(id: string, name: string): void {
    this.selectedRole = id;
    this.roleQuery = name;
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
    const match = this.recruiterOptions.find((x) => x.name.toLowerCase() === (name || '').toLowerCase());
    if (!match) return;
    this.selectedRecruiter = String(match.id);
    this.recruiterQuery = match.name;
    this.onFiltersChanged();
  }

  applyRoleByName(role: string): void {
    const match = this.roleOptions.find((x) => x.name.toLowerCase() === (role || '').toLowerCase());
    if (!match) return;
    this.selectedRole = String(match.id);
    this.roleQuery = match.name;
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
    const [year, month] = monthKey.split('-').map((x) => Number(x));
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
    else this.applyStatus('all');
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

  onRecycledClick(roleName: string): void {
    if (roleName) this.applyRoleByName(roleName);
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
          return of({ Success: false, Data: {} } as ActivityResponse);
        })
      )
      .subscribe((response) => {
        if (!response?.Success) {
          this.errorMessage = response?.Error || 'Unable to load activity data.';
          this.loading = false;
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
          .map(([label, value], index) => ({ label, value: Number(value || 0), color: palette[index % palette.length] }))
          .filter((item) => item.value > 0)
          .sort((a, b) => b.value - a.value);

        this.recruiterBreakdown = data.recruiter_breakdown || [];
        this.roleBreakdown = data.role_breakdown || [];
        this.recentActivity = data.recent_activity || [];
        this.upcomingList = data.upcoming_list || [];
        this.slaAlerts = data.sla_alerts || [];
        this.stageMovement = data.stage_movement || [];
        this.dropoffReasons = data.dropoff_reasons || [];
        this.insights = data.insights || [];
        this.responseTime = {
          avg_hours: data.response_time?.avg_hours || 0,
          median_hours: data.response_time?.median_hours || 0,
          samples: data.response_time?.samples || 0,
          by_recruiter: data.response_time?.by_recruiter || [],
        };
        this.outcomeQuality = {
          evaluated: data.outcome_quality?.evaluated || 0,
          hired: data.outcome_quality?.hired || 0,
          shortlisted: data.outcome_quality?.shortlisted || 0,
          rejected: data.outcome_quality?.rejected || 0,
          score_bands: data.outcome_quality?.score_bands || {},
          scored_count: data.outcome_quality?.scored_count || 0,
          quality_by_role: data.outcome_quality?.quality_by_role || [],
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
        this.roleRiskScore = data.role_risk_score || [];
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
          list: data.recycled_summary?.list || [],
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
        this.recruiterOptions = data.filter_options?.recruiters || this.recruiterOptions;
        this.roleOptions = data.filter_options?.roles || this.roleOptions;
        this.statusOptions = data.filter_options?.statuses || this.statusOptions;
        this.syncFilterInputLabels();
        this.refreshRecruiterFilterOptions();
        this.refreshRoleFilterOptions();

        this.loading = false;
        this.chartRenderPending = true;
        setTimeout(() => {
          const rendered = this.renderCharts();
          this.chartRenderPending = !rendered;
        }, 0);
      });
  }

  exportSnapshot(format: 'json' | 'csv'): void {
    const nowStamp = new Date().toISOString().replace(/[:.]/g, '-');
    if (format === 'json') {
      const payload = {
        generated_at: this.exportMeta.generated_at || new Date().toISOString(),
        filters: this.exportMeta.filters,
        summary: this.summary,
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
    rows.push(`summary,upcoming,${this.summary.upcoming}`);
    rows.push(`summary,hire_rate,${this.summary.hire_rate}`);
    rows.push(`targets,target_total,${this.targetVsActual.target_total}`);
    rows.push(`targets,actual_total,${this.targetVsActual.actual_total}`);
    rows.push(`targets,gap,${this.targetVsActual.gap}`);
    rows.push(`targets,progress_pct,${this.targetVsActual.progress_pct}`);
    this.roleRiskScore.forEach((item) => {
      rows.push(`role_risk,${this.escapeCsv(item.role)},${item.risk_score}`);
    });
    this.recycledSummary.list.forEach((item) => {
      rows.push(`recycled,${this.escapeCsv(item.candidate)},${item.interviews}`);
    });
    this.downloadBlob(rows.join('\n'), `activity-snapshot-${nowStamp}.csv`, 'text/csv;charset=utf-8;');
  }

  private downloadBlob(content: string, filename: string, mime: string): void {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  private escapeCsv(value: string): string {
    const v = String(value ?? '');
    if (v.includes(',') || v.includes('"') || v.includes('\n')) {
      return `"${v.replace(/"/g, '""')}"`;
    }
    return v;
  }

  private syncFilterInputLabels(): void {
    if (this.selectedRecruiter === 'all') {
      this.recruiterQuery = 'All Recruiters';
    } else {
      const match = this.recruiterOptions.find((x) => String(x.id) === this.selectedRecruiter);
      this.recruiterQuery = match?.name || 'All Recruiters';
      if (!match) this.selectedRecruiter = 'all';
    }

    if (this.selectedRole === 'all') {
      this.roleQuery = 'All Roles';
    } else {
      const match = this.roleOptions.find((x) => String(x.id) === this.selectedRole);
      this.roleQuery = match?.name || 'All Roles';
      if (!match) this.selectedRole = 'all';
    }
  }

  private refreshRecruiterFilterOptions(): void {
    const search = this.recruiterQuery.trim().toLowerCase();
    const base = [{ id: 'all', name: 'All Recruiters' }, ...this.recruiterOptions.map((x) => ({ id: String(x.id), name: x.name }))];
    this.filteredRecruiterOptions = (search ? base.filter((x) => x.name.toLowerCase().includes(search)) : base).slice(0, 60);
  }

  private refreshRoleFilterOptions(): void {
    const search = this.roleQuery.trim().toLowerCase();
    const base = [{ id: 'all', name: 'All Roles' }, ...this.roleOptions.map((x) => ({ id: String(x.id), name: x.name }))];
    this.filteredRoleOptions = (search ? base.filter((x) => x.name.toLowerCase().includes(search)) : base).slice(0, 60);
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

  private renderCharts(): boolean {
    let renderedSomething = false;

    const trendCtx = this.trendCanvas?.nativeElement?.getContext('2d');
    if (this.trendCanvas?.nativeElement && trendCtx && this.hasTrendData) {
      if (this.trendChart) {
        this.trendChart.destroy();
        this.trendChart = undefined;
      }
      this.trendChart = new Chart(trendCtx, {
        type: 'line',
        data: {
          labels: this.trend.labels,
          datasets: [
            {
              label: 'Interviews',
              data: this.trend.interviews,
              borderColor: '#3ed2ff',
              backgroundColor: 'rgba(62,210,255,0.15)',
              fill: true,
              tension: 0.3,
              pointRadius: 2.5,
              pointBackgroundColor: '#8de7ff'
            },
            {
              label: 'Hired',
              data: this.trend.hired,
              borderColor: '#43e89f',
              backgroundColor: 'rgba(67,232,159,0.1)',
              fill: false,
              tension: 0.25,
              pointRadius: 2.5,
              pointBackgroundColor: '#b8ffd5'
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { labels: { color: '#9fc5e2' } }
          },
          scales: {
            x: { ticks: { color: '#8fb4d8' }, grid: { color: 'rgba(111,170,214,0.12)' } },
            y: { beginAtZero: true, ticks: { color: '#8fb4d8', stepSize: 1 }, grid: { color: 'rgba(111,170,214,0.12)' } }
          }
        }
      });
      renderedSomething = true;
    } else if (this.trendChart) {
      this.trendChart.destroy();
      this.trendChart = undefined;
    }

    const statusCtx = this.statusCanvas?.nativeElement?.getContext('2d');
    if (this.statusCanvas?.nativeElement && statusCtx && this.hasStatusData) {
      if (this.statusChart) {
        this.statusChart.destroy();
        this.statusChart = undefined;
      }
      this.statusChart = new Chart(statusCtx, {
        type: 'doughnut',
        data: {
          labels: this.statusSplit.map((x) => x.label),
          datasets: [{ data: this.statusSplit.map((x) => x.value), backgroundColor: this.statusSplit.map((x) => x.color) }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '62%',
          plugins: { legend: { display: false } }
        }
      });
      renderedSomething = true;
    } else if (this.statusChart) {
      this.statusChart.destroy();
      this.statusChart = undefined;
    }
    return renderedSomething || (!this.hasTrendData && !this.hasStatusData);
  }
}
