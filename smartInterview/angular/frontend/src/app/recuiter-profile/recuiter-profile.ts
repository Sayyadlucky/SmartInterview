import { Component, AfterViewInit, OnInit, ViewChild, ElementRef, SimpleChanges, Input } from '@angular/core';
import { HttpClient } from '@angular/common/http';  // Import HttpClient
import { catchError } from 'rxjs/operators';
import { of } from 'rxjs';
import { CommonModule } from '@angular/common';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';

@Component({
  selector: 'app-recuiter-profile',
  imports: [CommonModule],
  templateUrl: './recuiter-profile.html',
  styleUrl: './recuiter-profile.scss'
})
export class RecuiterProfile {
  data: any;
  hiredCount: number | undefined;
  pendingCount: number | undefined;

  constructor(private http: HttpClient, private dialog: MatDialog) {}

  
  @Input() evaluator: any;
  
  loading: boolean = false;
  weekDays = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
  monthlyWorkload: { date: string, count: number }[][] = [];
  calendarDays: any[] = [];
  monthName = '';
  year = 0;
  recruiters_list: any[] = [];
  interview_list: any;
  next_interview: any;
  upcoming_interviews: any[] = [];
  workload: number[] = [0, 2, 4, 6, 8, 10, 12];

  // Example availability data (map evaluator's availability)
  availability: string[] = [];

  ngOnInit(): void {
      const today = new Date();
      const year = today.getFullYear();
      const month = today.getMonth();
      this.generateCalendar(year, month);
      setTimeout(() => {
        this.getRecruiterProfile();
      }, 0);
    }

