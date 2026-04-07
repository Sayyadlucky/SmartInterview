import { Routes } from '@angular/router';
import { Dashboard } from './dashboard/dashboard';
import { Jobs } from './jobs/jobs';
import { ErrorState } from './error-state/error-state';

export const routes: Routes = [
  {
    path: 'dashboard',
    children: [
      {
        path: '',
        component: Dashboard,
        title: 'Hiring Dashboard | Shortlistii',
      },
      {
        path: 'jobs',
        component: Jobs,
        title: 'Job Postings | Shortlistii',
      },
      {
        path: 'not-found',
        component: ErrorState,
        title: '404 | Shortlistii',
        data: { variant: 'not-found' },
      },
      {
        path: 'technical-error',
        component: ErrorState,
        title: 'Technical Error | Shortlistii',
        data: { variant: 'technical' },
      },
      {
        path: '**',
        component: ErrorState,
        title: '404 | Shortlistii',
        data: { variant: 'not-found' },
      },
    ]
  },
  {
    path: '',
    redirectTo: 'dashboard',
    pathMatch: 'full'
  },
  {
    path: '**',
    redirectTo: 'dashboard/not-found',
  }
];
