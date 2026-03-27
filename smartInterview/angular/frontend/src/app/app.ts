import { Component, signal } from '@angular/core';
import { Dashboard } from './dashboard/dashboard';
import { ParticleBackgroundComponent } from './particle-background/particle-background';

@Component({
  selector: 'app-root',
  imports: [Dashboard,
    ParticleBackgroundComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.scss'
}
)
export class App {
  protected readonly title = signal('frontend');
}
