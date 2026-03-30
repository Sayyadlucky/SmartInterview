import { Routes } from '@angular/router';
import { Dashboard } from './dashboard/dashboard';
import { Jobs } from './jobs/jobs';

export const routes: Routes = [
  {
    path: 'dashboard',
    children: [
      {
        path: '',
        component: Dashboard,
      },
      {
        path: 'jobs',
        component: Jobs,
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
    redirectTo: 'dashboard',
  }
];
