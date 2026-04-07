import { Component, inject, signal } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { NavigationEnd, Router, TitleStrategy } from '@angular/router';
import { RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { ParticleBackgroundComponent } from './particle-background/particle-background';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, ParticleBackgroundComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
}
)
export class App {
  private readonly pageTitle = inject(Title);
  private readonly router = inject(Router);
  private readonly titleStrategy = inject(TitleStrategy);
  protected readonly appName = signal('frontend');

  constructor() {
    this.applyRouteTitle();
    this.router.events
      .pipe(filter((event) => event instanceof NavigationEnd))
      .subscribe(() => this.applyRouteTitle());
  }

  private applyRouteTitle(): void {
    const nextTitle = this.titleStrategy.buildTitle(this.router.routerState.snapshot) || 'Hiring Dashboard | Shortlistii';
    this.pageTitle.setTitle(nextTitle);
  }
}
