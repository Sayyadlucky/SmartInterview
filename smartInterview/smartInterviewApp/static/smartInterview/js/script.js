// dynamically set current year
document.getElementById("currentYear").textContent = new Date().getFullYear();

// intro animations (unchanged)
gsap.from("#mainHeader", { y: -60, opacity: 0, duration: 1, ease: "power3.out" });
gsap.to("#hero h1", { opacity: 1, y: -20, duration: 1, ease: "power3.out" });
gsap.to("#hero p", { opacity: 1, y: -10, duration: 1, ease: "power3.out", delay: 0.3 });
gsap.to("#hero button", { opacity: 1, y: -5, duration: 1, ease: "power3.out", delay: 0.6 });

// DOM refs and state
const getStartedBtn = document.getElementById("getStartedBtn");
const openLoginBtn = document.getElementById("openLoginBtn");
const hero = document.getElementById("hero");
const loginSection = document.getElementById("loginSection");
const loginPanel = document.getElementById("loginPanel");
const closeLogin = document.getElementById("closeLogin");
const menu = document.getElementById("mainMenu");
const header = document.getElementById("mainHeader");

let menuShifted = false;
let isAnimating = false;

// compute dx (keeps your previous approach)
function computeDx(gap = 20) {
  const brandEl = header.querySelector(".flex");
  const container = header.querySelector(".max-w-7xl");
  const brandRect = brandEl.getBoundingClientRect();
  const menuRect  = menu.getBoundingClientRect();
  const containerRect = container.getBoundingClientRect();
  const desiredLeft = brandRect.right + gap;
  const menuLeft = menuRect.left;
  return desiredLeft - menuLeft;
}

// GET STARTED -> smooth scroll to features (does not hide hero)
getStartedBtn.addEventListener("click", (e) => {
  e.preventDefault();
  const features = document.getElementById('features');
  if (features) {
    features.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
});

// OPEN login panel (header sign-in button)
openLoginBtn.addEventListener("click", () => {
  if (isAnimating) return;
  isAnimating = true;

  // show overlay and animate menu shift & panel in
  loginSection.classList.remove("hidden");
  header.classList.add("overlay");

  const dx = computeDx(20);
  gsap.to(menu, { x: dx, duration: 0.7, ease: "power3.out" });
  menuShifted = true;

  gsap.fromTo(loginPanel, { x: "100%", opacity: 0 }, {
    x: 0, opacity: 1, duration: 0.9, ease: "power3.out",
    onComplete: () => { isAnimating = false; }
  });
});

// CLOSE: reliable timeline and reset (same logic as before)
closeLogin.addEventListener("click", () => {
  if (isAnimating) return;
  isAnimating = true;

  const tl = gsap.timeline({
    defaults: { duration: 0.7, ease: "power3.out" }
  });

  // slide panel out and menu back concurrently
  tl.to(loginPanel, { x: "100%", opacity: 0, ease: "power3.in" }, 0);
  tl.to(menu, { x: 0 }, 0);

  // after animations, reset state
  tl.add(() => {
    loginSection.classList.add("hidden");
    gsap.set(loginPanel, { clearProps: "all" });
    gsap.set(menu, { clearProps: "transform" });
    header.classList.remove("overlay");
  });

  // finish: clear flags
  tl.add(() => {
    menuShifted = false;
    isAnimating = false;
  }, "+=0");
});

// Particle Background (unchanged)
const canvas = document.getElementById("particles");
const ctx = canvas.getContext("2d");
let particlesArray = [];

function sizeCanvas() {
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
}
sizeCanvas();

class Particle {
  constructor(x, y, size, vx, vy) {
    this.x = x; this.y = y; this.size = size; this.vx = vx; this.vy = vy;
  }
  update() {
    this.x += this.vx; this.y += this.vy;
    if (this.x < 0 || this.x > canvas.width) this.vx *= -1;
    if (this.y < 0 || this.y > canvas.height) this.vy *= -1;
  }
  draw() {
    ctx.fillStyle = "rgba(0,191,255,0.7)";
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
    ctx.fill();
  }
}

function initParticles() {
  particlesArray = [];
  for (let i = 0; i < 50; i++) {
    const size = Math.random() * 3 + 1;
    const x = Math.random() * canvas.width;
    const y = Math.random() * canvas.height;
    const vx = (Math.random() - 0.5) * 1;
    const vy = (Math.random() - 0.5) * 1;
    particlesArray.push(new Particle(x, y, size, vx, vy));
  }
}

function animateParticles() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  for (const p of particlesArray) { p.update(); p.draw(); }
  connectParticles();
  requestAnimationFrame(animateParticles);
}
function connectParticles() {
      for (let a = 0; a < particlesArray.length; a++) {
        for (let b = a + 1; b < particlesArray.length; b++) {
          const dx = particlesArray[a].x - particlesArray[b].x;
          const dy = particlesArray[a].y - particlesArray[b].y;
          const dist = Math.sqrt(dx*dx + dy*dy);
          if (dist < 120) {
            ctx.strokeStyle = "rgba(0,191,255," + (1 - dist/120) + ")";
            ctx.lineWidth = 0.5;
            ctx.beginPath();
            ctx.moveTo(particlesArray[a].x, particlesArray[a].y);
            ctx.lineTo(particlesArray[b].x, particlesArray[b].y);
            ctx.stroke();
          }
        }
      }
    }
window.addEventListener("resize", () => { sizeCanvas(); initParticles(); });
initParticles();
animateParticles();

function scrollToElement(targetEl, duration = 600) {
const headerOffset = document.getElementById('mainHeader').offsetHeight;
const targetPosition = targetEl.getBoundingClientRect().top + window.pageYOffset - headerOffset;
const startPosition = window.pageYOffset;
const distance = targetPosition - startPosition;
let startTime = null;

function animation(currentTime) {
if (startTime === null) startTime = currentTime;
const timeElapsed = currentTime - startTime;
const run = ease(timeElapsed, startPosition, distance, duration);
window.scrollTo(0, run);
if (timeElapsed < duration) requestAnimationFrame(animation);
}

// Ease function (easeInOutCubic)
function ease(t, b, c, d) {
t /= d / 2;
if (t < 1) return (c / 2) * t * t * t + b;
t -= 2;
return (c / 2) * (t * t * t + 2) + b;
}

requestAnimationFrame(animation);
}

// Attach to anchor links
document.querySelectorAll('a[href^="#"]').forEach(link => {
link.addEventListener('click', function(e) {
e.preventDefault();
const targetId = this.getAttribute('href').substring(1);
const targetEl = document.getElementById(targetId);
if (targetEl) scrollToElement(targetEl, 800); // duration in ms
});
});

document.getElementById('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault(); // stop page reload
    const formData = new FormData(e.target);

    const res = await fetch("login/", {
        method: 'POST',
        body: formData,
    });
    const data = await res.json();

    if (data.success) {
        window.location.href = '/dashboard/';
    } else {
        document.getElementById('errorMsg').innerText = data.message;
    }
});