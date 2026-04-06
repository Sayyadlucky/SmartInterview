import { AfterViewInit, ChangeDetectionStrategy, ChangeDetectorRef, Component, ElementRef, HostListener, NgZone, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpParams } from '@angular/common/http';
import { catchError, of, timeout } from 'rxjs';
import { Chart, registerables } from 'chart.js';
import { getApiBaseUrl } from '../core/api-base';

Chart.register(...registerables);

interface AnalyticsResponse {
  Success: boolean;
  Error?: string | null;
  Data?: {
    summary?: {
      total_interviews?: number;
      hires?: number;
      hire_rate?: number;
      open_roles?: number;
      avg_time_to_hire_days?: number;
      median_time_to_hire_days?: number;
    };
    funnel?: {
      labels?: string[];
      values?: number[];
      conversions?: Array<{ from: string; to: string; rate: number }>;
    };
    time_to_hire?: {
      avg_days?: number;
      median_days?: number;
      monthly_labels?: string[];
      monthly_avg_days?: number[];
      monthly_hires?: number[];
      monthly_total_hires?: number[];
    };
    source_effectiveness?: Array<{ source: string; total: number; hired: number; conversion: number }>;
    recruiter_performance?: Array<{ name: string; interviews: number; hired: number; conversion: number }>;
    role_health?: Array<{ role: string; target: number; filled: number; pipeline: number; risk: number }>;
    interview_quality?: {
      evaluated?: number;
      score_bands?: Record<string, number>;
    };
    dropoff_analysis?: {
      total_dropoffs?: number;
      rejected?: number;
      cancelled?: number;
      no_show?: number;
      screening_timeout?: number;
      by_role?: Array<{ role: string; dropoffs: number; drop_rate: number }>;
    };
    offer_acceptance?: {
      offers_made?: number;
      offers_accepted?: number;
      offers_pending?: number;
      acceptance_rate?: number;
      monthly_labels?: string[];
      monthly_offers?: number[];
      monthly_accepted?: number[];
    };
    sla_compliance?: {
      active_pipeline?: number;
      breached?: number;
      compliance_rate?: number;
      breakdown?: Array<{ label: string; count: number }>;
      breach_candidates?: Array<{ candidate_name: string; role?: string; breach_label: string }>;
    };
    executive_insights?: string[];
    forecast_vs_target?: {
      current_target?: number;
      current_hired?: number;
      monthly_target?: number;
      open_demand_target?: number;
      next_labels?: string[];
      projected_hires?: number[];
      expected_gap_next_month?: number;
      projection_basis?: string;
      delivery_status?: string;
      delivery_ratio?: number;
    };
    anomaly_flags?: Array<{ severity: 'high' | 'medium' | 'low'; title: string; detail: string }>;
    executive_snapshot?: {
      generated_at?: string;
      filters?: { recruiter?: string; role?: string; start_date?: string; end_date?: string };
      kpis?: {
        total_interviews?: number;
        hire_rate?: number;
        dropoff_rate?: number;
        sla_compliance_rate?: number;
        offer_acceptance_rate?: number;
      };
    };
    filter_options?: {
      recruiters?: Array<{ id: number; name: string }>;
      roles?: Array<{ id: number; name: string }>;
    };
    phase_meta?: {
      implemented?: number[];
      pending?: number[];
      note?: string;
    };
  };
}

type SignalSeverity = 'critical' | 'at_risk' | 'warning' | 'positive' | 'info';
type Tone = 'critical' | 'at_risk' | 'warning' | 'positive' | 'neutral' | 'info';
type SeverityTab = 'all' | SignalSeverity;

interface AnalyticsBriefSignal {
  key: string;
  severity: SignalSeverity;
  title: string;
  message: string;
  metric: string;
  confidenceLabel: 'High' | 'Medium' | 'Low';
  confidenceTone: Tone;
  evidenceLabel: string;
  evidenceCount: number;
  sortWeight: number;
  ctaLabel?: string;
  actionTarget?: string;
}

interface AnalyticsSummaryCard {
  label: string;
  value: string;
  helper: string;
  status: string;
  tone: Tone;
  icon: string;
}

interface ExecutiveAction {
  label: string;
  detail: string;
  tone: Tone;
  target?: string;
}

interface AnomalySummary {
  count: number;
  topSeverity: SignalSeverity | 'none';
  headline: string;
  helper: string;
}

interface ForecastSummary {
  status: string;
  tone: Tone;
  headline: string;
  helper: string;
  metric: string;
  basis: string;
}

interface SourceHighlights {
  best?: { source: string; conversion: number; hired: number };
  weakest?: { source: string; conversion: number; total: number };
  note: string;
}

interface RecruiterHighlights {
  leader?: { name: string; conversion: number; hired: number };
  support?: { name: string; conversion: number; interviews: number };
  note: string;
}

interface RoleRiskHighlights {
  highestRisk?: { role: string; risk: number; pipeline: number };
  strongest?: { role: string; filled: number; target: number };
  note: string;
}