  getRecruiterProfile() {
    this.loading = true;
    let port_number = ''
        if(window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"){
          port_number = '8000'
        }
        const apiBaseUrl = `${window.location.protocol}//${window.location.hostname}:${port_number}`;
         const formData = new URLSearchParams();
        formData.append('recruiter', this.evaluator.email);

        fetch(`${apiBaseUrl}/get-evaluator-profile/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded'
          },
          body: formData.toString()
        })
        .then(response => response.json())
        .then(data => {
          if (data && data.Success) {
            this.interview_list = data.Interviews || [];
            if (this.interview_list && this.interview_list.length > 0) {
              const today = new Date();
              const currentMonth = today.getMonth();
              const currentYear = today.getFullYear();

              this.availability = this.interview_list
                .map((interview: any) => {
                  const interviewDate = new Date(interview.date);
                  if (
                    interviewDate.getMonth() === currentMonth &&
                    interviewDate.getFullYear() === currentYear
                  ) {
                    return interviewDate.toISOString().split('T')[0]; // yyyy-mm-dd
                  }
                  return null;
                })
                .filter((date: string | null) => date !== null) as string[];
            }
            this.updateInterviewCounts();
            this.loading = false;
            this.next_interview = this.getNextInterview(this.interview_list);
            this.renderPerformanceChart();
            this.generateMonthlyWorkload();
          }else{
            alert('Error fetching profile data. Please try again.');
          }
        })
        .catch(error => {
          alert('Error fetching profile data. Please try again.');
        });
  }

  generateCalendar(year: number, month: number) {
    this.year = year;
    this.monthName = new Date(year, month).toLocaleString('default', { month: 'long' });

    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);

    const days: any[] = [];

    // Padding before first day
    for (let i = 0; i < firstDay.getDay(); i++) {
      days.push({ date: '', currentMonth: false });
    }

    // Actual days
    for (let d = 1; d <= lastDay.getDate(); d++) {
      const dateObj = new Date(year, month, d);
      const dateString = [
        dateObj.getFullYear(),
        String(dateObj.getMonth() + 1).padStart(2, '0'),
        String(dateObj.getDate()).padStart(2, '0')
      ].join('-'); // yyyy-mm-dd (local)

      days.push({
        date: d,
        dateString,
        currentMonth: true
      });
    }

    this.calendarDays = days;
  }

  updateInterviewCounts() {
    this.hiredCount = this.interview_list?.filter((interview: { status: string; }) => interview.status === 'hired').length;
    this.pendingCount = this.interview_list?.filter((interview: { status: string; }) => interview.status != 'rejected').length;
  }

  
  getNextInterview(interviews: any[]) {
    const today = new Date();

    // filter only future "scheduled" interviews
    const upcoming = interviews
      .filter(item => 
        item.status === "scheduled" && new Date(item.date) >= today
      )
      .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());

    if (upcoming?.length > 0) {
      this.upcoming_interviews = upcoming;
      return upcoming[0].date; // next nearest interview
    } else {
      this.upcoming_interviews = [];
      return "No Upcoming Interview";
    }
  }
  // Add this method to fix the error
  trackById(index: number, item: any): any {
      return item.id;
  }

  renderPerformanceChart(): void {
    // if (!this.interview_list || !Array.isArray(this.interview_list)) return;

    // Track number of interviews per month for the current year
    const currentYear = new Date().getFullYear();
    const monthCounts = Array(12).fill(0);

    this.interview_list.forEach((interview: any) => {
      const interviewDate = new Date(interview.date);
      if (interviewDate.getFullYear() === currentYear) {
        monthCounts[interviewDate.getMonth()] += 1;
      }
    });

    const labels = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
    ];
    const data = monthCounts;

    // Wait for Chart.js to be loaded before drawing the chart
    const ensureChartJsLoaded = (callback: () => void) => {
      if ((window as any).Chart) {
        callback();
      } else {
        const existingScript = document.querySelector('script[src="https://cdn.jsdelivr.net/npm/chart.js"]');
        if (!existingScript) {
          const script = document.createElement('script');
          script.src = 'https://cdn.jsdelivr.net/npm/chart.js';
          script.onload = () => callback();
          document.body.appendChild(script);
        } else {
          existingScript.addEventListener('load', () => callback());
        }
      }
    };

    // Wait for the canvas to be available in the DOM
    const waitForCanvas = (callback: () => void) => {
      const canvas = document.getElementById('performanceChart') as HTMLCanvasElement;
      if (!canvas) {
        setTimeout(() => waitForCanvas(callback), 100);
      } else {
        callback();
      }
    };

    waitForCanvas(() => {
      ensureChartJsLoaded(() => {
        const canvas = document.getElementById('performanceChart') as HTMLCanvasElement;
        canvas.height = 200; // Set a fixed height
        if (!canvas) return;

        // Remove previous chart if exists
        if ((window as any).performanceChartInstance) {
          (window as any).performanceChartInstance.destroy();
        }

        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        (window as any).performanceChartInstance = new (window as any).Chart(ctx, {
          type: 'line',
          data: {
            labels,
            datasets: [{
              label: `No of Interviews`,
              data,
              borderColor: '#2196f3',
              backgroundColor: 'rgba(33,150,243,0.1)',
              fill: true,
              tension: 0.3
            }]
          },
          options: {
            responsive: true,
            plugins: {
              legend: { display: false }
            },
            scales: {
              x: {
                type: 'category',
                labels: labels,
                ticks: {
                  autoSkip: false
                }
              },
              y: {
                beginAtZero: true,
                min: 0,
                max: (() => {
                  const maxVal = Math.max(...data);
                  // Always at least 10, otherwise go slightly above max (rounded up)
                  return Math.max(10, Math.ceil(maxVal + 1));
                })(),
                ticks: {
                  stepSize: (() => {
                    const avg = data.reduce((a, b) => a + b, 0) / (data.length || 1);
                    return avg < 10 ? 1 : 2;
                  })(),
                  callback: function(value: number) {
                    return value % 2 === 0 ? value : '';
                  },
                  autoSkip: false // ensure all ticks are shown
                }
              }
            }
          }
        });
      });
    });
  }

  generateMonthlyWorkload(): void {
    if (!this.interview_list || !Array.isArray(this.interview_list)) {
      this.monthlyWorkload = [];
      return;
    }
    const today = new Date();
    const year = today.getFullYear();
    const month = today.getMonth();

    // Get all days in current month
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const workload: { date: string, count: number }[] = [];
    for (let d = 1; d <= daysInMonth; d++) {
      const dateObj = new Date(year, month, d);
      const dateString = [
        dateObj.getFullYear(),
        String(dateObj.getMonth() + 1).padStart(2, '0'),
        String(dateObj.getDate()).padStart(2, '0')
      ].join('-'); // yyyy-mm-dd
      const count = this.interview_list.filter((interview: any) => {
        const interviewDate = new Date(interview.date);
        return interviewDate.getFullYear() === year &&
               interviewDate.getMonth() === month &&
               interviewDate.getDate() === d;
      }).length;
      workload.push({ date: dateString, count });
    }
    // Optionally, split into weeks for display
    const weeks: { date: string, count: number }[][] = [];
    let week: { date: string, count: number }[] = [];
    for (let i = 0; i < workload.length; i++) {
      week.push(workload[i]);
      if (week.length === 7 || i === workload.length - 1) {
        weeks.push(week);
        week = [];
      }
    }
    this.monthlyWorkload = weeks;
  }

}