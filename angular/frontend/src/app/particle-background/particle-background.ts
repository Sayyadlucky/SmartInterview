import { Component, ElementRef, ViewChild, AfterViewInit, HostListener } from '@angular/core';

class Particle {
  constructor(
    public x: number,
    public y: number,
    public size: number,
    public vx: number,
    public vy: number
  ) {}

  update(canvasWidth: number, canvasHeight: number) {
    this.x += this.vx; this.y += this.vy;
    if (this.x < 0 || this.x > canvasWidth) this.vx *= -1;
    if (this.y < 0 || this.y > canvasHeight) this.vy *= -1;
  }
  draw(ctx: CanvasRenderingContext2D) {
    ctx.fillStyle = "rgba(0,191,255,0.7)";
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
    ctx.fill();
  }
}

@Component({
  selector: 'app-particle-background',
  templateUrl: './particle-background.html',
  styleUrls: ['./particle-background.scss']
})
export class ParticleBackgroundComponent implements AfterViewInit {
  @ViewChild('particlesCanvas', { static: true }) canvasRef!: ElementRef<HTMLCanvasElement>;
  private ctx!: CanvasRenderingContext2D;
  private particlesArray: Particle[] = [];

  ngAfterViewInit() {
    const canvas = this.canvasRef.nativeElement;
    this.ctx = canvas.getContext('2d')!;
    this.sizeCanvas();
    this.initParticles();
    this.animateParticles();
  }

  @HostListener('window:resize')
  onResize() {
    this.sizeCanvas();
    this.initParticles();
  }

  sizeCanvas() {
    const canvas = this.canvasRef.nativeElement;
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }

  initParticles() {
    const canvas = this.canvasRef.nativeElement;
    this.particlesArray = [];
    for (let i = 0; i < 60; i++) {
      const size = Math.random() * 3 + 1;
      const x = Math.random() * canvas.width;
      const y = Math.random() * canvas.height;
      const vx = (Math.random() - 0.5) * 1;
      const vy = (Math.random() - 0.5) * 1;
      this.particlesArray.push(new Particle(x, y, size, vx, vy));
    }
  }

  animateParticles = () => {
    const canvas = this.canvasRef.nativeElement;
    this.ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const p of this.particlesArray) {
      p.update(canvas.width, canvas.height);
      p.draw(this.ctx);
    }
    requestAnimationFrame(this.animateParticles);
  };
}
