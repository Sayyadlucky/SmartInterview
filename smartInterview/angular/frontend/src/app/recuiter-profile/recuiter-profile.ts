import { AfterViewChecked, Component, ElementRef, Input, OnChanges, OnDestroy, SimpleChanges, ViewChild } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { Chart, registerables } from 'chart.js';
import { catchError, of } from 'rxjs';

Chart.register(...registerables);

interface Evaluator {
  id: number;
  name: string;
  email: string;
  role: string;
  gender?: string;
  user_id?: number;
}

interface InterviewItem {
  id: number;
  candidate: string;
  status: string;
  score?: number | null;
  role?: string;
  date: string;
}

interface InterviewProfileResponse {
  Success: boolean;
  Error?: string | null;
  Interviews?: InterviewItem[];
}

@Component({
  selector: 'app-recuiter-profile',
  imports: [CommonModule],
  templateUrl: './recuiter-profile.html',
  styleUrl: './recuiter-profile.scss'
})
export class RecuiterProfile implements OnChanges, OnDestroy, AfterViewChecked {
  @Input() evaluator!: Evaluator;
  @ViewChild('performanceChartCanvas') performanceChartCanvas?: ElementRef<HTMLCanvasElement>;

  loading = false;
  errorMessage = '';
  interviews: InterviewItem[] = [];

  hiredCount = 0;
  pendingCount = 0;
  completedRate = 0;
  upcomingInterviews: InterviewItem[] = [];
  nextInterviewLabel = 'No Upcoming Interview';
  availabilityDates: string[] = [];
  availabilityDateSet = new Set<string>();
  calendarInterviewCountMap: Record<string, number> = {};
  performanceStatusBreakdownData: Array<{ label: string; count: number; percent: number }> = [];
  selectedMonthInterviews = 0;
  selectedMonthActiveDays = 0;
  selectedMonthScheduledCount = 0;
  selectedMonthBusiestDayLabel = '-';
  selectedMonthBusiestCount = 0;
  selectedMonthTopRoles: Array<{ role: string; count: number }> = [];

  calendarMonthName = '';
  calendarYear = 0;
  selectedCalendarYear = new Date().getFullYear();
  selectedCalendarMonth = new Date().getMonth();
  selectedInsightsYear = new Date().getFullYear();
  selectedInsightsMonth = new Date().getMonth();
  private readonly baseCalendarYear = new Date().getFullYear();
  private readonly baseCalendarMonth = new Date().getMonth();
  private minCalendarMonthIndex = this.baseCalendarYear * 12 + this.baseCalendarMonth - 1;
  weekDays = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
  monthLabels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  calendarDays: Array<{ date: string; dateString: string; currentMonth: boolean }> = [];
  monthlyInterviewCounts: number[] = Array(12).fill(0);
  selectedPerformanceYear = new Date().getFullYear();
  minPerformanceYear = new Date().getFullYear();
  maxPerformanceYear = new Date().getFullYear();

  private performanceChart?: Chart;
  private chartRenderPending = false;

