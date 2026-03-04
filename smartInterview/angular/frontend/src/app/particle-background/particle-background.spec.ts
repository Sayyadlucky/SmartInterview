import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ParticleBackground } from './particle-background';

describe('ParticleBackground', () => {
  let component: ParticleBackground;
  let fixture: ComponentFixture<ParticleBackground>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ParticleBackground]
    })
    .compileComponents();

    fixture = TestBed.createComponent(ParticleBackground);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
