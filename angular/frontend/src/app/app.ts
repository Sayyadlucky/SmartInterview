import { Component, inject } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { NavigationEnd, Router, TitleStrategy } from '@angular/router';
import { RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { ParticleBackgroundComponent } from './particle-background/particle-background';
import { AppToastStackComponent } from './core/app-toast-stack.component';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, ParticleBackgroundComponent, AppToastStackComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
}
)
export class App {
  private readonly pageTitle = inject(Title);
  private readonly router = inject(Router);
  private readonly titleStrategy = inject(TitleStrategy);

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