interface AnalyticsChangeSignal {
  label: string;
  value: string;
  direction: 'up' | 'down' | 'flat' | 'alert' | 'positive';
  helper: string;
  tone: Tone;
}

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './analytics.html',
  styleUrl: './analytics.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class Analytics implements OnInit, AfterViewInit, OnDestroy {
  loading = false;
  errorMessage = '';
  initialized = false;

  summary = {
    total_interviews: 0,
    hires: 0,
    hire_rate: 0,
    open_roles: 0,
    avg_time_to_hire_days: 0,
    median_time_to_hire_days: 0,
  };
  funnel = {
    labels: [] as string[],
    values: [] as number[],
    conversions: [] as Array<{ from: string; to: string; rate: number }>,
  };
  timeToHire = {
    avg_days: 0,
    median_days: 0,
    monthly_labels: [] as string[],
    monthly_avg_days: [] as number[],
    monthly_hires: [] as number[],
    monthly_total_hires: [] as number[],
  };
  sourceEffectiveness: Array<{ source: string; total: number; hired: number; conversion: number }> = [];
  recruiterPerformance: Array<{ name: string; interviews: number; hired: number; conversion: number }> = [];
  roleHealth: Array<{ role: string; target: number; filled: number; pipeline: number; risk: number }> = [];
  interviewQuality = {
    evaluated: 0,
    score_bands: {} as Record<string, number>,
  };
  dropoffAnalysis = {
    total_dropoffs: 0,
    rejected: 0,
    cancelled: 0,
    no_show: 0,
    screening_timeout: 0,
    by_role: [] as Array<{ role: string; dropoffs: number; drop_rate: number }>,
  };
  offerAcceptance = {
    offers_made: 0,
    offers_accepted: 0,
    offers_pending: 0,
    acceptance_rate: 0,
    monthly_labels: [] as string[],
    monthly_offers: [] as number[],
    monthly_accepted: [] as number[],
  };
  slaCompliance = {
    active_pipeline: 0,
    breached: 0,
    compliance_rate: 100,
    breakdown: [] as Array<{ label: string; count: number }>,
    breach_candidates: [] as Array<{ candidate_name: string; role?: string; breach_label: string }>,
  };
  executiveInsights: string[] = [];
  showDropoffDetailsModal = false;
  showSlaDetailsModal = false;
  forecastVsTarget = {
    current_target: 0,
    current_hired: 0,
    monthly_target: 0,
    open_demand_target: 0,
    next_labels: [] as string[],
    projected_hires: [] as number[],
    expected_gap_next_month: 0,
    projection_basis: '',
    delivery_status: 'Monitoring',
    delivery_ratio: 0,
  };
  anomalyFlags: Array<{ severity: 'high' | 'medium' | 'low'; title: string; detail: string }> = [];
  executiveSnapshot = {
    generated_at: '',
    filters: { recruiter: 'all', role: 'all', start_date: '', end_date: '' },
    kpis: {
      total_interviews: 0,
      hire_rate: 0,
      dropoff_rate: 0,
      sla_compliance_rate: 0,
      offer_acceptance_rate: 0,
    }
  };
  phaseMeta = {
    implemented: [] as number[],
    pending: [] as number[],
    note: '',
  };

  recruiterOptions: Array<{ id: number; name: string }> = [];
  roleOptions: Array<{ id: number; name: string }> = [];
  filteredRecruiterOptions: Array<{ id: string; name: string }> = [];
  filteredRoleOptions: Array<{ id: string; name: string }> = [];
  selectedRecruiter = 'all';
  selectedRole = 'all';
  recruiterQuery = 'All Recruiters';
  roleQuery = 'All Roles';
  showRecruiterMenu = false;
  showRoleMenu = false;
  startDate = '';
  endDate = '';
  dateRangeError = '';

  activeSeverityTab: SeverityTab = 'critical';
  analyticsBriefSignals: AnalyticsBriefSignal[] = [];
  analyticsChangeSignals: AnalyticsChangeSignal[] = [];
  availableSeverityTabs: Array<{ key: SeverityTab; label: string; count: number }> = [];
  signalHealthSummary: Array<{ severity: SignalSeverity; count: number }> = [];
  visibleAnalyticsBriefSignals: AnalyticsBriefSignal[] = [];
  primaryAnalyticsSignal: AnalyticsBriefSignal | null = null;
  secondaryAnalyticsSignals: AnalyticsBriefSignal[] = [];
  analyticsSummaryCards: AnalyticsSummaryCard[] = [];
  executiveActions: ExecutiveAction[] = [];
  anomalySummary: AnomalySummary = {
    count: 0,
    topSeverity: 'none',
    headline: 'No anomaly signal',
    helper: 'The current filter set is not surfacing flagged risk patterns.',
  };
  forecastSummary: ForecastSummary = {
    status: 'Monitoring',
    tone: 'neutral',
    headline: 'Awaiting forecast signal',
    helper: 'Projection data will appear here when hires and targets are available.',
    metric: 'No projection',
    basis: '',
  };
  sourceHighlights: SourceHighlights = { note: 'No candidate origin signal yet.' };
  recruiterHighlights: RecruiterHighlights = { note: 'No recruiter efficiency signal yet.' };
  roleRiskHighlights: RoleRiskHighlights = { note: 'No role risk signal yet.' };
  analystInsightCards: string[] = [];

  funnelCanvas?: ElementRef<HTMLCanvasElement>;
  tthCanvas?: ElementRef<HTMLCanvasElement>;

  @ViewChild('funnelCanvas', { static: false })
  set funnelCanvasRef(value: ElementRef<HTMLCanvasElement> | undefined) {
    this.funnelCanvas = value;
    if (value && this.initialized && !this.loading) {
      this.scheduleChartRender();
    }
  }

  @ViewChild('tthCanvas', { static: false })
  set tthCanvasRef(value: ElementRef<HTMLCanvasElement> | undefined) {
    this.tthCanvas = value;
    if (value && this.initialized && !this.loading) {
      this.scheduleChartRender();
    }
  }

  private funnelChart?: Chart;
  private tthChart?: Chart;
  private filterTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private chartRetryTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private chartAnimationFrameId: number | null = null;
  private sectionHighlightTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private readonly tabListener = (event: Event) => {
    const e = event as CustomEvent;
    if (e?.detail?.tab === 'analytics') {
      this.zone.run(() => this.ensureInitialized());
    }
  };
  private readonly statusUpdateListener = () => {
    this.zone.run(() => {
      if (this.initialized) this.loadAnalyticsData();
    });
  };

  constructor(
    private http: HttpClient,
    private cdr: ChangeDetectorRef,
    private zone: NgZone,
  ) {}

  ngOnInit(): void {
    window.addEventListener('dashboard-tab-change', this.tabListener as EventListener);
    window.addEventListener('candidate-status-updated', this.statusUpdateListener as EventListener);
    window.addEventListener('global-data-refresh', this.statusUpdateListener as EventListener);
    const isActiveOnInit = !!document.querySelector('#analytics.tab-content.active');
    if (isActiveOnInit) this.ensureInitialized();
  }

  ngAfterViewInit(): void {
    this.scheduleChartRender();
  }

  ngOnDestroy(): void {
    window.removeEventListener('dashboard-tab-change', this.tabListener as EventListener);
    window.removeEventListener('candidate-status-updated', this.statusUpdateListener as EventListener);
    window.removeEventListener('global-data-refresh', this.statusUpdateListener as EventListener);
    if (this.filterTimeoutId) clearTimeout(this.filterTimeoutId);
    if (this.chartRetryTimeoutId) clearTimeout(this.chartRetryTimeoutId);
    if (this.sectionHighlightTimeoutId) clearTimeout(this.sectionHighlightTimeoutId);
    if (this.chartAnimationFrameId !== null) cancelAnimationFrame(this.chartAnimationFrameId);
    this.destroyCharts();
  }

  @HostListener('document:keydown.escape')
  onEscapeKey(): void {
    if (this.showDropoffDetailsModal) {
      this.closeDropoffDetailsModal();
      return;
    }
    if (this.showSlaDetailsModal) {
      this.closeSlaDetailsModal();
    }
  }

  get hasFunnelData(): boolean {
    return this.funnel.values.some((x) => x > 0);
  }

  get hasTimeToHireTrend(): boolean {
    return this.timeToHire.monthly_avg_days.some((x) => x > 0) || this.timeToHire.monthly_hires.some((x) => x > 0);
  }

  get hasForecastProjection(): boolean {
    return this.forecastVsTarget.next_labels.length > 0 && this.forecastVsTarget.projected_hires.some((x) => x > 0);
  }

  get qualityRows(): Array<{ label: string; value: number }> {
    return Object.entries(this.interviewQuality.score_bands || {})
      .map(([label, value]) => ({ label, value: Number(value || 0) }))
      .filter((x) => x.value > 0);
  }

  get funnelHelperText(): string {
    const weakest = this.getWeakestFunnelConversion();
    if (!weakest) return 'Track where candidate volume is falling away between stages.';
    return `${weakest.from} to ${weakest.to} is the weakest transition at ${this.formatPercent(weakest.rate)}.`;
  }

  get weakestFunnelConversionRate(): number {
    return this.getWeakestFunnelConversion()?.rate || 0;
  }

  get timeToHireHelperText(): string {
    if (!this.hasTimeToHireTrend) return 'Trend data will appear here once monthly pacing is available.';
    const comparison = this.summary.avg_time_to_hire_days - this.summary.median_time_to_hire_days;
    if (comparison > 2) return `Average cycle time is running ${comparison.toFixed(0)}d above the median pace.`;
    if (comparison < -2) return `Average cycle time is tracking ${Math.abs(comparison).toFixed(0)}d faster than the median pace.`;
    return 'Average and median cycle times are moving in a stable band.';
  }

  get forecastHelperText(): string {
    return this.forecastSummary.helper;
  }

  get currentDeliveryStatus(): string {
    return this.forecastVsTarget.delivery_status || 'Monitoring';
  }

  get currentDeliveryMetric(): string {
    const target = this.forecastVsTarget.current_target;
    const hired = this.forecastVsTarget.current_hired;
    if (!target) return `${hired} hires`;
    const ratioPct = Math.round((this.forecastVsTarget.delivery_ratio || 0) * 100);
    return hired > target ? `${hired} / ${target} hired (${ratioPct}%)` : `${hired} / ${target} hired`;
  }

  get anomalyHelperText(): string {
    if (!this.anomalyFlags.length) return 'No anomaly flags are currently elevated for the selected view.';
    return this.anomalySummary.helper;
  }

  setActiveSeverityTab(tab: SeverityTab): void {
    this.activeSeverityTab = tab;
    this.updateVisibleAnalyticsSignals();
  }

  formatRoleWithId(role: string, roleId?: number | string | null): string {
    const roleName = (role || '').toString().trim();
    const id = (roleId ?? '').toString().trim();
    if (!roleName) return id;
    return id ? `${roleName} - ${id}` : roleName;
  }

  ensureInitialized(): void {
    if (this.initialized) return;
    this.initialized = true;
    this.cdr.markForCheck();
    this.loadAnalyticsData();
  }

  onFiltersChanged(): void {
    if (this.startDate && this.endDate && this.startDate > this.endDate) {
      this.dateRangeError = 'From date cannot be greater than To date.';
      return;
    }
    this.dateRangeError = '';
    if (this.filterTimeoutId) clearTimeout(this.filterTimeoutId);
    this.filterTimeoutId = setTimeout(() => this.loadAnalyticsData(), 250);
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
    this.recruiterQuery = 'All Recruiters';
    this.roleQuery = 'All Roles';
    this.showRecruiterMenu = false;
    this.showRoleMenu = false;
    this.startDate = '';
    this.endDate = '';
    this.dateRangeError = '';
    this.refreshRecruiterFilterOptions();
    this.refreshRoleFilterOptions();
    this.loadAnalyticsData();
  }

  exportSnapshot(format: 'json' | 'csv'): void {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    if (format === 'json') {
      const payload = {
        generated_at: this.executiveSnapshot.generated_at || new Date().toISOString(),
        filters: this.executiveSnapshot.filters,
        summary: this.summary,
        forecast_vs_target: this.forecastVsTarget,
        anomaly_flags: this.anomalyFlags,
        kpis: this.executiveSnapshot.kpis,
      };
      this.downloadBlob(JSON.stringify(payload, null, 2), `analytics-snapshot-${stamp}.json`, 'application/json');
      return;
    }

    const rows: string[] = [];
    rows.push('section,key,value');
    rows.push(`summary,total_interviews,${this.summary.total_interviews}`);
    rows.push(`summary,hire_rate,${this.summary.hire_rate}`);
    rows.push(`forecast,current_target,${this.forecastVsTarget.current_target}`);
    rows.push(`forecast,current_hired,${this.forecastVsTarget.current_hired}`);
    rows.push(`forecast,monthly_target,${this.forecastVsTarget.monthly_target}`);
    rows.push(`forecast,expected_gap_next_month,${this.forecastVsTarget.expected_gap_next_month}`);
    this.anomalyFlags.forEach((f, idx) => rows.push(`anomaly_${idx + 1},${this.escapeCsv(f.title)},${this.escapeCsv(f.detail)}`));
    this.downloadBlob(rows.join('\n'), `analytics-snapshot-${stamp}.csv`, 'text/csv;charset=utf-8;');
  }

  getSignalClass(severity: SignalSeverity): string {
    return `severity-${severity.replace('_', '-')}`;
  }

  getToneClass(tone: Tone): string {
    return `tone-${tone.replace('_', '-')}`;
  }

  getBadgeClass(severity: SignalSeverity): string {
    return `badge-${severity.replace('_', '-')}`;
  }

  getSeverityLabel(severity: SignalSeverity): string {
    return severity === 'at_risk' ? 'At Risk' : severity.charAt(0).toUpperCase() + severity.slice(1);
  }

  getAnomalyClass(severity: 'high' | 'medium' | 'low'): string {
    return severity === 'high' ? 'severity-critical' : severity === 'medium' ? 'severity-warning' : 'severity-info';
  }

  getForecastProgress(): number {
    return Math.max(0, Math.min(100, (this.forecastVsTarget.delivery_ratio || 0) * 100));
  }

  getProjectionWidth(value: number): string {
    const max = Math.max(...this.forecastVsTarget.projected_hires, this.forecastVsTarget.monthly_target, 1);
    return `${Math.max(8, (value / max) * 100)}%`;
  }

  getFilterSummary(): string {
    const recruiter = this.selectedRecruiter === 'all' ? 'All recruiters' : this.recruiterQuery;
    const role = this.selectedRole === 'all' ? 'All roles' : this.roleQuery;
    const range = this.startDate || this.endDate ? `${this.startDate || 'Start'} to ${this.endDate || 'Now'}` : 'All dates';
    return `${recruiter} • ${role} • ${range}`;
  }

  handleSignalAction(signal: AnalyticsBriefSignal): void {
    if (signal.key === 'anomaly_severity' && this.shouldOpenDropoffModalFromAnomalies()) {
      this.navigateToAnalyticsTarget('dropoffs');
      window.setTimeout(() => this.openDropoffDetailsModal(), 260);
      return;
    }
    this.navigateToAnalyticsTarget(signal.actionTarget);
  }

  handleExecutiveAction(action: ExecutiveAction): void {
    if (action.target === 'anomalies' && this.shouldOpenDropoffModalFromAnomalies()) {
      this.navigateToAnalyticsTarget('dropoffs');
      window.setTimeout(() => this.openDropoffDetailsModal(), 260);
      return;
    }
    this.navigateToAnalyticsTarget(action.target);
  }

  openSlaDetailsModal(): void {
    if (!this.slaCompliance.breach_candidates.length) return;
    this.showSlaDetailsModal = true;
    document.body.style.overflow = 'hidden';
    this.cdr.markForCheck();
  }

  closeSlaDetailsModal(): void {
    this.showSlaDetailsModal = false;
    document.body.style.overflow = '';
    this.cdr.markForCheck();
  }

  openDropoffDetailsModal(): void {
    if (!this.dropoffAnalysis.by_role.length) return;
    this.showDropoffDetailsModal = true;
    document.body.style.overflow = 'hidden';
    this.cdr.markForCheck();
  }

  closeDropoffDetailsModal(): void {
    this.showDropoffDetailsModal = false;
    document.body.style.overflow = '';
    this.cdr.markForCheck();
  }

  private loadAnalyticsData(): void {
    if (!this.initialized) return;
    this.loading = true;
    this.errorMessage = '';

    let params = new HttpParams();
    if (this.selectedRecruiter !== 'all') params = params.set('recruiter', this.selectedRecruiter);
    if (this.selectedRole !== 'all') params = params.set('role', this.selectedRole);
    if (this.startDate) params = params.set('start_date', this.startDate);
    if (this.endDate) params = params.set('end_date', this.endDate);

    this.http.get<AnalyticsResponse>(`${getApiBaseUrl()}/analytics-tab-data/`, { params })
      .pipe(
        timeout(15000),
        catchError((error) => {
          console.error('Error fetching analytics data', error);
          this.loading = false;
          this.errorMessage = error?.name === 'TimeoutError'
            ? 'Analytics request timed out. Try a narrower filter range.'
            : 'Unable to load analytics data.';
          this.cdr.markForCheck();
          return of({ Success: false, Data: {} } as AnalyticsResponse);
        })
      )
      .subscribe((response) => {
        if (!response?.Success) {
          this.errorMessage = response?.Error || 'Unable to load analytics data.';
          this.loading = false;
          this.cdr.markForCheck();
          return;
        }

        const data = response.Data || {};
        this.summary = { ...this.summary, ...(data.summary || {}) };
        this.funnel = {
          labels: data.funnel?.labels || [],
          values: data.funnel?.values || [],
          conversions: data.funnel?.conversions || [],
        };
        this.timeToHire = {
          avg_days: data.time_to_hire?.avg_days || 0,
          median_days: data.time_to_hire?.median_days || 0,
          monthly_labels: data.time_to_hire?.monthly_labels || [],
          monthly_avg_days: data.time_to_hire?.monthly_avg_days || [],
          monthly_hires: data.time_to_hire?.monthly_hires || [],
          monthly_total_hires: data.time_to_hire?.monthly_total_hires || [],
        };
        this.sourceEffectiveness = data.source_effectiveness || [];
        this.recruiterPerformance = data.recruiter_performance || [];
        this.roleHealth = data.role_health || [];
        this.interviewQuality = {
          evaluated: data.interview_quality?.evaluated || 0,
          score_bands: data.interview_quality?.score_bands || {},
        };
        this.dropoffAnalysis = {
          total_dropoffs: data.dropoff_analysis?.total_dropoffs || 0,
          rejected: data.dropoff_analysis?.rejected || 0,
          cancelled: data.dropoff_analysis?.cancelled || 0,
          no_show: data.dropoff_analysis?.no_show || 0,
          screening_timeout: data.dropoff_analysis?.screening_timeout || 0,
          by_role: data.dropoff_analysis?.by_role || [],
        };
        this.offerAcceptance = {
          offers_made: data.offer_acceptance?.offers_made || 0,
          offers_accepted: data.offer_acceptance?.offers_accepted || 0,
          offers_pending: data.offer_acceptance?.offers_pending || 0,
          acceptance_rate: data.offer_acceptance?.acceptance_rate || 0,
          monthly_labels: data.offer_acceptance?.monthly_labels || [],
          monthly_offers: data.offer_acceptance?.monthly_offers || [],
          monthly_accepted: data.offer_acceptance?.monthly_accepted || [],
        };
        this.slaCompliance = {
          active_pipeline: data.sla_compliance?.active_pipeline || 0,
          breached: data.sla_compliance?.breached || 0,
          compliance_rate: data.sla_compliance?.compliance_rate || 100,
          breakdown: data.sla_compliance?.breakdown || [],
          breach_candidates: data.sla_compliance?.breach_candidates || [],
        };
        this.executiveInsights = data.executive_insights || [];
        this.forecastVsTarget = {
          current_target: data.forecast_vs_target?.current_target || 0,
          current_hired: data.forecast_vs_target?.current_hired || 0,
          monthly_target: data.forecast_vs_target?.monthly_target || 0,
          open_demand_target: data.forecast_vs_target?.open_demand_target || 0,
          next_labels: data.forecast_vs_target?.next_labels || [],
          projected_hires: data.forecast_vs_target?.projected_hires || [],
          expected_gap_next_month: data.forecast_vs_target?.expected_gap_next_month || 0,
          projection_basis: data.forecast_vs_target?.projection_basis || '',
          delivery_status: data.forecast_vs_target?.delivery_status || 'Monitoring',
          delivery_ratio: data.forecast_vs_target?.delivery_ratio || 0,
        };
        this.anomalyFlags = data.anomaly_flags || [];
        this.executiveSnapshot = {
          generated_at: data.executive_snapshot?.generated_at || '',
          filters: {
            recruiter: data.executive_snapshot?.filters?.recruiter || 'all',
            role: data.executive_snapshot?.filters?.role || 'all',
            start_date: data.executive_snapshot?.filters?.start_date || '',
            end_date: data.executive_snapshot?.filters?.end_date || '',
          },
          kpis: {
            total_interviews: data.executive_snapshot?.kpis?.total_interviews || 0,
            hire_rate: data.executive_snapshot?.kpis?.hire_rate || 0,
            dropoff_rate: data.executive_snapshot?.kpis?.dropoff_rate || 0,
            sla_compliance_rate: data.executive_snapshot?.kpis?.sla_compliance_rate || 0,
            offer_acceptance_rate: data.executive_snapshot?.kpis?.offer_acceptance_rate || 0,
          }
        };
        this.phaseMeta = {
          implemented: data.phase_meta?.implemented || [],
          pending: data.phase_meta?.pending || [],
          note: data.phase_meta?.note || '',
        };

        this.recruiterOptions = data.filter_options?.recruiters || this.recruiterOptions;
        this.roleOptions = data.filter_options?.roles || this.roleOptions;
        this.syncFilterInputLabels();
        this.refreshRecruiterFilterOptions();
        this.refreshRoleFilterOptions();
        try {
          this.refreshPresentationModels();
        } catch (error) {
          console.error('Error preparing analytics presentation models', error);
          this.resetPresentationModels();
        } finally {
          this.loading = false;
          this.cdr.markForCheck();
          this.scheduleChartRender();
        }
      });
  }

  private refreshPresentationModels(): void {
    this.sourceHighlights = this.buildSourceHighlights();
    this.recruiterHighlights = this.buildRecruiterHighlights();
    this.roleRiskHighlights = this.buildRoleRiskHighlights();
    this.anomalySummary = this.buildAnomalySummary();
    this.forecastSummary = this.buildForecastSummary();
    this.analyticsBriefSignals = this.buildAnalyticsBriefSignals();
    this.analyticsChangeSignals = this.buildAnalyticsChangeSignals();
    this.analyticsSummaryCards = this.buildAnalyticsSummaryCards();
    this.executiveActions = this.buildExecutiveActions();
    this.analystInsightCards = this.buildAnalystInsightCards();
    this.availableSeverityTabs = this.buildSeverityTabs();
    this.signalHealthSummary = this.buildSignalHealthSummary();
    this.ensureValidActiveSeverityTab();
    this.updateVisibleAnalyticsSignals();
  }

  private resetPresentationModels(): void {
    this.activeSeverityTab = 'critical';
    this.analyticsBriefSignals = [];
    this.analyticsChangeSignals = [];
    this.analyticsSummaryCards = this.buildAnalyticsSummaryCards();
    this.executiveActions = [];
    this.analystInsightCards = [...this.executiveInsights].slice(0, 6);
    this.sourceHighlights = this.buildSourceHighlights();
    this.recruiterHighlights = this.buildRecruiterHighlights();
    this.roleRiskHighlights = this.buildRoleRiskHighlights();
    this.anomalySummary = this.buildAnomalySummary();
    this.forecastSummary = this.buildForecastSummary();
    this.availableSeverityTabs = this.buildSeverityTabs();
    this.signalHealthSummary = this.buildSignalHealthSummary();
    this.updateVisibleAnalyticsSignals();
  }

  private buildAnalyticsBriefSignals(): AnalyticsBriefSignal[] {
    const signals: AnalyticsBriefSignal[] = [];

    const weakestFunnel = this.getWeakestFunnelConversion();
    if (weakestFunnel) {
      const severity: SignalSeverity = weakestFunnel.rate < 35 ? 'critical' : weakestFunnel.rate < 60 ? 'at_risk' : 'positive';
      const evidenceCount = Math.max(...this.funnel.values, 0);
      signals.push(this.createBriefSignal({
        key: 'funnel_leakage',
        severity,
        title: 'Funnel Leakage Signal',
        message: `${weakestFunnel.from} to ${weakestFunnel.to} is the softest step in the funnel.`,
        metric: `${this.formatPercent(weakestFunnel.rate)} conversion`,
        evidenceCount,
        evidenceLabel: `${evidenceCount} candidates across tracked funnel stages`,
        ctaLabel: 'Audit stage',
        actionTarget: weakestFunnel.to,
      }));
    }

    const avg = this.summary.avg_time_to_hire_days || this.timeToHire.avg_days;
    const median = this.summary.median_time_to_hire_days || this.timeToHire.median_days;
    if (avg || median) {
      const diff = avg - median;
      const severity: SignalSeverity = diff > 5 ? 'at_risk' : diff < -3 ? 'positive' : 'info';
      const evidenceCount = this.timeToHire.monthly_avg_days.filter((value) => value > 0).length;
      signals.push(this.createBriefSignal({
        key: 'hiring_slowdown',
        severity,
        title: 'Hiring Slowdown Signal',
        message: diff > 5
          ? 'Current hiring pace is stretching beyond the median cycle time.'
          : diff < -3
            ? 'Current hiring pace is beating the recent median cycle time.'
            : 'Cycle times are moving in a relatively stable band.',
        metric: `${this.formatDays(avg)} avg vs ${this.formatDays(median)} median`,
        evidenceCount,
        evidenceLabel: evidenceCount > 0 ? `${evidenceCount} monthly pacing points analyzed` : 'Current average compared with median cycle baseline',
        ctaLabel: 'Review pacing',
        actionTarget: 'time-to-hire',
      }));
    }

    if (this.roleRiskHighlights.highestRisk) {
      const role = this.roleRiskHighlights.highestRisk;
      const matchingRole = this.roleHealth.find((item) => item.role === role.role);
      const evidenceCount = (matchingRole?.pipeline || 0) + (matchingRole?.target || 0);
      signals.push(this.createBriefSignal({
        key: 'role_risk',
        severity: role.risk >= 75 ? 'critical' : role.risk > 50 ? 'at_risk' : 'info',
        title: 'Role Risk Signal',
        message: `${role.role} has the highest risk pressure in the current hiring mix.`,
        metric: `Risk ${this.formatPercent(role.risk)} • pipeline ${role.pipeline}`,
        evidenceCount,
        evidenceLabel: matchingRole
          ? `${matchingRole.pipeline} pipeline coverage against ${matchingRole.target} target`
          : `${role.pipeline} candidates contributing to this role signal`,
        ctaLabel: 'Review roles',
        actionTarget: role.role,
      }));
    }

    if (this.sourceHighlights.best || this.sourceHighlights.weakest) {
      const best = this.sourceHighlights.best;
      const weakest = this.sourceHighlights.weakest;
      const severity: SignalSeverity = weakest && weakest.conversion < 20 ? 'warning' : 'positive';
      const primarySource = best?.source || weakest?.source || '';
      const sourceRecord = this.sourceEffectiveness.find((item) => item.source === primarySource);
      const evidenceCount = sourceRecord?.total || weakest?.total || best?.hired || 0;
      signals.push(this.createBriefSignal({
        key: 'source_quality',
        severity,
        title: 'Candidate Origin Signal',
        message: best && weakest
          ? `${best.source} is outperforming while ${weakest.source} is under-converting.`
          : best
            ? `${best.source} is currently the strongest candidate origin.`
            : `${weakest?.source} needs candidate origin review.`,
        metric: best ? `${best.source} ${this.formatPercent(best.conversion)}` : `${weakest?.source || 'Origin'} ${this.formatPercent(weakest?.conversion || 0)}`,
        evidenceCount,
        evidenceLabel: evidenceCount > 0 ? `${evidenceCount} application-origin candidates evaluated` : 'Candidate origin evidence is limited',
        ctaLabel: 'Inspect origins',
        actionTarget: 'sources',
      }));
    }

    if (this.recruiterHighlights.leader || this.recruiterHighlights.support) {
      const leader = this.recruiterHighlights.leader;
      const support = this.recruiterHighlights.support;
      const anchor = leader?.name || support?.name || '';
      const recruiterRecord = this.recruiterPerformance.find((item) => item.name === anchor);
      const evidenceCount = recruiterRecord?.interviews || support?.interviews || leader?.hired || 0;
      signals.push(this.createBriefSignal({
        key: 'recruiter_efficiency',
        severity: support && leader && leader.conversion - support.conversion >= 20 ? 'warning' : 'info',
        title: 'Recruiter Efficiency Signal',
        message: leader && support
          ? `${leader.name} is leading conversion while ${support.name} may need support or workload balancing.`
          : leader
            ? `${leader.name} is setting the efficiency pace across recruiters.`
            : `${support?.name} may need support to improve throughput.`,
        metric: leader ? `${leader.name} ${this.formatPercent(leader.conversion)}` : `${support?.name || 'Recruiter'} ${this.formatPercent(support?.conversion || 0)}`,
        evidenceCount,
        evidenceLabel: evidenceCount > 0 ? `${evidenceCount} recruiter-owned interviews reviewed` : 'Recruiter evidence is limited',
        ctaLabel: 'Review recruiters',
        actionTarget: 'recruiters',
      }));
    }

    if (this.slaCompliance.active_pipeline || this.slaCompliance.breached) {
      const severity: SignalSeverity =
        this.slaCompliance.compliance_rate === 0 || this.slaCompliance.breached > 0 ? 'critical' :
        this.slaCompliance.compliance_rate < 90 ? 'warning' :
        'positive';
      const evidenceCount = this.slaCompliance.active_pipeline || this.slaCompliance.breached;
      signals.push(this.createBriefSignal({
        key: 'sla_pressure',
        severity,
        title: 'SLA Pressure Signal',
        message: this.slaCompliance.breached > 0
          ? `${this.slaCompliance.breached} active candidates are breaching pipeline SLA expectations.`
          : 'Pipeline SLA coverage is holding without active breaches.',
        metric: `${this.formatPercent(this.slaCompliance.compliance_rate)} compliant`,
        evidenceCount,
        evidenceLabel: `${evidenceCount} active candidates in SLA scope`,
        ctaLabel: 'Address breaches',
        actionTarget: 'sla',
      }));
    }

    if (this.forecastVsTarget.current_target || this.forecastVsTarget.monthly_target || this.forecastVsTarget.expected_gap_next_month) {
      const evidenceCount = this.forecastVsTarget.next_labels.length || (this.forecastVsTarget.current_target ? 1 : 0);
      signals.push(this.createBriefSignal({
        key: 'forecast_gap',
        severity: this.forecastVsTarget.expected_gap_next_month > 0 ? 'at_risk' : 'positive',
        title: 'Forecast Gap Signal',
        message: this.forecastVsTarget.expected_gap_next_month > 0
          ? 'Current pacing indicates a likely hiring gap next month.'
          : 'Current pacing is aligned with hiring targets.',
        metric: this.forecastVsTarget.expected_gap_next_month > 0
          ? `${this.forecastVsTarget.expected_gap_next_month} projected gap`
          : `${this.forecastVsTarget.current_hired}/${this.forecastVsTarget.current_target || this.forecastVsTarget.monthly_target} hires`,
        evidenceCount,
        evidenceLabel: evidenceCount > 1 ? `${evidenceCount} forward projection points in view` : 'Current target and projected pace compared',
        ctaLabel: 'Inspect forecast',
        actionTarget: 'forecast',
      }));
    }

    if (this.anomalyFlags.length) {
      const highCount = this.anomalyFlags.filter((x) => x.severity === 'high').length;
      signals.push(this.createBriefSignal({
        key: 'anomaly_severity',
        severity: highCount > 0 ? 'critical' : 'warning',
        title: 'Anomaly Severity Signal',
        message: highCount > 0
          ? `${highCount} high-severity anomalies need leadership attention.`
          : 'Anomalies exist, but none are at the highest severity.',
        metric: `${this.anomalyFlags.length} total flags`,
        evidenceCount: this.anomalyFlags.length,
        evidenceLabel: `${this.anomalyFlags.length} anomaly flags evaluated`,
        ctaLabel: 'Review anomalies',
        actionTarget: 'anomalies',
      }));
    }

    if (this.offerAcceptance.offers_made || this.offerAcceptance.offers_pending) {
      const severity: SignalSeverity =
        this.offerAcceptance.acceptance_rate < 50 ? 'warning' :
        this.offerAcceptance.acceptance_rate >= 75 ? 'positive' :
        'info';
      const evidenceCount = this.offerAcceptance.offers_made || this.offerAcceptance.offers_accepted;
      signals.push(this.createBriefSignal({
        key: 'offer_acceptance',
        severity,
        title: 'Offer Stage Health',
        message: this.offerAcceptance.acceptance_rate < 50
          ? 'Shortlist-to-hire progression is soft and may threaten near-term hiring goals.'
          : this.offerAcceptance.acceptance_rate >= 75
            ? 'Shortlist-to-hire progression is supporting current hiring momentum.'
            : 'Offer-stage progression is holding but should be monitored.',
        metric: `${this.formatPercent(this.offerAcceptance.acceptance_rate)} accepted`,
        evidenceCount,
        evidenceLabel: `${evidenceCount} shortlist and hire-stage records included in this view`,
        ctaLabel: 'Review offers',
        actionTarget: 'offers',
      }));
    }

    return [...signals].sort((a, b) => b.sortWeight - a.sortWeight || b.evidenceCount - a.evidenceCount).slice(0, 8);
  }

  private buildAnalyticsChangeSignals(): AnalyticsChangeSignal[] {
    const changes: AnalyticsChangeSignal[] = [];
    const avgVsMedian = (this.summary.avg_time_to_hire_days || this.timeToHire.avg_days) - (this.summary.median_time_to_hire_days || this.timeToHire.median_days);
    const weakestFunnel = this.getWeakestFunnelConversion();
    const dropoffRate = this.summary.total_interviews > 0 ? (this.dropoffAnalysis.total_dropoffs / this.summary.total_interviews) * 100 : 0;

    changes.push({
      label: 'Hiring Pace',
      value: avgVsMedian > 2 ? 'Running slower' : avgVsMedian < -2 ? 'Running faster' : 'Holding steady',
      direction: avgVsMedian > 2 ? 'alert' : avgVsMedian < -2 ? 'positive' : 'flat',
      helper: avgVsMedian > 2
        ? `${Math.round(avgVsMedian)}d slower than median cycle`
        : avgVsMedian < -2
          ? `${Math.round(Math.abs(avgVsMedian))}d faster than median cycle`
          : 'Average and median cycle are closely aligned',
      tone: avgVsMedian > 2 ? 'at_risk' : avgVsMedian < -2 ? 'positive' : 'neutral',
    });

    if (weakestFunnel) {
      changes.push({
        label: 'Funnel Efficiency',
        value: `${weakestFunnel.from} → ${weakestFunnel.to}`,
        direction: weakestFunnel.rate < 35 ? 'alert' : weakestFunnel.rate < 60 ? 'down' : 'positive',
        helper: `${this.formatPercent(weakestFunnel.rate)} conversion at the weakest stage`,
        tone: weakestFunnel.rate < 35 ? 'critical' : weakestFunnel.rate < 60 ? 'at_risk' : 'positive',
      });
    }

    changes.push({
      label: 'Drop-off Pressure',
      value: this.formatPercent(dropoffRate),
      direction: dropoffRate > 35 ? 'alert' : dropoffRate > 18 ? 'down' : 'flat',
      helper: dropoffRate > 0 ? `${this.dropoffAnalysis.total_dropoffs} drop-offs across current interview volume` : 'No material drop-off pressure in current view',
      tone: dropoffRate > 35 ? 'at_risk' : dropoffRate > 18 ? 'warning' : 'neutral',
    });

    changes.push({
      label: 'SLA Pressure',
      value: this.slaCompliance.breached > 0 ? `${this.slaCompliance.breached} breached` : 'Low pressure',
      direction: this.slaCompliance.breached > 0 ? 'alert' : 'positive',
      helper: `${this.formatPercent(this.slaCompliance.compliance_rate)} of active pipeline remains within SLA`,
      tone: this.slaCompliance.compliance_rate < 75 ? 'critical' : this.slaCompliance.breached > 0 ? 'warning' : 'positive',
    });

    changes.push({
      label: 'Offer Health',
      value: this.formatPercent(this.offerAcceptance.acceptance_rate),
      direction: this.offerAcceptance.acceptance_rate >= 75 ? 'positive' : this.offerAcceptance.acceptance_rate >= 50 ? 'flat' : 'down',
      helper: this.offerAcceptance.offers_made > 0
        ? `${this.offerAcceptance.offers_made} offers are informing close-rate quality`
        : 'Offer activity is limited in the selected view',
      tone: this.offerAcceptance.acceptance_rate >= 75 ? 'positive' : this.offerAcceptance.acceptance_rate >= 50 ? 'neutral' : 'warning',
    });

    changes.push({
      label: 'Forecast Status',
      value: this.forecastSummary.status,
      direction: this.forecastVsTarget.expected_gap_next_month > 0 ? 'alert' : this.forecastSummary.tone === 'positive' ? 'positive' : 'flat',
      helper: this.forecastVsTarget.expected_gap_next_month > 0
        ? `${this.forecastVsTarget.expected_gap_next_month} hire gap is currently projected`
        : this.forecastSummary.helper,
      tone: this.forecastVsTarget.expected_gap_next_month > 0 ? 'at_risk' : this.forecastSummary.tone,
    });

    return changes.slice(0, 6);
  }

  private buildSeverityTabs(): Array<{ key: SeverityTab; label: string; count: number }> {
    const ordered: SeverityTab[] = ['all', 'critical', 'at_risk', 'warning', 'positive', 'info'];
    return ordered
      .map((key) => ({
        key,
        label: key === 'all' ? 'All' : key === 'at_risk' ? 'At Risk' : key.charAt(0).toUpperCase() + key.slice(1),
        count: key === 'all'
          ? this.analyticsBriefSignals.length
          : this.analyticsBriefSignals.filter((signal) => signal.severity === key).length,
      }))
      .filter((tab) => tab.key === 'all' || tab.count > 0);
  }

  private buildSignalHealthSummary(): Array<{ severity: SignalSeverity; count: number }> {
    return ['critical', 'at_risk', 'warning', 'positive', 'info']
      .map((severity) => ({
        severity: severity as SignalSeverity,
        count: this.analyticsBriefSignals.filter((signal) => signal.severity === severity).length,
      }))
      .filter((item) => item.count > 0);
  }

  private updateVisibleAnalyticsSignals(): void {
    const filtered = this.activeSeverityTab === 'all'
      ? this.analyticsBriefSignals
      : this.analyticsBriefSignals.filter((signal) => signal.severity === this.activeSeverityTab);
    this.visibleAnalyticsBriefSignals = [...filtered].sort(
      (a, b) => b.sortWeight - a.sortWeight || b.evidenceCount - a.evidenceCount || a.title.localeCompare(b.title)
    );
    this.primaryAnalyticsSignal = this.visibleAnalyticsBriefSignals[0] || null;
    this.secondaryAnalyticsSignals = this.visibleAnalyticsBriefSignals.slice(1);
  }

  private ensureValidActiveSeverityTab(): void {
    if (this.availableSeverityTabs.some((tab) => tab.key === this.activeSeverityTab)) return;
    const preferredOrder: SeverityTab[] = ['critical', 'at_risk', 'warning', 'positive', 'info', 'all'];
    this.activeSeverityTab = preferredOrder.find((tab) => this.availableSeverityTabs.some((item) => item.key === tab)) || 'all';
  }

  private buildAnalyticsSummaryCards(): AnalyticsSummaryCard[] {
    const highRiskRoles = this.roleHealth.filter((x) => x.risk >= 60).length;
    const target = this.forecastVsTarget.current_target || this.forecastVsTarget.monthly_target;
    const hiresBehind = target > 0 && this.summary.hires < target;
    const avgVsMedian = this.summary.avg_time_to_hire_days - this.summary.median_time_to_hire_days;

    return [
      {
        label: 'Total Interviews',
        value: this.formatInteger(this.summary.total_interviews),
        helper: this.summary.total_interviews > 0 ? 'Top-of-funnel activity across the selected view.' : 'No interview volume in the selected view.',
        status: this.summary.total_interviews > 0 ? 'active' : 'quiet',
        tone: this.summary.total_interviews > 0 ? 'info' : 'neutral',
        icon: 'ph-chats-teardrop',
      },
      {
        label: 'Hires',
        value: this.formatInteger(this.summary.hires),
        helper: target > 0
          ? `${hiresBehind ? 'Tracking behind' : 'Tracking against'} target of ${target}.`
          : 'Completed hires in the selected view.',
        status: target > 0 ? (hiresBehind ? 'below target' : 'on pace') : 'current',
        tone: target > 0 ? (hiresBehind ? 'warning' : 'positive') : 'info',
        icon: 'ph-handshake',
      },
      {
        label: 'Hire Rate',
        value: this.formatPercent(this.summary.hire_rate),
        helper: this.summary.hire_rate >= 30 ? 'Interview-to-hire conversion is holding well.' : 'Interview-to-hire conversion needs closer review.',
        status: this.summary.hire_rate >= 30 ? 'healthy' : 'at risk',
        tone: this.summary.hire_rate >= 30 ? 'positive' : 'warning',
        icon: 'ph-percent',
      },
      {
        label: 'Open Roles',
        value: this.formatInteger(this.summary.open_roles),
        helper: highRiskRoles > 0 ? `${highRiskRoles} roles show elevated risk.` : 'Open demand is not showing elevated role risk.',
        status: highRiskRoles > 0 ? 'at risk' : 'stable',
        tone: highRiskRoles > 0 ? 'warning' : 'neutral',
        icon: 'ph-briefcase-metal',
      },
      {
        label: 'Avg Time-to-Hire',
        value: this.formatDays(this.summary.avg_time_to_hire_days),
        helper: avgVsMedian > 2 ? 'Cycle time is slower than the median trend.' : avgVsMedian < -2 ? 'Cycle time is improving against the median trend.' : 'Cycle time is stable versus the median trend.',
        status: avgVsMedian > 2 ? 'slowing' : avgVsMedian < -2 ? 'improving' : 'stable',
        tone: avgVsMedian > 2 ? 'warning' : avgVsMedian < -2 ? 'positive' : 'neutral',
        icon: 'ph-timer',
      },
      {
        label: 'Median Time-to-Hire',
        value: this.formatDays(this.summary.median_time_to_hire_days),
        helper: 'Median cycle time sets the current pacing baseline.',
        status: 'baseline',
        tone: 'info',
        icon: 'ph-hourglass-medium',
      }
    ];
  }

  private buildAnomalySummary(): AnomalySummary {
    if (!this.anomalyFlags.length) {
      return {
        count: 0,
        topSeverity: 'none',
        headline: 'No major anomalies detected',
        helper: 'Signals are currently within expected operating ranges for the selected filters.',
      };
    }

    const hasHigh = this.anomalyFlags.some((x) => x.severity === 'high');
    const hasMedium = this.anomalyFlags.some((x) => x.severity === 'medium');
    const topSeverity: SignalSeverity = hasHigh ? 'critical' : hasMedium ? 'warning' : 'info';
    const headline = hasHigh
      ? 'High-severity anomalies are affecting hiring stability'
      : hasMedium
        ? 'Operational anomalies need follow-up'
        : 'Low-severity anomalies are present';

    return {
      count: this.anomalyFlags.length,
      topSeverity,
      headline,
      helper: this.anomalyFlags[0]?.detail || 'Review anomaly details to isolate the cause.',
    };
  }

  private buildForecastSummary(): ForecastSummary {
    const target = this.forecastVsTarget.current_target;
    const hired = this.forecastVsTarget.current_hired;
    const gap = this.forecastVsTarget.expected_gap_next_month;
    const basis = this.forecastVsTarget.projection_basis || 'Projection basis unavailable';
    const deliveryStatus = this.forecastVsTarget.delivery_status || 'Monitoring';
    const deliveryRatio = this.forecastVsTarget.delivery_ratio || 0;
    const deliveryPercent = Math.round(deliveryRatio * 100);

    if (!target && !this.hasForecastProjection) {
      return {
        status: 'Monitoring',
        tone: 'neutral',
        headline: 'Forecast data is limited for this view',
        helper: 'Targets or future projections are not yet available.',
        metric: 'No projection',
        basis,
      };
    }

    let tone: Tone = 'warning';
    if (deliveryStatus === 'Ahead of target' || deliveryStatus === 'At target') {
      tone = 'positive';
    } else if (deliveryStatus === 'In progress' || deliveryStatus === 'Monitoring') {
      tone = 'neutral';
    }

    const metric = !target
      ? `${hired} hires`
      : hired > target
        ? `${hired} / ${target} hired (${deliveryPercent}%)`
        : `${hired} / ${target} hired`;

    return {
      status: deliveryStatus,
      tone,
      headline: deliveryStatus === 'Ahead of target'
        ? 'Current delivery is running ahead of the active target'
        : deliveryStatus === 'At target'
          ? 'Current delivery is aligned with the active target'
          : deliveryStatus === 'In progress'
            ? 'Current delivery is moving toward the active target'
            : deliveryStatus === 'Not started'
              ? 'Current delivery has not started against the active target'
              : 'Forecast data is being monitored for this view',
      helper: gap > 0
        ? `Expected next-month gap is ${gap} hires unless pipeline conversion improves.`
        : 'Projected hiring pace aligns with next-month demand.',
      metric,
      basis,
    };
  }

  private buildSourceHighlights(): SourceHighlights {
    const ranked = [...this.sourceEffectiveness].filter((x) => x.total > 0).sort((a, b) => b.conversion - a.conversion);
    if (!ranked.length) return { note: 'Candidate origin data will surface once application origins are available.' };

    const best = ranked[0];
    const weakest = ranked[ranked.length - 1];
    return {
      best: { source: best.source, conversion: best.conversion, hired: best.hired },
      weakest: { source: weakest.source, conversion: weakest.conversion, total: weakest.total },
      note: `${best.source} is contributing the strongest hire conversion. ${weakest.source} needs closer pipeline review.`,
    };
  }

  private buildRecruiterHighlights(): RecruiterHighlights {
    const ranked = [...this.recruiterPerformance].filter((x) => x.interviews > 0).sort((a, b) => b.conversion - a.conversion);
    if (!ranked.length) return { note: 'Recruiter performance signals will appear once interview ownership data is available.' };

    const leader = ranked[0];
    const support = ranked[ranked.length - 1];
    return {
      leader: { name: leader.name, conversion: leader.conversion, hired: leader.hired },
      support: { name: support.name, conversion: support.conversion, interviews: support.interviews },
      note: `${leader.name} leads on conversion. ${support.name} is the best candidate for coaching or load review.`,
    };
  }

  private buildRoleRiskHighlights(): RoleRiskHighlights {
    if (!this.roleHealth.length) return { note: 'Role risk signals will appear once role pipeline data is available.' };

    const highestRisk = [...this.roleHealth].sort((a, b) => b.risk - a.risk)[0];
    const strongest = [...this.roleHealth].sort((a, b) => (b.filled / Math.max(b.target, 1)) - (a.filled / Math.max(a.target, 1)))[0];

    return {
      highestRisk: { role: highestRisk.role, risk: highestRisk.risk, pipeline: highestRisk.pipeline },
      strongest: { role: strongest.role, filled: strongest.filled, target: strongest.target },
      note: `${highestRisk.role} needs the most attention. ${strongest.role} is closest to or leading against plan.`,
    };
  }

  private buildExecutiveActions(): ExecutiveAction[] {
    const actions: ExecutiveAction[] = [];
    const weakestFunnel = this.getWeakestFunnelConversion();

    if (weakestFunnel && weakestFunnel.rate < 60) {
      actions.push({
        label: 'Audit weakest funnel stage',
        detail: `${weakestFunnel.from} to ${weakestFunnel.to} is leaking candidates.`,
        tone: weakestFunnel.rate < 35 ? 'critical' : 'at_risk',
        target: weakestFunnel.to,
      });
    }

    if (this.roleRiskHighlights.highestRisk && this.roleRiskHighlights.highestRisk.risk >= 45) {
      actions.push({
        label: 'Review high-risk roles',
        detail: `${this.roleRiskHighlights.highestRisk.role} is carrying the highest staffing risk.`,
        tone: this.roleRiskHighlights.highestRisk.risk >= 75 ? 'critical' : 'at_risk',
        target: this.roleRiskHighlights.highestRisk.role,
      });
    }

    if (this.recruiterHighlights.support && this.recruiterHighlights.leader &&
      this.recruiterHighlights.leader.conversion - this.recruiterHighlights.support.conversion >= 15) {
      actions.push({
        label: 'Rebalance recruiter workload',
        detail: `${this.recruiterHighlights.support.name} may need support to close the conversion gap.`,
        tone: 'info',
        target: this.recruiterHighlights.support.name,
      });
    }

    if (this.sourceHighlights.weakest && this.sourceHighlights.weakest.conversion < 20) {
      actions.push({
        label: 'Investigate weak candidate origin',
        detail: `${this.sourceHighlights.weakest.source} is underperforming on hire conversion.`,
        tone: 'at_risk',
        target: this.sourceHighlights.weakest.source,
      });
    }

    if (this.slaCompliance.breached > 0) {
      actions.push({
        label: 'Address SLA breach pockets',
        detail: `${this.slaCompliance.breached} active candidates are already outside SLA.`,
        tone: this.slaCompliance.compliance_rate < 75 ? 'critical' : 'warning',
        target: 'sla',
      });
    }

    if (this.offerAcceptance.offers_made > 0 && this.offerAcceptance.acceptance_rate < 60) {
      actions.push({
        label: 'Review offer acceptance softness',
        detail: `Offer acceptance is ${this.formatPercent(this.offerAcceptance.acceptance_rate)} in the selected view.`,
        tone: 'at_risk',
        target: 'offers',
      });
    }

    if (this.forecastVsTarget.expected_gap_next_month > 0) {
      actions.push({
        label: 'Close forecasted hiring gap',
        detail: `${this.forecastVsTarget.expected_gap_next_month} hires are projected to be missing next month.`,
        tone: 'warning',
        target: 'forecast',
      });
    }

    return actions.slice(0, 5);
  }

  private buildAnalystInsightCards(): string[] {
    const insights = [...this.executiveInsights];
    if (this.forecastSummary.headline && !insights.length) {
      insights.push(this.forecastSummary.headline);
    }
    if (this.sourceHighlights.note) insights.push(this.sourceHighlights.note);
    if (this.recruiterHighlights.note) insights.push(this.recruiterHighlights.note);
    if (this.roleRiskHighlights.note) insights.push(this.roleRiskHighlights.note);
    return insights.filter((value, index, all) => !!value && all.indexOf(value) === index).slice(0, 6);
  }

  private navigateToAnalyticsTarget(target?: string): void {
    const sectionId = this.resolveAnalyticsSectionId(target);
    if (!sectionId) return;

    const element = document.getElementById(sectionId);
    if (!element) return;

    const rect = element.getBoundingClientRect();
    const headerOffset = 104;
    const absoluteTop = window.scrollY + rect.top;
    const targetTop = Math.max(0, absoluteTop - headerOffset);

    window.scrollTo({ top: targetTop, behavior: 'smooth' });
    element.classList.remove('analytics-section-highlight');
    void element.clientHeight;
    element.classList.add('analytics-section-highlight');
    if (this.sectionHighlightTimeoutId) clearTimeout(this.sectionHighlightTimeoutId);
    this.sectionHighlightTimeoutId = setTimeout(() => {
      element.classList.remove('analytics-section-highlight');
      this.sectionHighlightTimeoutId = null;
    }, 1800);

    if (sectionId === 'analytics-sla' && this.slaCompliance.breach_candidates.length) {
      window.setTimeout(() => this.openSlaDetailsModal(), 260);
    }
  }

  private resolveAnalyticsSectionId(target?: string): string | null {
    if (!target) return null;

    const normalized = target.toString().trim().toLowerCase();
    if (!normalized) return null;

    if (normalized === 'time-to-hire' || normalized === 'time to hire') return 'analytics-time-to-hire';
    if (normalized === 'forecast' || normalized === 'forecast vs target') return 'analytics-forecast';
    if (normalized === 'anomalies' || normalized === 'anomaly' || normalized === 'risk') return 'analytics-anomalies';
    if (normalized === 'offers' || normalized === 'offer' || normalized === 'offer acceptance') return 'analytics-offers';
    if (normalized === 'sla') return 'analytics-sla';
    if (normalized === 'dropoff' || normalized === 'dropoffs') return 'analytics-dropoffs';
    if (normalized === 'sources' || normalized === 'source') return 'analytics-sources';
    if (normalized === 'recruiters' || normalized === 'recruiter') return 'analytics-recruiters';

    const funnelStages = ['applied', 'assessment pending', 'scheduled', 'shortlisted', 'hired', 'completed'];
    if (funnelStages.includes(normalized)) return 'analytics-funnel';

    const matchedRole = this.roleHealth.find((item) => item.role.toLowerCase() === normalized);
    if (matchedRole) return 'analytics-role-health';

    const matchedRecruiter = this.recruiterPerformance.find((item) => item.name.toLowerCase() === normalized);
    if (matchedRecruiter) return 'analytics-recruiters';

    const matchedSource = this.sourceEffectiveness.find((item) => item.source.toLowerCase() === normalized);
    if (matchedSource) return 'analytics-sources';

    return null;
  }

  private shouldOpenDropoffModalFromAnomalies(): boolean {
    if (!this.dropoffAnalysis.by_role.length) return false;
    return this.anomalyFlags.some((flag) => {
      const title = (flag.title || '').toLowerCase();
      const detail = (flag.detail || '').toLowerCase();
      return title.includes('drop-off') || title.includes('dropoff') || detail.includes('drop-off') || detail.includes('dropoff');
    });
  }

  getChangeDirectionClass(direction: AnalyticsChangeSignal['direction']): string {
    return `direction-${direction}`;
  }

  trackByString(_index: number, value: string): string {
    return value;
  }

  trackByOption(_index: number, option: { id: string }): string {
    return option.id;
  }

  trackByTab(_index: number, tab: { key: SeverityTab }): SeverityTab {
    return tab.key;
  }

  trackBySignal(_index: number, signal: AnalyticsBriefSignal): string {
    return signal.key;
  }

  trackByAction(_index: number, action: ExecutiveAction): string {
    return `${action.label}:${action.target || ''}`;
  }

  trackBySummaryCard(_index: number, card: AnalyticsSummaryCard): string {
    return card.label;
  }

  trackByChange(_index: number, change: AnalyticsChangeSignal): string {
    return change.label;
  }

  private createBriefSignal(input: Omit<AnalyticsBriefSignal, 'confidenceLabel' | 'confidenceTone' | 'sortWeight'>): AnalyticsBriefSignal {
    const confidenceLabel = this.getSignalConfidence(input.evidenceCount, input.severity);
    return {
      ...input,
      confidenceLabel,
      confidenceTone: confidenceLabel === 'High' ? 'positive' : confidenceLabel === 'Medium' ? 'info' : 'neutral',
      sortWeight: this.getSignalSortWeight(input.severity, input.evidenceCount, input.key),
    };
  }

  private getSignalConfidence(evidenceCount: number, severity: SignalSeverity): 'High' | 'Medium' | 'Low' {
    if (evidenceCount >= 12 || (severity === 'critical' && evidenceCount >= 5)) return 'High';
    if (evidenceCount >= 4) return 'Medium';
    return 'Low';
  }

  private getSignalSortWeight(severity: SignalSeverity, evidenceCount: number, key: string): number {
    const severityWeight: Record<SignalSeverity, number> = {
      critical: 400,
      at_risk: 300,
      warning: 200,
      positive: 100,
      info: 0,
    };
    const businessBoost: Record<string, number> = {
      anomaly_severity: 45,
      forecast_gap: 40,
      role_risk: 35,
      funnel_leakage: 34,
      sla_pressure: 30,
      hiring_slowdown: 24,
      offer_acceptance: 20,
      recruiter_efficiency: 16,
      source_quality: 14,
    };
    return severityWeight[severity] + (businessBoost[key] || 0) + Math.min(evidenceCount, 50);
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

  private scheduleChartRender(attempt = 0): void {
    if (!this.initialized || this.loading) return;
    if (this.chartAnimationFrameId !== null) cancelAnimationFrame(this.chartAnimationFrameId);
    if (this.chartRetryTimeoutId) clearTimeout(this.chartRetryTimeoutId);

    this.chartAnimationFrameId = requestAnimationFrame(() => {
      this.chartAnimationFrameId = null;
      const rendered = this.renderCharts();
      if (!rendered && attempt < 4) {
        this.chartRetryTimeoutId = setTimeout(() => this.scheduleChartRender(attempt + 1), 90);
      }
    });
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
    if (v.includes(',') || v.includes('"') || v.includes('\n')) return `"${v.replace(/"/g, '""')}"`;
    return v;
  }

  private renderCharts(): boolean {
    let rendered = false;

    const funnelCtx = this.funnelCanvas?.nativeElement?.getContext('2d');
    if (this.funnelCanvas?.nativeElement && funnelCtx && this.hasFunnelData) {
      if (this.funnelChart) this.funnelChart.destroy();
      this.funnelChart = new Chart(funnelCtx, {
        type: 'bar',
        data: {
          labels: this.funnel.labels,
          datasets: [{
            label: 'Candidates',
            data: this.funnel.values,
            backgroundColor: ['#57e6ff', '#4cb9ff', '#3b82f6', '#2dd4bf', '#f59e0b', '#ef4444'],
            borderRadius: 10,
            borderSkipped: false,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: {
              ticks: { color: '#98c3e5' },
              grid: { color: 'rgba(120,188,235,0.08)' }
            },
            y: {
              ticks: { color: '#98c3e5', stepSize: 1 },
              beginAtZero: true,
              grid: { color: 'rgba(120,188,235,0.1)' }
            },
          }
        }
      });
      rendered = true;
    } else if (this.funnelChart) {
      this.funnelChart.destroy();
      this.funnelChart = undefined;
    }

    const tthCtx = this.tthCanvas?.nativeElement?.getContext('2d');
    if (this.tthCanvas?.nativeElement && tthCtx && this.hasTimeToHireTrend) {
      if (this.tthChart) this.tthChart.destroy();
      this.tthChart = new Chart(tthCtx, {
        type: 'line',
        data: {
          labels: this.timeToHire.monthly_labels,
          datasets: [
            {
              label: 'Avg Days',
              data: this.timeToHire.monthly_avg_days,
              borderColor: '#57e6ff',
              backgroundColor: 'rgba(34,211,238,0.18)',
              fill: true,
              tension: 0.32,
              pointRadius: 2.5,
            },
            {
              label: 'Hires',
              data: this.timeToHire.monthly_hires,
              borderColor: '#5eead4',
              backgroundColor: 'rgba(94,234,212,0.14)',
              fill: false,
              tension: 0.25,
              pointRadius: 2.5,
              yAxisID: 'y1',
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: {
              ticks: { color: '#98c3e5' },
              grid: { color: 'rgba(120,188,235,0.08)' }
            },
            y: {
              ticks: { color: '#98c3e5' },
              beginAtZero: true,
              grid: { color: 'rgba(120,188,235,0.1)' }
            },
            y1: {
              ticks: { color: '#98c3e5' },
              beginAtZero: true,
              position: 'right',
              grid: { drawOnChartArea: false }
            },
          },
          plugins: { legend: { labels: { color: '#bfe0f8' } } }
        }
      });
      rendered = true;
    } else if (this.tthChart) {
      this.tthChart.destroy();
      this.tthChart = undefined;
    }

    return rendered || (!this.hasFunnelData && !this.hasTimeToHireTrend);
  }

  private destroyCharts(): void {
    if (this.funnelChart) {
      this.funnelChart.destroy();
      this.funnelChart = undefined;
    }
    if (this.tthChart) {
      this.tthChart.destroy();
      this.tthChart = undefined;
    }
  }

  public getWeakestFunnelConversion(): { from: string; to: string; rate: number } | null {
    if (!this.funnel.conversions.length) return null;
    return [...this.funnel.conversions].sort((a, b) => a.rate - b.rate)[0] || null;
  }

  private formatPercent(value: number): string {
    return `${Number(value || 0).toFixed(Number.isInteger(value) ? 0 : 1)}%`;
  }

  private formatDays(value: number): string {
    return `${Math.round(value || 0)}d`;
  }

  private formatInteger(value: number): string {
    return `${Math.round(value || 0)}`;
  }
}
