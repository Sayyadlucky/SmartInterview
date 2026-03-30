import { Component, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { ParticleBackgroundComponent } from './particle-background/particle-background';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, ParticleBackgroundComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
}
)
export class App {
  protected readonly title = signal('frontend');
}
