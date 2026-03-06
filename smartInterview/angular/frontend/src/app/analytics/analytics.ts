import { AfterViewChecked, AfterViewInit, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpParams } from '@angular/common/http';
import { catchError, of } from 'rxjs';
import { Chart, registerables } from 'chart.js';

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
    };
    executive_insights?: string[];
    forecast_vs_target?: {
      current_target?: number;
      current_hired?: number;
      monthly_target?: number;
      next_labels?: string[];
      projected_hires?: number[];
      expected_gap_next_month?: number;
      projection_basis?: string;
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

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './analytics.html',
  styleUrl: './analytics.scss'
})
export class Analytics implements OnInit, AfterViewInit, AfterViewChecked, OnDestroy {
  loading = false;
  errorMessage = '';
  initialized = false;
  chartRenderPending = false;

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
  };
  executiveInsights: string[] = [];
  forecastVsTarget = {
    current_target: 0,
    current_hired: 0,
    monthly_target: 0,
    next_labels: [] as string[],
    projected_hires: [] as number[],
    expected_gap_next_month: 0,
    projection_basis: '',
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

  @ViewChild('funnelCanvas', { static: false }) funnelCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('tthCanvas', { static: false }) tthCanvas?: ElementRef<HTMLCanvasElement>;
  private funnelChart?: Chart;
  private tthChart?: Chart;
  private filterTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private readonly tabListener = (event: Event) => {
    const e = event as CustomEvent;
    if (e?.detail?.tab === 'analytics') this.ensureInitialized();
  };

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    window.addEventListener('dashboard-tab-change', this.tabListener as EventListener);
    const isActiveOnInit = !!document.querySelector('#analytics.tab-content.active');
    if (isActiveOnInit) this.ensureInitialized();
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
    window.removeEventListener('dashboard-tab-change', this.tabListener as EventListener);
    if (this.filterTimeoutId) clearTimeout(this.filterTimeoutId);
    this.destroyCharts();
  }

  get hasFunnelData(): boolean {
    return this.funnel.values.some((x) => x > 0);
  }

  get hasTimeToHireTrend(): boolean {
    return this.timeToHire.monthly_avg_days.some((x) => x > 0) || this.timeToHire.monthly_hires.some((x) => x > 0);
  }

  get qualityRows(): Array<{ label: string; value: number }> {
    return Object.entries(this.interviewQuality.score_bands || {})
      .map(([label, value]) => ({ label, value: Number(value || 0) }))
      .filter((x) => x.value > 0);
  }

  ensureInitialized(): void {
    if (this.initialized) return;
    this.initialized = true;
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

  private getApiBaseUrl(): string {
    let port = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      port = '8000';
    }
    return `${window.location.protocol}//${window.location.hostname}:${port}`;
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

    this.http.get<AnalyticsResponse>(`${this.getApiBaseUrl()}/analytics-tab-data/`, { params })
      .pipe(
        catchError((error) => {
          console.error('Error fetching analytics data', error);
          this.loading = false;
          this.errorMessage = 'Unable to load analytics data.';
          return of({ Success: false, Data: {} } as AnalyticsResponse);
        })
      )
      .subscribe((response) => {
        if (!response?.Success) {
          this.errorMessage = response?.Error || 'Unable to load analytics data.';
          this.loading = false;
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
        };
        this.executiveInsights = data.executive_insights || [];
        this.forecastVsTarget = {
          current_target: data.forecast_vs_target?.current_target || 0,
          current_hired: data.forecast_vs_target?.current_hired || 0,
          monthly_target: data.forecast_vs_target?.monthly_target || 0,
          next_labels: data.forecast_vs_target?.next_labels || [],
          projected_hires: data.forecast_vs_target?.projected_hires || [],
          expected_gap_next_month: data.forecast_vs_target?.expected_gap_next_month || 0,
          projection_basis: data.forecast_vs_target?.projection_basis || '',
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

        this.loading = false;
        this.chartRenderPending = true;
        requestAnimationFrame(() => {
          const rendered = this.renderCharts();
          this.chartRenderPending = !rendered;
        });
      });
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
            backgroundColor: ['#22d3ee', '#38bdf8', '#3b82f6', '#10b981', '#f59e0b', '#ef4444'],
            borderRadius: 8,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color: '#98c3e5' }, grid: { color: 'rgba(120,188,235,0.12)' } },
            y: { ticks: { color: '#98c3e5', stepSize: 1 }, beginAtZero: true, grid: { color: 'rgba(120,188,235,0.12)' } },
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
              borderColor: '#22d3ee',
              backgroundColor: 'rgba(34,211,238,0.15)',
              fill: true,
              tension: 0.3,
              pointRadius: 2.5,
            },
            {
              label: 'Hires',
              data: this.timeToHire.monthly_hires,
              borderColor: '#4ade80',
              backgroundColor: 'rgba(74,222,128,0.1)',
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
            x: { ticks: { color: '#98c3e5' }, grid: { color: 'rgba(120,188,235,0.12)' } },
            y: { ticks: { color: '#98c3e5' }, beginAtZero: true, grid: { color: 'rgba(120,188,235,0.12)' } },
            y1: { ticks: { color: '#98c3e5' }, beginAtZero: true, position: 'right', grid: { drawOnChartArea: false } },
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
}