  constructor(private http: HttpClient) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['evaluator'] && this.evaluator?.email) {
      this.loadRecruiterProfile();
    }
  }

  ngOnDestroy(): void {
    this.destroyChart();
  }

  ngAfterViewChecked(): void {
    if (!this.chartRenderPending || this.loading) return;
    this.renderPerformanceChart();
    this.chartRenderPending = false;
  }

  trackById(_index: number, item: InterviewItem): number {
    return item.id;
  }

  get totalInterviews(): number {
    return this.interviews.length;
  }

  get activePipelineCount(): number {
    return this.interviews.filter((i) => {
      const status = this.normalizeStatus(i.status);
      return ['scheduled', 'assessment pending', 'shortlisted', 'auto screening scheduled'].includes(status);
    }).length;
  }

  get lastActiveDate(): Date | null {
    const firstValid = this.interviews
      .map((i) => this.getValidDate(i.date))
      .find((d): d is Date => !!d);
    return firstValid || null;
  }

  get currentMonthInterviews(): number {
    const now = new Date();
    const month = now.getMonth();
    const year = now.getFullYear();
    return this.interviews.filter((i) => {
      const d = this.getValidDate(i.date);
      return !!d && d.getMonth() === month && d.getFullYear() === year;
    }).length;
  }

  get previousMonthInterviews(): number {
    const now = new Date();
    const previous = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const month = previous.getMonth();
    const year = previous.getFullYear();
    return this.interviews.filter((i) => {
      const d = this.getValidDate(i.date);
      return !!d && d.getMonth() === month && d.getFullYear() === year;
    }).length;
  }

  get monthOverMonthDelta(): number {
    return this.currentMonthInterviews - this.previousMonthInterviews;
  }

  get monthOverMonthDeltaPercent(): number {
    if (!this.previousMonthInterviews) return this.currentMonthInterviews ? 100 : 0;
    return Math.round((this.monthOverMonthDelta / this.previousMonthInterviews) * 100);
  }

  get monthOverMonthLabel(): string {
    const delta = this.monthOverMonthDelta;
    const percent = this.monthOverMonthDeltaPercent;
    if (delta === 0) return 'No change vs last month';
    return `${delta > 0 ? '+' : ''}${delta} (${delta > 0 ? '+' : ''}${percent}%) vs last month`;
  }

  get monthOverMonthClass(): string {
    if (this.monthOverMonthDelta > 0) return 'trend-up';
    if (this.monthOverMonthDelta < 0) return 'trend-down';
    return 'trend-flat';
  }

  get hasPerformanceData(): boolean {
    return this.monthlyInterviewCounts.some((count) => count > 0);
  }

  get thisMonthInterviewCount(): number {
    const index = new Date().getMonth();
    return this.monthlyInterviewCounts[index] || 0;
  }

  get avgMonthlyInterviews(): number {
    const total = this.monthlyInterviewCounts.reduce((sum, value) => sum + value, 0);
    return Math.round((total / 12) * 10) / 10;
  }

  get selectedMonthAvgPerActiveDay(): number {
    if (!this.selectedMonthActiveDays) return 0;
    return Math.round((this.selectedMonthInterviews / this.selectedMonthActiveDays) * 10) / 10;
  }

  get peakMonth(): { label: string; count: number } {
    const maxCount = Math.max(...this.monthlyInterviewCounts);
    const monthIndex = this.monthlyInterviewCounts.findIndex((count) => count === maxCount);
    return {
      label: monthIndex >= 0 ? this.monthLabels[monthIndex] : this.monthLabels[0],
      count: maxCount > 0 ? maxCount : 0
    };
  }

  get canGoPrevPerformanceYear(): boolean {
    return this.selectedPerformanceYear > this.minPerformanceYear;
  }

  get canGoNextPerformanceYear(): boolean {
    return this.selectedPerformanceYear < this.maxPerformanceYear;
  }

  private buildPerformanceStatusBreakdown(source: InterviewItem[]): Array<{ label: string; count: number; percent: number }> {
    const statusBuckets: Record<string, number> = {
      Scheduled: 0,
      'Assessment Pending': 0,
      Shortlisted: 0,
      Hired: 0,
      Rejected: 0,
      Cancelled: 0
    };

    source.forEach((item) => {
      const status = this.normalizeStatus(item.status);
      if (status === 'scheduled') statusBuckets['Scheduled'] += 1;
      else if (status === 'assessment pending') statusBuckets['Assessment Pending'] += 1;
      else if (status === 'shortlisted') statusBuckets['Shortlisted'] += 1;
      else if (status === 'hired' || status === 'completed') statusBuckets['Hired'] += 1;
      else if (status === 'rejected') statusBuckets['Rejected'] += 1;
      else if (status === 'cancelled') statusBuckets['Cancelled'] += 1;
    });

    return Object.entries(statusBuckets)
      .map(([label, count]) => ({
        label,
        count,
        percent: source.length ? Math.round((count / source.length) * 100) : 0
      }))
      .filter((item) => item.count > 0)
      .sort((a, b) => b.count - a.count)
      .slice(0, 4);
  }

  changePerformanceYear(step: number): void {
    const nextYear = this.selectedPerformanceYear + step;
    if (nextYear < this.minPerformanceYear || nextYear > this.maxPerformanceYear) return;
    this.selectedPerformanceYear = nextYear;
    this.rebuildPerformanceYearState();
    this.chartRenderPending = true;
  }

  isAvailabilityDate(dateString: string): boolean {
    return !!dateString && this.availabilityDateSet.has(dateString);
  }

  getInterviewCountByDate(dateString: string): number {
    return this.calendarInterviewCountMap[dateString] || 0;
  }

  getCalendarDensityClass(dateString: string): string {
    const count = this.getInterviewCountByDate(dateString);
    if (count >= 5) return 'density-5';
    if (count >= 4) return 'density-4';
    if (count >= 3) return 'density-3';
    if (count >= 2) return 'density-2';
    if (count >= 1) return 'density-1';
    return '';
  }

  getCalendarCellTitle(dateString: string): string {
    if (!dateString) return '';
    const count = this.getInterviewCountByDate(dateString);
    return count ? `${count} interview${count > 1 ? 's' : ''}` : 'No interviews';
  }

  isNonInterviewDate(day: { date: string; dateString: string; currentMonth: boolean }): boolean {
    return !!day.currentMonth && !!day.dateString && !this.isAvailabilityDate(day.dateString);
  }

  get calendarMonthOffset(): number {
    return (
      this.selectedCalendarYear * 12 +
      this.selectedCalendarMonth -
      (this.baseCalendarYear * 12 + this.baseCalendarMonth)
    );
  }

  get insightsMonthOffset(): number {
    return (
      this.selectedInsightsYear * 12 +
      this.selectedInsightsMonth -
      (this.baseCalendarYear * 12 + this.baseCalendarMonth)
    );
  }

  get insightsMonthName(): string {
    return new Date(this.selectedInsightsYear, this.selectedInsightsMonth, 1).toLocaleString('default', { month: 'long' });
  }

  get insightsYear(): number {
    return this.selectedInsightsYear;
  }

  get calendarSectionTitle(): string {
    if (this.calendarMonthOffset < -1) return 'Past Activity';
    if (this.calendarMonthOffset === -1) return 'Previous Month Activity';
    if (this.calendarMonthOffset === 1) return 'Next Month Activity';
    return 'Current Month Activity';
  }

  get canGoPrevCalendarMonth(): boolean {
    const selectedMonthIndex = this.selectedCalendarYear * 12 + this.selectedCalendarMonth;
    return selectedMonthIndex > this.minCalendarMonthIndex;
  }

  get canGoNextCalendarMonth(): boolean {
    return this.calendarMonthOffset < 1;
  }

  get canGoPrevInsightsMonth(): boolean {
    const selectedMonthIndex = this.selectedInsightsYear * 12 + this.selectedInsightsMonth;
    return selectedMonthIndex > this.minCalendarMonthIndex;
  }

  get canGoNextInsightsMonth(): boolean {
    return this.insightsMonthOffset < 1;
  }

  roleBarWidth(count: number): number {
    const max = this.selectedMonthTopRoles[0]?.count || 1;
    return Math.max(10, Math.round((count / max) * 100));
  }

  changeCalendarMonth(step: number): void {
    if ((step < 0 && !this.canGoPrevCalendarMonth) || (step > 0 && !this.canGoNextCalendarMonth)) {
      return;
    }
    const monthIndex = this.selectedCalendarYear * 12 + this.selectedCalendarMonth + step;
    this.selectedCalendarYear = Math.floor(monthIndex / 12);
    this.selectedCalendarMonth = ((monthIndex % 12) + 12) % 12;
    this.rebuildCalendarState();
  }

  changeInsightsMonth(step: number): void {
    if ((step < 0 && !this.canGoPrevInsightsMonth) || (step > 0 && !this.canGoNextInsightsMonth)) {
      return;
    }
    const monthIndex = this.selectedInsightsYear * 12 + this.selectedInsightsMonth + step;
    this.selectedInsightsYear = Math.floor(monthIndex / 12);
    this.selectedInsightsMonth = ((monthIndex % 12) + 12) % 12;
    this.rebuildInsightsState();
  }

  private getApiBaseUrl(): string {
    let portNumber = '';
    if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
      portNumber = '8000';
    }
    return `${window.location.protocol}//${window.location.hostname}:${portNumber}`;
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

  private destroyChart(): void {
    if (this.performanceChart) {
      this.performanceChart.destroy();
      this.performanceChart = undefined;
    }
  }

  private parseDate(value: string): Date {
    return new Date(value);
  }

  private getValidDate(value: string): Date | null {
    const parsed = this.parseDate(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  loadRecruiterProfile(): void {
    if (!this.evaluator?.email && !this.evaluator?.id) return;

    this.loading = true;
    this.errorMessage = '';
    const apiBaseUrl = this.getApiBaseUrl();
    const body = new URLSearchParams();
    if (this.evaluator.email) body.append('recruiter', this.evaluator.email);
    if (this.evaluator.id) body.append('recruiter_id', String(this.evaluator.id));

    this.http
      .post<InterviewProfileResponse>(`${apiBaseUrl}/get-evaluator-profile/`, body.toString(), {
        headers: new HttpHeaders({ 'Content-Type': 'application/x-www-form-urlencoded' })
      })
      .pipe(
        catchError((error) => {
          console.error('Error fetching recruiter profile', error);
          this.loading = false;
          this.errorMessage = 'Failed to load evaluator profile.';
          return of({ Success: false, Interviews: [] } as InterviewProfileResponse);
        })
      )
      .subscribe((response) => {
        try {
          if (!response?.Success) {
            this.interviews = [];
            this.loading = false;
            this.errorMessage = response?.Error || 'Failed to load evaluator profile.';
            this.rebuildDerivedState();
            this.destroyChart();
            return;
          }

          const raw = Array.isArray(response.Interviews) ? response.Interviews : [];
          this.interviews = raw.slice().sort((a, b) => {
            const dateA = this.getValidDate(a.date)?.getTime() || 0;
            const dateB = this.getValidDate(b.date)?.getTime() || 0;
            return dateB - dateA;
          });

          this.rebuildDerivedState();
          this.loading = false;
          this.chartRenderPending = true;
        } catch (err) {
          console.error('Error processing evaluator profile payload', err);
          this.interviews = [];
          this.loading = false;
          this.errorMessage = 'Profile data format error.';
          this.rebuildDerivedState();
          this.destroyChart();
          this.chartRenderPending = false;
        }
      });
  }

  private rebuildDerivedState(): void {
    const now = new Date();
    const thisMonth = now.getMonth();
    const thisYear = now.getFullYear();

    this.hiredCount = this.interviews.filter((i) => {
      const status = this.normalizeStatus(i.status);
      return status === 'hired' || status === 'completed';
    }).length;

    this.pendingCount = this.interviews.filter((i) => this.normalizeStatus(i.status) !== 'rejected').length;
    this.completedRate = this.totalInterviews ? Math.round((this.hiredCount / this.totalInterviews) * 100) : 0;

    const upcoming = this.interviews
      .filter((i) => {
        if (this.normalizeStatus(i.status) !== 'scheduled') return false;
        const d = this.getValidDate(i.date);
        return !!d && d.getTime() >= now.getTime();
      })
      .sort((a, b) => {
        const dateA = this.getValidDate(a.date)?.getTime() || 0;
        const dateB = this.getValidDate(b.date)?.getTime() || 0;
        return dateA - dateB;
      });
    this.upcomingInterviews = upcoming;
    this.nextInterviewLabel = upcoming.length ? upcoming[0].date : 'No Upcoming Interview';

    const interviewYears = this.interviews
      .map((i) => this.getValidDate(i.date)?.getFullYear())
      .filter((year): year is number => typeof year === 'number');
    this.minPerformanceYear = interviewYears.length ? Math.min(thisYear, Math.min(...interviewYears)) : thisYear;
    this.maxPerformanceYear = interviewYears.length ? Math.max(thisYear, Math.max(...interviewYears)) : thisYear;
    this.selectedPerformanceYear = thisYear;
    this.rebuildPerformanceYearState();

    const validInterviewDates = this.interviews
      .map((i) => this.getValidDate(i.date))
      .filter((date): date is Date => !!date);
    if (validInterviewDates.length) {
      const firstInterviewDate = validInterviewDates.reduce((min, date) => (date < min ? date : min), validInterviewDates[0]);
      this.minCalendarMonthIndex = firstInterviewDate.getFullYear() * 12 + firstInterviewDate.getMonth();
    } else {
      this.minCalendarMonthIndex = this.baseCalendarYear * 12 + this.baseCalendarMonth - 1;
    }

    this.selectedCalendarYear = thisYear;
    this.selectedCalendarMonth = thisMonth;
    this.selectedInsightsYear = thisYear;
    this.selectedInsightsMonth = thisMonth;
    this.rebuildCalendarState();
    this.rebuildInsightsState();
  }

  private rebuildCalendarState(): void {
    const monthInterviews = this.interviews.filter((i) => {
      const d = this.getValidDate(i.date);
      if (!d) return false;
      return d.getMonth() === this.selectedCalendarMonth && d.getFullYear() === this.selectedCalendarYear;
    });
    const dateMap: Record<string, number> = {};

    monthInterviews.forEach((i) => {
      const date = this.getValidDate(i.date);
      if (!date) return;
      const key = date.toISOString().split('T')[0];
      dateMap[key] = (dateMap[key] || 0) + 1;
    });

    this.calendarInterviewCountMap = dateMap;
    this.availabilityDates = Object.keys(dateMap);
    this.availabilityDateSet = new Set(this.availabilityDates);

    this.generateCalendar(this.selectedCalendarYear, this.selectedCalendarMonth);
  }

  private rebuildInsightsState(): void {
    const monthInterviews = this.interviews.filter((i) => {
      const d = this.getValidDate(i.date);
      if (!d) return false;
      return d.getMonth() === this.selectedInsightsMonth && d.getFullYear() === this.selectedInsightsYear;
    });
    const dateMap: Record<string, number> = {};
    const roleMap: Record<string, number> = {};
    let scheduledCount = 0;

    monthInterviews.forEach((i) => {
      const date = this.getValidDate(i.date);
      if (!date) return;
      const key = date.toISOString().split('T')[0];
      dateMap[key] = (dateMap[key] || 0) + 1;

      if (this.normalizeStatus(i.status) === 'scheduled') {
        scheduledCount += 1;
      }

      const roleName = (i.role || 'Unassigned').toString().trim() || 'Unassigned';
      roleMap[roleName] = (roleMap[roleName] || 0) + 1;
    });

    this.selectedMonthInterviews = monthInterviews.length;
    this.selectedMonthActiveDays = Object.keys(dateMap).length;
    this.selectedMonthScheduledCount = scheduledCount;

    const busiest = Object.entries(dateMap).sort((a, b) => b[1] - a[1])[0];
    if (busiest) {
      this.selectedMonthBusiestCount = busiest[1];
      this.selectedMonthBusiestDayLabel = new Date(`${busiest[0]}T00:00:00`).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric'
      });
    } else {
      this.selectedMonthBusiestCount = 0;
      this.selectedMonthBusiestDayLabel = '-';
    }

    this.selectedMonthTopRoles = Object.entries(roleMap)
      .map(([role, count]) => ({ role, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 3);
  }

  private rebuildPerformanceYearState(): void {
    this.monthlyInterviewCounts = Array(12).fill(0);
    let yearlyTotal = 0;
    let yearlyHired = 0;
    const yearlyInterviews: InterviewItem[] = [];

    this.interviews.forEach((interview) => {
      const d = this.getValidDate(interview.date);
      if (!d) return;
      if (d.getFullYear() === this.selectedPerformanceYear) {
        this.monthlyInterviewCounts[d.getMonth()] += 1;
        yearlyTotal += 1;
        yearlyInterviews.push(interview);
        const status = this.normalizeStatus(interview.status);
        if (status === 'hired' || status === 'completed') {
          yearlyHired += 1;
        }
      }
    });

    this.completedRate = yearlyTotal ? Math.round((yearlyHired / yearlyTotal) * 100) : 0;
    this.performanceStatusBreakdownData = this.buildPerformanceStatusBreakdown(yearlyInterviews);
  }

  private generateCalendar(year: number, month: number): void {
    this.calendarYear = year;
    this.calendarMonthName = new Date(year, month).toLocaleString('default', { month: 'long' });

    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const days: Array<{ date: string; dateString: string; currentMonth: boolean }> = [];

    for (let i = 0; i < firstDay.getDay(); i++) {
      days.push({ date: '', dateString: '', currentMonth: false });
    }

    for (let d = 1; d <= lastDay.getDate(); d++) {
      const dateObj = new Date(year, month, d);
      const dateString = [
        dateObj.getFullYear(),
        String(dateObj.getMonth() + 1).padStart(2, '0'),
        String(dateObj.getDate()).padStart(2, '0')
      ].join('-');
      days.push({ date: String(d), dateString, currentMonth: true });
    }

    this.calendarDays = days;
  }

  private renderPerformanceChart(): void {
    const canvas = this.performanceChartCanvas?.nativeElement;
    if (!canvas) return;

    this.destroyChart();
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    this.performanceChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: this.monthLabels,
        datasets: [
          {
            label: 'Interviews',
            data: this.monthlyInterviewCounts,
            borderColor: '#38c7ff',
            backgroundColor: 'rgba(56, 199, 255, 0.16)',
            fill: true,
            tension: 0.32,
            pointRadius: 2.8,
            pointBackgroundColor: '#8de7ff'
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            ticks: { color: '#8fb4d8' },
            grid: { color: 'rgba(111, 170, 214, 0.12)' }
          },
          y: {
            beginAtZero: true,
            ticks: {
              color: '#8fb4d8',
              stepSize: 1
            },
            grid: { color: 'rgba(111, 170, 214, 0.12)' }
          }
        }
      }
    });
  }
}
