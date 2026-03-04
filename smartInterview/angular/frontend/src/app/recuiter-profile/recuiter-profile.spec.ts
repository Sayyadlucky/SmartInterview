import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RecuiterProfile } from './recuiter-profile';

describe('RecuiterProfile', () => {
  let component: RecuiterProfile;
  let fixture: ComponentFixture<RecuiterProfile>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RecuiterProfile]
    })
    .compileComponents();

    fixture = TestBed.createComponent(RecuiterProfile);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
