const byId = (id) => document.getElementById(id);

const header = byId("mainHeader");
const menu = byId("mainMenu");
const loginSection = byId("loginSection");
const loginPanel = byId("loginPanel");
const openLoginBtn = byId("openLoginBtn");
const contactSignInBtn = byId("contactSignInBtn");
const closeLogin = byId("closeLogin");
const getStartedBtn = byId("getStartedBtn");
const loginForm = byId("loginForm");
const errorMsg = byId("errorMsg");
const mobileMenuBtn = byId("mobileMenuBtn");
const closeMobileMenu = byId("closeMobileMenu");
const mobileDrawer = byId("mobileDrawer");
const mobileDrawerBackdrop = byId("mobileDrawerBackdrop");
const drawerSignInBtn = byId("drawerSignInBtn");
const preloader = byId("preloader");
const heroSection = byId("hero");

const hasGsap = typeof window.gsap !== "undefined";
const hasScrollTrigger = typeof window.ScrollTrigger !== "undefined";
const hasThree = typeof window.THREE !== "undefined";
const isFixedHeaderPage =
  document.body?.classList.contains("candidate-login-page") ||
  document.body?.classList.contains("candidate-signup-page") ||
  document.body?.classList.contains("jobs-portal-page");

if ("scrollRestoration" in history) {
  history.scrollRestoration = "manual";
}

window.addEventListener("beforeunload", () => {
  window.scrollTo(0, 0);
});

window.addEventListener("pageshow", () => {
  window.scrollTo(0, 0);
});

function openMobileMenu() {
  mobileDrawer?.classList.add("open");
  mobileDrawer?.setAttribute("aria-hidden", "false");
  mobileDrawerBackdrop?.classList.add("show");
}

function closeMobileDrawer() {
  mobileDrawer?.classList.remove("open");
  mobileDrawer?.setAttribute("aria-hidden", "true");
  mobileDrawerBackdrop?.classList.remove("show");
}

function openLogin() {
  loginSection?.classList.remove("hidden");
  if (hasGsap) {
    gsap.set(loginPanel, { x: "100%", opacity: 0 });
    gsap.to(menu, { x: 36, duration: 0.45, ease: "power2.out" });
    gsap.to(loginPanel, { x: 0, opacity: 1, duration: 0.55, ease: "power3.out" });
  }
}

function closeLoginPanel() {
  if (!hasGsap) {
    loginSection?.classList.add("hidden");
    return;
  }
  gsap.to(menu, { x: 0, duration: 0.45, ease: "power2.out" });
  gsap.to(loginPanel, {
    x: "100%",
    opacity: 0,
    duration: 0.45,
    ease: "power2.inOut",
    onComplete: () => loginSection?.classList.add("hidden"),
  });
}

