import { ComponentFixture, TestBed } from '@angular/core/testing';

import { Evaluators } from './evaluators';

describe('Evaluators', () => {
  let component: Evaluators;
  let fixture: ComponentFixture<Evaluators>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Evaluators]
    })
    .compileComponents();

    fixture = TestBed.createComponent(Evaluators);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