function initCoreUi() {
  const year = byId("currentYear");
  if (year) year.textContent = new Date().getFullYear();

  if (isFixedHeaderPage) {
    header?.classList.add("scrolled");
  } else {
    window.addEventListener("scroll", () => {
      header?.classList.toggle("scrolled", window.scrollY > 24);
    });
  }

  window.addEventListener("mousemove", (e) => {
    const x = (e.clientX / window.innerWidth) * 100;
    const y = (e.clientY / window.innerHeight) * 100;
    document.documentElement.style.setProperty("--mx", `${x}%`);
    document.documentElement.style.setProperty("--my", `${y}%`);
  });

  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener("click", (e) => {
      const href = anchor.getAttribute("href");
      const target = href ? document.querySelector(href) : null;
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  getStartedBtn?.addEventListener("click", () => {
    byId("features")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  mobileMenuBtn?.addEventListener("click", openMobileMenu);
  closeMobileMenu?.addEventListener("click", closeMobileDrawer);
  mobileDrawerBackdrop?.addEventListener("click", closeMobileDrawer);
  drawerSignInBtn?.addEventListener("click", () => {
    closeMobileDrawer();
    setTimeout(openLogin, 220);
  });

  document.querySelectorAll(".drawer-nav a").forEach((link) => {
    link.addEventListener("click", closeMobileDrawer);
  });
}

function initLoginPanel() {
  openLoginBtn?.addEventListener("click", openLogin);
  contactSignInBtn?.addEventListener("click", openLogin);
  closeLogin?.addEventListener("click", closeLoginPanel);

  loginSection?.addEventListener("click", (e) => {
    if (e.target === loginSection) closeLoginPanel();
  });

  document.querySelectorAll(".floating input.floating-input").forEach((input) => {
    const wrap = input.closest(".floating");
    const sync = () => wrap?.classList.toggle("has-value", !!input.value?.trim());
    input.addEventListener("input", sync);
    sync();
  });

  loginForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (errorMsg) errorMsg.textContent = "";

    try {
      const res = await fetch("login/", {
        method: "POST",
        body: new FormData(loginForm),
      });

      const data = await res.json();
      if (data.success) {
        window.location.href = "/dashboard/";
        return;
      }

      if (errorMsg) errorMsg.textContent = data.message || "Invalid username or password.";
    } catch (_err) {
      if (errorMsg) errorMsg.textContent = "Login request failed. Please try again.";
    }
  });
}

function initGsapMotion() {
  if (!hasGsap) return;
  if (!heroSection) return;
  if (hasScrollTrigger) gsap.registerPlugin(ScrollTrigger);

  const intro = gsap.timeline({ defaults: { ease: "power3.out" } });
  intro
    .from(".brand", { y: -20, opacity: 0, duration: 0.55 })
    .from("#mainMenu a", { y: -16, opacity: 0, stagger: 0.05, duration: 0.35 }, "-=0.34")
    .from("#openLoginBtn", { y: -12, opacity: 0, duration: 0.35 }, "-=0.3")
    .from("#hero h2", { y: 20, opacity: 0, duration: 0.55 }, "-=0.32")
    .from(".hero-cta .btn", { y: 10, opacity: 0, stagger: 0.08, duration: 0.35 }, "-=0.2");

  gsap.utils.toArray(".reveal-up").forEach((el) => {
    gsap.to(el, {
      opacity: 1,
      y: 0,
      duration: 0.7,
      ease: "power2.out",
      scrollTrigger: hasScrollTrigger
        ? { trigger: el, start: "top 85%" }
        : undefined,
    });
  });

  if (hasScrollTrigger) {
    gsap.set([".eyebrow", ".wordmark", ".subtitle", ".hero-stats"], { autoAlpha: 0, y: 24 });

    gsap.timeline({
      scrollTrigger: {
        trigger: "#hero",
        start: "top top",
        end: "+=55%",
        scrub: 1,
      },
    })
      .to(".eyebrow", { autoAlpha: 1, y: 0, ease: "none" }, 0.05)
      .to(".wordmark", { autoAlpha: 1, y: 0, ease: "none" }, 0.16)
      .to(".subtitle", { autoAlpha: 1, y: 0, ease: "none" }, 0.28)
      .to(".hero-stats", { autoAlpha: 1, y: 0, ease: "none" }, 0.4);

    gsap.to(".hero-orbits", {
      yPercent: 14,
      ease: "none",
      scrollTrigger: {
        trigger: "#hero",
        start: "top top",
        end: "bottom top",
        scrub: 1,
      },
    });

    const heroTl = gsap.timeline({
      scrollTrigger: {
        trigger: "#hero",
        start: "top top",
        end: "+=120%",
        scrub: 1.1,
        pin: true,
      },
    });
    heroTl
      .to(".wordmark", { scale: 0.86, y: -22, ease: "none" }, 0)
      .to(".subtitle", { y: -16, ease: "none" }, 0)
      .to(".hero-stats", { y: 14, scale: 0.98, ease: "none" }, 0)
      .to(".hero-orbits", { scale: 1.12, opacity: 0.66, ease: "none" }, 0)
      .to(".scroll-indicator", { opacity: 0, y: 20, ease: "none" }, 0);

    gsap.timeline({
      scrollTrigger: {
        trigger: "#ai-visuals",
        start: "top 85%",
        end: "bottom 20%",
        scrub: 1,
      },
    })
      .fromTo(".visuals-gallery", { y: 96, scale: 0.95, opacity: 0.82 }, { y: 0, scale: 1, opacity: 1, ease: "none" }, 0)
      .fromTo(".visuals-copy", { y: 64, opacity: 0.72 }, { y: 0, opacity: 1, ease: "none" }, 0)
      .fromTo(".shot-a", { yPercent: 14, rotate: -7 }, { yPercent: 0, rotate: -5, ease: "none" }, 0)
      .fromTo(".shot-b", { yPercent: 18, rotate: 7 }, { yPercent: 0, rotate: 4, ease: "none" }, 0)
      .fromTo(".shot-c", { yPercent: 12, rotate: -3 }, { yPercent: 0, rotate: -1, ease: "none" }, 0);
  }
}

function initCounters() {
  const counters = document.querySelectorAll(".counter");
  if (!counters.length || !hasGsap) return;

  counters.forEach((counter) => {
    const target = Number(counter.getAttribute("data-target") || 0);
    const run = () => {
      const obj = { value: 0 };
      gsap.to(obj, {
        value: target,
        duration: 1.3,
        ease: "power2.out",
        onUpdate: () => {
          counter.textContent = `${Math.round(obj.value)}%`;
        },
      });
    };

    if (hasScrollTrigger) {
      ScrollTrigger.create({
        trigger: counter,
        start: "top 92%",
        once: true,
        onEnter: run,
      });
    } else {
      run();
    }
  });
}

function initTiltCards() {
  const cards = document.querySelectorAll(".tilt-card:not(.robot-shot)");
  if (!cards.length) return;

  cards.forEach((card) => {
    card.addEventListener("mousemove", (e) => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const rx = ((y / rect.height) - 0.5) * -7;
      const ry = ((x / rect.width) - 0.5) * 9;
      card.style.transform = `perspective(1000px) rotateX(${rx}deg) rotateY(${ry}deg)`;
    });
    card.addEventListener("mouseleave", () => {
      card.style.transform = "perspective(1000px) rotateX(0deg) rotateY(0deg)";
    });
  });
}

function initMagneticButtons() {
  // Disabled magnetic translation to keep button positions stable on hover.
}

function initVisualParallax() {
  const shots = document.querySelectorAll("[data-parallax-speed]");
  if (!shots.length) return;

  const visuals = byId("ai-visuals");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let pointerX = 0;
  let pointerY = 0;

  window.addEventListener("mousemove", (e) => {
    pointerX = (e.clientX / window.innerWidth) - 0.5;
    pointerY = (e.clientY / window.innerHeight) - 0.5;
  });

  function tick() {
    let settle = 0;
    if (visuals) {
      const rect = visuals.getBoundingClientRect();
      const start = window.innerHeight;
      const end = -rect.height * 0.2;
      const progress = (start - rect.top) / (start - end);
      settle = 1 - Math.min(1, Math.max(0, progress));
    }

    shots.forEach((shot) => {
      const speed = Number(shot.getAttribute("data-parallax-speed") || 0.2);
      const y = reduced ? 0 : settle * speed * 30;
      const mx = reduced ? 0 : pointerX * speed * 20;
      const my = reduced ? 0 : pointerY * speed * 16;
      shot.style.transform = `translate3d(${mx}px, ${my + y}px, 0) rotate(var(--base-rot, 0deg))`;
    });
    requestAnimationFrame(tick);
  }
  tick();
}

function initParticles() {
  const canvas = byId("particles");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  let points = [];
  const isReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pointCount = isReduced ? 45 : 110;

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }

  function seed() {
    points = Array.from({ length: pointCount }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      vx: (Math.random() - 0.5) * 0.25,
      vy: (Math.random() - 0.5) * 0.25,
      r: Math.random() * 1.5 + 0.35,
    }));
  }

  function tick() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (let i = 0; i < points.length; i++) {
      const p = points[i];
      p.x += p.vx;
      p.y += p.vy;

      if (p.x < 0 || p.x > canvas.width) p.vx *= -1;
      if (p.y < 0 || p.y > canvas.height) p.vy *= -1;

      ctx.fillStyle = "rgba(102, 226, 255, 0.38)";
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();

      for (let j = i + 1; j < points.length; j++) {
        const q = points[j];
        const dx = p.x - q.x;
        const dy = p.y - q.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 120) {
          ctx.strokeStyle = `rgba(88, 164, 255, ${(1 - dist / 120) * 0.15})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(q.x, q.y);
          ctx.stroke();
        }
      }
    }

    requestAnimationFrame(tick);
  }

  resize();
  seed();
  tick();
  window.addEventListener("resize", () => {
    resize();
    seed();
  });
}

function initThreeScene() {
  const wrap = byId("scene3d");
  if (!wrap || !hasThree) return;

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x050b18, 0.038);
  const camera = new THREE.PerspectiveCamera(58, window.innerWidth / window.innerHeight, 0.1, 1000);
  camera.position.set(0, 0.2, 8.4);

  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  wrap.appendChild(renderer.domElement);

  const EffectComposerCtor = THREE.EffectComposer || window.EffectComposer;
  const RenderPassCtor = THREE.RenderPass || window.RenderPass;
  const UnrealBloomPassCtor = THREE.UnrealBloomPass || window.UnrealBloomPass;
  const composer = (EffectComposerCtor && RenderPassCtor && UnrealBloomPassCtor)
    ? new EffectComposerCtor(renderer)
    : null;

  const heroGroup = new THREE.Group();
  heroGroup.position.z = -1.6;
  scene.add(heroGroup);

  const torus = new THREE.Mesh(
    new THREE.TorusKnotGeometry(1.72, 0.35, 220, 38),
    new THREE.MeshStandardMaterial({
      color: 0x66dcff,
      emissive: 0x10274f,
      roughness: 0.16,
      metalness: 0.9,
    })
  );
  torus.position.set(0, 0.2, -1.8);
  heroGroup.add(torus);

  const core = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.95, 0),
    new THREE.MeshPhysicalMaterial({
      color: 0x9fe4ff,
      transparent: true,
      opacity: 0.9,
      roughness: 0.05,
      metalness: 0.2,
      transmission: 0.22,
      clearcoat: 1,
      clearcoatRoughness: 0.14,
      emissive: 0x17305f,
    })
  );
  heroGroup.add(core);

  const wireShell = new THREE.Mesh(
    new THREE.IcosahedronGeometry(1.45, 1),
    new THREE.MeshBasicMaterial({
      color: 0x70d9ff,
      wireframe: true,
      transparent: true,
      opacity: 0.45,
    })
  );
  heroGroup.add(wireShell);

  const orbitalA = new THREE.Mesh(
    new THREE.TorusGeometry(2.9, 0.022, 16, 280),
    new THREE.MeshBasicMaterial({ color: 0x8cb9ff, transparent: true, opacity: 0.46 })
  );
  orbitalA.rotation.set(1.16, 0, 0.25);
  orbitalA.position.set(0, -0.68, -2.45);
  heroGroup.add(orbitalA);

  const orbitalB = orbitalA.clone();
  orbitalB.material = orbitalA.material.clone();
  orbitalB.material.opacity = 0.26;
  orbitalB.scale.set(1.22, 1.22, 1.22);
  orbitalB.rotation.z = 0.86;
  heroGroup.add(orbitalB);

  const halo = new THREE.Mesh(
    new THREE.TorusGeometry(3.35, 0.05, 20, 320),
    new THREE.MeshBasicMaterial({ color: 0x6fe2ff, transparent: true, opacity: 0.24 })
  );
  halo.rotation.set(1.1, 0.2, 0.3);
  heroGroup.add(halo);

  const shards = new THREE.Group();
  for (let i = 0; i < 12; i++) {
    const shard = new THREE.Mesh(
      new THREE.ConeGeometry(0.06, 0.45, 4),
      new THREE.MeshStandardMaterial({
        color: 0x8be8ff,
        emissive: 0x122a53,
        metalness: 0.7,
        roughness: 0.2,
      })
    );
    const a = (Math.PI * 2 * i) / 12;
    const r = 2.3 + Math.random() * 0.6;
    shard.position.set(Math.cos(a) * r, (Math.random() - 0.5) * 1.8, Math.sin(a) * r);
    shard.lookAt(0, 0, 0);
    shards.add(shard);
  }
  heroGroup.add(shards);

  const starsGeometry = new THREE.BufferGeometry();
  const starsCount = 2600;
  const starPositions = new Float32Array(starsCount * 3);
  const starColors = new Float32Array(starsCount * 3);
  for (let i = 0; i < starsCount; i++) {
    const s = i * 3;
    const radius = 10 + Math.random() * 24;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos((Math.random() * 2) - 1);
    starPositions[s] = radius * Math.sin(phi) * Math.cos(theta);
    starPositions[s + 1] = radius * Math.sin(phi) * Math.sin(theta);
    starPositions[s + 2] = radius * Math.cos(phi);

    const blend = Math.random();
    starColors[s] = 0.55 + blend * 0.25;
    starColors[s + 1] = 0.72 + blend * 0.18;
    starColors[s + 2] = 1.0;
  }
  starsGeometry.setAttribute("position", new THREE.BufferAttribute(starPositions, 3));
  starsGeometry.setAttribute("color", new THREE.BufferAttribute(starColors, 3));

  const starField = new THREE.Points(
    starsGeometry,
    new THREE.PointsMaterial({
      size: 0.028,
      transparent: true,
      opacity: 0.74,
      vertexColors: true,
    })
  );
  scene.add(starField);

  const ambient = new THREE.AmbientLight(0x7898ff, 0.6);
  const key = new THREE.PointLight(0x8cf4ff, 1.5, 120);
  key.position.set(4, 2, 8);
  const fill = new THREE.PointLight(0x5a77ff, 1.12, 120);
  fill.position.set(-4, -1, 6);
  const low = new THREE.PointLight(0x6ed6ff, 0.92, 120);
  low.position.set(0, -4, 6);
  scene.add(ambient, key, fill, low);

  if (composer) {
    const renderPass = new RenderPassCtor(scene, camera);
    const bloomPass = new UnrealBloomPassCtor(
      new THREE.Vector2(window.innerWidth, window.innerHeight),
      1.55,
      0.9,
      0.05
    );
    composer.addPass(renderPass);
    composer.addPass(bloomPass);
  }

  const mouse = { x: 0, y: 0 };
  window.addEventListener("mousemove", (e) => {
    mouse.x = (e.clientX / window.innerWidth) * 2 - 1;
    mouse.y = -(e.clientY / window.innerHeight) * 2 + 1;
  });

  if (hasGsap && hasScrollTrigger) {
    gsap.to(camera.position, {
      z: 5.5,
      x: 1.25,
      y: 0.66,
      ease: "none",
      scrollTrigger: {
        trigger: "#new-features",
        start: "top bottom",
        end: "bottom top",
        scrub: 1.2,
      },
    });

    gsap.to(heroGroup.rotation, {
      x: 1.0,
      y: Math.PI * 1.24,
      z: 0.44,
      ease: "none",
      scrollTrigger: {
        trigger: "#platform",
        start: "top bottom",
        end: "bottom top",
        scrub: 1.3,
      },
    });

    gsap.to(heroGroup.position, {
      z: -1.35,
      y: 0.35,
      ease: "none",
      scrollTrigger: {
        trigger: "#new-features",
        start: "top bottom",
        end: "bottom top",
        scrub: 1.2,
      },
    });
  }

  const clock = new THREE.Clock();
  function animate() {
    const t = clock.getElapsedTime();

    torus.rotation.x += 0.006;
    torus.rotation.y += 0.008;
    core.rotation.x -= 0.004;
    core.rotation.y += 0.005;
    wireShell.rotation.x += 0.0028;
    wireShell.rotation.y -= 0.0034;
    orbitalA.rotation.z += 0.0019;
    orbitalB.rotation.z -= 0.0013;
    halo.rotation.z += 0.0009;
    halo.rotation.y += 0.0006;
    shards.rotation.y += 0.0024;
    shards.rotation.x += 0.0008;
    starField.rotation.y += 0.00042;

    heroGroup.position.x += (mouse.x * 0.56 - heroGroup.position.x) * 0.03;
    heroGroup.position.y += (mouse.y * 0.34 - heroGroup.position.y) * 0.03;
    heroGroup.position.z = -2.0 + Math.sin(t * 0.9) * 0.12;
    core.scale.setScalar(1 + Math.sin(t * 2.2) * 0.03);
    halo.scale.setScalar(1 + Math.sin(t * 1.6) * 0.03);

    if (composer) composer.render();
    else renderer.render(scene, camera);

    requestAnimationFrame(animate);
  }

  animate();

  window.addEventListener("resize", () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
    composer?.setSize(window.innerWidth, window.innerHeight);
  });
}

function init() {
  window.scrollTo(0, 0);

  initCoreUi();
  initLoginPanel();
  initMagneticButtons();
  initVisualParallax();
  initGsapMotion();
  initCounters();
  initTiltCards();
  initParticles();
  initThreeScene();

  if (preloader) {
    setTimeout(() => {
      preloader.classList.add("hide");
    }, 700);
  }
}

window.addEventListener("DOMContentLoaded", init);
