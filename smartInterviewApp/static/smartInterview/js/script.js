const byId = (id) => document.getElementById(id);

const header = byId("mainHeader") || document.querySelector(".legal-header");
const menu = byId("mainMenu");
const loginSection = byId("loginSection");
const loginPanel = byId("loginPanel");
const openLoginBtn = byId("openLoginBtn");
const contactSignInBtn = byId("contactSignInBtn");
const closeLogin = byId("closeLogin");
const getStartedBtn = byId("getStartedBtn");
const loginForm = byId("loginForm");
const signInBtn = byId("signInBtn");
const workspaceForgotPasswordTrigger = byId("workspaceForgotPasswordTrigger");
const workspaceResetOverlay = byId("workspaceResetOverlay");
const workspaceResetClose = byId("workspaceResetClose");
const workspaceResetProceed = byId("workspaceResetProceed");
const errorMsg = byId("errorMsg");
const mobileMenuBtn = byId("mobileMenuBtn");
const closeMobileMenu = byId("closeMobileMenu");
const mobileDrawer = byId("mobileDrawer");
const mobileDrawerBackdrop = byId("mobileDrawerBackdrop");
const drawerSignInBtn = byId("drawerSignInBtn");
const heroSection = byId("hero");
const isLandingPage = document.body?.classList.contains("landing-page");

const hasGsap = typeof window.gsap !== "undefined";
const hasScrollTrigger = typeof window.ScrollTrigger !== "undefined";
const hasThree = typeof window.THREE !== "undefined";
const isFixedHeaderPage =
  document.body?.classList.contains("candidate-login-page") ||
  document.body?.classList.contains("candidate-signup-page") ||
  document.body?.classList.contains("jobs-portal-page");

if ("scrollRestoration" in history && !window.location.hash) {
  history.scrollRestoration = "manual";
}

window.addEventListener("beforeunload", () => {
  if (window.location.hash) return;
  window.scrollTo(0, 0);
});

window.addEventListener("pageshow", () => {
  if (window.location.hash) return;
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

  const getHeaderOffset = () => {
    if (!header) return 0;
    return Math.round(header.getBoundingClientRect().height);
  };

  const syncScrollPadding = () => {
    document.documentElement.style.scrollPaddingTop = `${getHeaderOffset() + 34}px`;
  };

  const scrollToTarget = (target, { behavior = "smooth" } = {}) => {
    if (!target) return;
    const headerOffset = getHeaderOffset();
    const top = window.scrollY + target.getBoundingClientRect().top - headerOffset - 34;
    window.scrollTo({
      top: Math.max(0, top),
      behavior,
    });
  };

  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener("click", (e) => {
      const href = anchor.getAttribute("href");
      if (!href || href === "#") return;
      const target = href ? document.querySelector(href) : null;
      if (!target) return;
      e.preventDefault();
      scrollToTarget(target);
    });
  });

  const sanitizeDigits = (value) => (value || "").replace(/\D/g, "");
  document.querySelectorAll("input[data-digits-only]").forEach((input) => {
    if (input.dataset.digitsBound === "true") return;
    input.dataset.digitsBound = "true";

    input.addEventListener("input", () => {
      const sanitized = sanitizeDigits(input.value);
      if (sanitized !== input.value) {
        input.value = sanitized;
      }
    });

    input.addEventListener("paste", (event) => {
      const pasted = event.clipboardData?.getData("text") || "";
      if (!/\D/.test(pasted)) return;
      event.preventDefault();
      input.value = sanitizeDigits(pasted);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });

    input.addEventListener("drop", (event) => event.preventDefault());
  });

  syncScrollPadding();
  window.addEventListener("resize", syncScrollPadding);

  if (window.location.hash) {
    window.requestAnimationFrame(() => {
      const target = document.querySelector(window.location.hash);
      if (target) scrollToTarget(target, { behavior: "auto" });
    });
  }

  getStartedBtn?.addEventListener("click", (e) => {
    const targetSelector = getStartedBtn.getAttribute("data-scroll-target");
    const target = targetSelector ? document.querySelector(targetSelector) : null;
    if (!target) return;
    e.preventDefault();
    scrollToTarget(target);
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

function initLegalToc() {
  const toc = document.querySelector(".legal-toc");
  if (!toc) return;

  const links = Array.from(toc.querySelectorAll('a[href^="#"]'));
  if (!links.length) return;

  const sections = links
    .map((link) => {
      const href = link.getAttribute("href");
      const section = href ? document.querySelector(href) : null;
      return section ? { link, section } : null;
    })
    .filter(Boolean);

  if (!sections.length) return;

  const setActive = (id) => {
    sections.forEach(({ link, section }) => {
      const active = section.id === id;
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  };

  const getHeaderOffset = () => {
    if (!header) return 0;
    return Math.round(header.getBoundingClientRect().height);
  };

  const updateActiveSection = () => {
    const marker = window.scrollY + getHeaderOffset() + 64;
    let activeId = sections[0].section.id;

    sections.forEach(({ section }) => {
      const sectionTop = window.scrollY + section.getBoundingClientRect().top;
      if (sectionTop <= marker) activeId = section.id;
    });

    setActive(activeId);
  };

  let ticking = false;
  const handleScroll = () => {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(() => {
      updateActiveSection();
      ticking = false;
    });
  };

  updateActiveSection();
  window.addEventListener("scroll", handleScroll, { passive: true });
  window.addEventListener("resize", updateActiveSection);
}

function initLoginPanel() {
  const defaultSignInMarkup = signInBtn?.innerHTML || "";
  let loginSubmitting = false;

  const setLoginSubmitting = (submitting) => {
    if (!signInBtn) return;
    loginSubmitting = submitting;
    signInBtn.disabled = submitting;
    signInBtn.classList.toggle("is-loading", submitting);

    if (submitting) {
      signInBtn.setAttribute("aria-busy", "true");
      signInBtn.innerHTML = '<span class="btn-spinner" aria-hidden="true"></span><span class="btn-label">Signing in</span>';
      return;
    }

    signInBtn.removeAttribute("aria-busy");
    signInBtn.innerHTML = defaultSignInMarkup;
  };

  openLoginBtn?.addEventListener("click", openLogin);
  contactSignInBtn?.addEventListener("click", openLogin);
  document.querySelectorAll("[data-open-login]").forEach((trigger) => {
    trigger.addEventListener("click", openLogin);
  });
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
    if (loginSubmitting) return;
    if (errorMsg) errorMsg.textContent = "";
    setLoginSubmitting(true);

    try {
      const res = await fetch("login/", {
        method: "POST",
        body: new FormData(loginForm),
      });

      const data = await res.json();
      if (data.success) {
        window.location.href = data.redirect_url || "/dashboard/";
        return;
      }

      if (errorMsg) errorMsg.textContent = data.message || "Invalid username or password.";
      setLoginSubmitting(false);
    } catch (_err) {
      if (errorMsg) errorMsg.textContent = "Login request failed. Please try again.";
      setLoginSubmitting(false);
    }
  });
}

function initWorkspacePasswordReset() {
  if (!workspaceResetOverlay || !workspaceForgotPasswordTrigger) return;

  const copy = byId("workspaceResetCopy");
  const messageBox = byId("workspaceResetMessage");
  const indicators = Array.from(document.querySelectorAll("[data-workspace-step-indicator]"));
  const stepMap = {
    1: byId("workspaceResetEmailStep"),
    2: byId("workspaceResetPhoneStep"),
    3: byId("workspaceResetOtpStep"),
    4: byId("workspaceResetPasswordStep"),
    5: byId("workspaceResetSuccessStep"),
  };
  const state = { step: 1, maskedPhone: "", lastFour: "" };

  const setStep = (step) => {
    state.step = step;
    Object.entries(stepMap).forEach(([key, panel]) => {
      if (!panel) return;
      panel.classList.toggle("is-active", Number(key) === step);
    });
    indicators.forEach((indicator, index) => {
      const value = index + 1;
      indicator.classList.toggle("is-active", value === Math.min(step, 4));
      indicator.classList.toggle("is-complete", value < Math.min(step, 5));
    });
  };

  const showMessage = (text, type = "") => {
    if (!messageBox) return;
    if (!text) {
      messageBox.textContent = "";
      messageBox.className = "workspace-reset-message";
      return;
    }
    messageBox.textContent = text;
    messageBox.className = `workspace-reset-message is-visible ${type ? `is-${type}` : ""}`.trim();
  };

  const resetFlow = () => {
    state.step = 1;
    state.maskedPhone = "";
    state.lastFour = "";
    byId("workspaceResetEmailStep")?.reset();
    byId("workspaceResetPhoneStep")?.reset();
    byId("workspaceResetOtpStep")?.reset();
    byId("workspaceResetPasswordStep")?.reset();
    const lastFour = byId("workspaceResetLastFour");
    const maskedPhone = byId("workspaceResetMaskedPhone");
    if (lastFour) lastFour.textContent = "0000";
    if (maskedPhone) maskedPhone.textContent = "••••";
    if (copy) copy.textContent = "Verify your admin or recruiter account in a few secure steps and set a new password.";
    showMessage("");
    setStep(1);
  };

  const openModal = () => {
    resetFlow();
    workspaceResetOverlay.classList.add("is-open");
    workspaceResetOverlay.setAttribute("aria-hidden", "false");
  };

  const closeModal = () => {
    workspaceResetOverlay.classList.remove("is-open");
    workspaceResetOverlay.setAttribute("aria-hidden", "true");
  };

  const getCookie = (name) => {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  };

  const postForm = async (url, payload) => {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken"),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: payload,
    });

    const rawText = await response.text();
    let data = null;
    try {
      data = rawText ? JSON.parse(rawText) : null;
    } catch (_error) {
      data = null;
    }

    if (!response.ok || !data?.Success) {
      throw new Error((data && data.Error) || "Unable to complete this step right now. Please verify your details and try again.");
    }
    return data;
  };

  const setLoadingState = (button, label) => {
    if (!button) return;
    button.disabled = true;
    button.classList.add("is-loading");
    button.setAttribute("aria-busy", "true");
    button.dataset.originalLabel = button.dataset.originalLabel || button.textContent.trim() || "Continue";
    button.innerHTML = `<span class="btn-spinner" aria-hidden="true"></span><span class="btn-label">${label}</span>`;
  };

  const resetLoadingState = (button) => {
    if (!button) return;
    const originalLabel = button.dataset.originalLabel || "Continue";
    button.disabled = false;
    button.classList.remove("is-loading");
    button.removeAttribute("aria-busy");
    button.innerHTML = `<span class="btn-label">${originalLabel}</span>`;
  };

  workspaceForgotPasswordTrigger.addEventListener("click", (event) => {
    event.preventDefault();
    closeLoginPanel();
    window.setTimeout(openModal, hasGsap ? 240 : 0);
  });

  workspaceResetClose?.addEventListener("click", closeModal);
  workspaceResetProceed?.addEventListener("click", () => {
    closeModal();
    window.setTimeout(openLogin, 120);
  });

  workspaceResetOverlay.addEventListener("click", (event) => {
    if (event.target === workspaceResetOverlay) closeModal();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && workspaceResetOverlay.classList.contains("is-open")) {
      closeModal();
    }
  });

  byId("workspaceResetEmailStep")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    showMessage("");
    const formData = new FormData(event.currentTarget);
    const submitButton = event.currentTarget.querySelector('button[type="submit"]');
    setLoadingState(submitButton, "Checking...");
    try {
      const data = await postForm("/workspace/password-reset/start/", formData);
      state.maskedPhone = data.Data.masked_phone || "••••";
      state.lastFour = data.Data.last_four || "0000";
      const lastFour = byId("workspaceResetLastFour");
      const maskedPhone = byId("workspaceResetMaskedPhone");
      if (lastFour) lastFour.textContent = state.lastFour;
      if (maskedPhone) maskedPhone.textContent = state.maskedPhone;
      if (copy) copy.textContent = "Confirm the mobile number linked to your workspace account before we send a one-time password.";
      showMessage("");
      setStep(2);
      resetLoadingState(submitButton);
    } catch (error) {
      resetLoadingState(submitButton);
      showMessage(error.message, "error");
    }
  });

  byId("workspaceResetPhoneStep")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    showMessage("");
    const formData = new FormData(event.currentTarget);
    const submitButton = event.currentTarget.querySelector('button[type="submit"]');
    setLoadingState(submitButton, "Sending OTP...");
    try {
      const data = await postForm("/workspace/password-reset/verify-phone/", formData);
      if (copy) copy.textContent = "Enter the OTP sent to your registered mobile number to continue securely.";
      showMessage(data.Data?.message || "OTP sent successfully.", "success");
      const maskedPhone = byId("workspaceResetMaskedPhone");
      if (maskedPhone) maskedPhone.textContent = data.Data?.masked_phone || state.maskedPhone;
      setStep(3);
      resetLoadingState(submitButton);
    } catch (error) {
      resetLoadingState(submitButton);
      showMessage(error.message, "error");
    }
  });

  byId("workspaceResetOtpStep")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    showMessage("");
    const formData = new FormData(event.currentTarget);
    const submitButton = event.currentTarget.querySelector('button[type="submit"]');
    setLoadingState(submitButton, "Verifying...");
    try {
      const data = await postForm("/workspace/password-reset/verify-otp/", formData);
      if (copy) copy.textContent = "Set a new password for your workspace account.";
      showMessage(data.Data?.message || "OTP verified successfully.", "success");
      setStep(4);
      resetLoadingState(submitButton);
    } catch (error) {
      resetLoadingState(submitButton);
      showMessage(error.message, "error");
    }
  });

  byId("workspaceResetPasswordStep")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    showMessage("");
    const formData = new FormData(event.currentTarget);
    const submitButton = event.currentTarget.querySelector('button[type="submit"]');
    setLoadingState(submitButton, "Updating...");
    try {
      const data = await postForm("/workspace/password-reset/complete/", formData);
      showMessage("");
      if (copy) copy.textContent = data.Data?.message || "Your password has been updated successfully.";
      setStep(5);
      resetLoadingState(submitButton);
    } catch (error) {
      resetLoadingState(submitButton);
      showMessage(error.message, "error");
    }
  });
}

function initRevealOnScroll() {
  if (hasGsap) return;
  const elements = document.querySelectorAll(".reveal-up");
  if (!elements.length) return;

  const reveal = (el) => {
    el.style.opacity = "1";
    el.style.transform = "translateY(0)";
  };

  if (!("IntersectionObserver" in window)) {
    elements.forEach(reveal);
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        reveal(entry.target);
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.14, rootMargin: "0px 0px -8% 0px" }
  );

  elements.forEach((element) => observer.observe(element));
}

function initContactPage() {
  if (!document.body?.classList.contains("contact-page-shell")) return;

  const form = document.querySelector(".contact-form");
  const submitBtn = form?.querySelector(".contact-submit-btn");
  const submitLabel = submitBtn?.querySelector(".contact-submit-btn__label");
  const successModal = byId("contactSuccessModal");
  const closeButtons = successModal?.querySelectorAll("[data-close-contact-success]");

  if (form && submitBtn && submitLabel) {
    form.addEventListener("submit", () => {
      if (submitBtn.disabled) return;
      submitBtn.disabled = true;
      submitBtn.classList.add("is-submitting");
      submitBtn.setAttribute("aria-busy", "true");
      submitLabel.textContent = submitBtn.getAttribute("data-loading-label") || "Sending Inquiry";
    });
  }

  if (!successModal) return;

  const closeModal = () => {
    successModal.classList.remove("is-open");
    successModal.setAttribute("aria-hidden", "true");
  };

  const openModal = () => {
    successModal.classList.add("is-open");
    successModal.setAttribute("aria-hidden", "false");
  };

  closeButtons?.forEach((trigger) => {
    trigger.addEventListener("click", closeModal);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && successModal.classList.contains("is-open")) closeModal();
  });

  window.requestAnimationFrame(openModal);
}

function initLandingMotion() {
  if (!isLandingPage || !hasGsap || !heroSection) return;
  if (hasScrollTrigger) gsap.registerPlugin(ScrollTrigger);

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const intro = gsap.timeline({ defaults: { ease: "power3.out" } });

  intro
    .from(".brand", { y: -18, opacity: 0, duration: 0.48 })
    .from("#mainMenu a", { y: -12, opacity: 0, stagger: 0.05, duration: 0.28 }, "-=0.3")
    .from("#openLoginBtn", { y: -12, opacity: 0, duration: 0.28 }, "-=0.26")
    .from(".hero-glow", { scale: 0.84, opacity: 0, stagger: 0.12, duration: 0.9 }, "-=0.28")
    .from(".hero-beam", { y: 24, opacity: 0, stagger: 0.1, duration: 0.7 }, "-=0.6")
    .from(".hero-copy .eyebrow", { y: 16, opacity: 0, duration: 0.34 }, "-=0.52")
    .from(".hero-wordmark", { y: 20, opacity: 0, duration: 0.48 }, "-=0.18")
    .from(".hero-title", { y: 28, opacity: 0, duration: 0.62 }, "-=0.28")
    .from(".hero-subtitle", { y: 20, opacity: 0, duration: 0.52 }, "-=0.32")
    .from(".hero-actions .btn", { y: 12, opacity: 0, stagger: 0.08, duration: 0.32 }, "-=0.22")
    .from(".hero-link-row > *", { y: 10, opacity: 0, stagger: 0.05, duration: 0.26 }, "-=0.2")
    .from(".hero-trust .context-chip", { y: 12, opacity: 0, stagger: 0.05, duration: 0.26 }, "-=0.16")
    .from(".hiring-flow-strip", { y: 18, opacity: 0, duration: 0.34 }, "-=0.14")
    .from(".hiring-flow-step", { y: 10, opacity: 0, stagger: 0.05, duration: 0.24 }, "-=0.18")
    .from(".hero-visual", { x: 28, opacity: 0, scale: 0.98, duration: 0.65 }, "-=0.46")
    .from(
      [".hero-visual-window", ".hero-floating-card"],
      { y: 18, opacity: 0, stagger: 0.08, duration: 0.34 },
      "-=0.32"
    );

  if (!reduced) {
    const heroLayers = gsap.timeline({
      defaults: { ease: "none" },
      scrollTrigger: hasScrollTrigger
        ? {
            trigger: "#hero",
            start: "top top",
            end: "bottom top",
            scrub: 1,
          }
        : undefined,
    });

    heroLayers
      .to(".hero-backdrop", { yPercent: 10 }, 0)
      .to(".hero-orbits", { yPercent: 14, scale: 1.04 }, 0)
      .to(".hero-copy", { yPercent: -4 }, 0)
      .to(".hero-visual-window", { yPercent: 6 }, 0)
      .to(".scroll-indicator", { opacity: 0, y: 16 }, 0);

    window.addEventListener("mousemove", (event) => {
      const x = (event.clientX / window.innerWidth) - 0.5;
      const y = (event.clientY / window.innerHeight) - 0.5;
      gsap.to(".hero-backdrop", {
        x: x * 16,
        y: y * 12,
        duration: 0.8,
        overwrite: "auto",
        ease: "power2.out",
      });
      gsap.to(".hero-visual-window", {
        x: x * -10,
        y: y * -8,
        duration: 0.8,
        overwrite: "auto",
        ease: "power2.out",
      });
    });
  }

  gsap.utils.toArray(".reveal-up").forEach((el) => {
    gsap.fromTo(
      el,
      { y: 28, opacity: 0 },
      {
        y: 0,
        opacity: 1,
        duration: 0.72,
        ease: "power2.out",
        scrollTrigger: hasScrollTrigger
          ? { trigger: el, start: "top 84%", once: true }
          : undefined,
      }
    );
  });

  [
    ".workflow-grid",
    ".landing-feature-grid",
    ".platform-tour-tabs",
    ".analytics-spotlight__grid",
    ".comparison-grid",
    ".site-footer__nav",
  ].forEach((selector) => {
    const group = document.querySelector(selector);
    if (!group || !hasScrollTrigger) return;
    const items = group.children;
    if (!items.length) return;

    gsap.fromTo(
      items,
      { y: 18, opacity: 0 },
      {
        y: 0,
        opacity: 1,
        duration: 0.5,
        stagger: 0.08,
        ease: "power2.out",
        scrollTrigger: {
          trigger: group,
          start: "top 82%",
          once: true,
        },
      }
    );
  });
}

function initPlatformTour() {
  if (!isLandingPage) return;

  const root = byId("platform-overview");
  if (!root) return;

  const tabs = Array.from(root.querySelectorAll("[data-platform-tab]"));
  const panels = Array.from(root.querySelectorAll("[data-platform-panel]"));
  if (!tabs.length || !panels.length) return;

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let activeKey = tabs.find((tab) => tab.classList.contains("is-active"))?.dataset.platformTab || tabs[0].dataset.platformTab;
  let autoRotateId = null;
  let hasUserInteracted = false;

  const panelByKey = (key) => panels.find((panel) => panel.dataset.platformPanel === key);

  const syncTabState = (key) => {
    tabs.forEach((tab) => {
      const active = tab.dataset.platformTab === key;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.setAttribute("tabindex", active ? "0" : "-1");
    });
  };

  const syncPanelState = (key) => {
    panels.forEach((panel) => {
      const active = panel.dataset.platformPanel === key;
      panel.classList.toggle("is-active", active);
      panel.hidden = !active;
      panel.setAttribute("aria-hidden", active ? "false" : "true");
      panel.style.transform = "";
      panel.style.opacity = "";
    });
  };

  const stopAutoRotate = () => {
    if (!autoRotateId) return;
    window.clearInterval(autoRotateId);
    autoRotateId = null;
  };

  const showPanel = (key, options = {}) => {
    const { userInitiated = false } = options;
    const currentPanel = panelByKey(activeKey);
    const nextPanel = panelByKey(key);
    if (!nextPanel || key === activeKey) return;

    if (userInitiated) {
      hasUserInteracted = true;
      stopAutoRotate();
    }

    syncTabState(key);

    if (!hasGsap || reduced || !currentPanel) {
      syncPanelState(key);
      activeKey = key;
      return;
    }

    gsap.killTweensOf([currentPanel, nextPanel]);

    gsap.to(currentPanel, {
      opacity: 0,
      y: -16,
      scale: 0.985,
      duration: 0.2,
      ease: "power2.in",
      onComplete: () => {
        currentPanel.hidden = true;
        currentPanel.setAttribute("aria-hidden", "true");
        currentPanel.classList.remove("is-active");
        currentPanel.style.transform = "";

        nextPanel.hidden = false;
        nextPanel.setAttribute("aria-hidden", "false");
        nextPanel.classList.add("is-active");
        gsap.fromTo(
          nextPanel,
          { opacity: 0, y: 16, scale: 0.988 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.34,
            ease: "power2.out",
            clearProps: "transform,opacity",
          }
        );
      },
    });

    activeKey = key;
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => showPanel(tab.dataset.platformTab, { userInitiated: true }));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End", "Enter", " "].includes(event.key)) return;
      event.preventDefault();

      if (event.key === "Enter" || event.key === " ") {
        showPanel(tab.dataset.platformTab, { userInitiated: true });
        return;
      }

      let nextIndex = index;
      if (event.key === "ArrowDown" || event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
      if (event.key === "ArrowUp" || event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = tabs.length - 1;

      tabs[nextIndex]?.focus();
      showPanel(tabs[nextIndex].dataset.platformTab, { userInitiated: true });
    });
  });

  syncTabState(activeKey);
  syncPanelState(activeKey);

  if (reduced) return;

  const startAutoRotate = () => {
    if (hasUserInteracted || tabs.length < 2 || autoRotateId) return;
    autoRotateId = window.setInterval(() => {
      const currentIndex = tabs.findIndex((tab) => tab.dataset.platformTab === activeKey);
      const nextTab = tabs[(currentIndex + 1) % tabs.length];
      if (nextTab) showPanel(nextTab.dataset.platformTab);
    }, 5200);
  };

  root.addEventListener("mouseenter", stopAutoRotate);
  root.addEventListener("mouseleave", startAutoRotate);
  root.addEventListener("focusin", stopAutoRotate);
  root.addEventListener("focusout", () => {
    if (!root.contains(document.activeElement)) startAutoRotate();
  });

  startAutoRotate();
}

function initGsapMotion() {
  if (!hasGsap) return;
  if (!heroSection) return;
  if (isLandingPage) return;
  if (hasScrollTrigger) gsap.registerPlugin(ScrollTrigger);

  const intro = gsap.timeline({ defaults: { ease: "power3.out" } });
  intro
    .from(".brand", { y: -20, opacity: 0, duration: 0.55 })
    .from("#mainMenu a", { y: -16, opacity: 0, stagger: 0.05, duration: 0.35 }, "-=0.34")
    .from("#openLoginBtn", { y: -12, opacity: 0, duration: 0.35 }, "-=0.3")
    .from(".hero-copy .eyebrow", { y: 18, opacity: 0, duration: 0.38 }, "-=0.22")
    .from(".hero-copy .wordmark", { y: 18, opacity: 0, duration: 0.46 }, "-=0.18")
    .from(".hero-title", { y: 22, opacity: 0, duration: 0.58 }, "-=0.22")
    .from(".hero-subtitle", { y: 20, opacity: 0, duration: 0.52 }, "-=0.26")
    .from(".hero-cta .btn", { y: 10, opacity: 0, stagger: 0.08, duration: 0.35 }, "-=0.2")
    .from(".hero-link-row > *", { y: 10, opacity: 0, stagger: 0.06, duration: 0.28 }, "-=0.22")
    .from(".hero-stats", { x: 24, opacity: 0, duration: 0.58 }, "-=0.34");

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
    gsap.to(".hero-orbits", {
      yPercent: 10,
      ease: "none",
      scrollTrigger: {
        trigger: "#hero",
        start: "top top",
        end: "bottom top",
        scrub: 1,
      },
    });

    gsap.to(".scroll-indicator", {
      opacity: 0,
      y: 18,
      ease: "none",
      scrollTrigger: {
        trigger: "#hero",
        start: "top top",
        end: "bottom top",
        scrub: 1,
      },
    });
  }
}

function initTiltCards() {
  const cards = isLandingPage
    ? document.querySelectorAll(".platform-tour-panel")
    : document.querySelectorAll(".tilt-card:not(.robot-shot)");
  if (!cards.length) return;

  cards.forEach((card) => {
    card.addEventListener("mousemove", (e) => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const intensity = isLandingPage ? 4.2 : 7;
      const rx = ((y / rect.height) - 0.5) * -intensity;
      const ry = ((x / rect.width) - 0.5) * (intensity + (isLandingPage ? 1 : 2));
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
  if (isLandingPage) return;
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
        trigger: "#operations",
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
        trigger: "#decision-layer",
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
        trigger: "#operations",
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
  initWorkspacePasswordReset();
  initLegalToc();
  initLandingMotion();
  initPlatformTour();
  initRevealOnScroll();
  initContactPage();
  initMagneticButtons();
  initVisualParallax();
  initGsapMotion();
  initTiltCards();
  initParticles();
  initThreeScene();
}

window.addEventListener("DOMContentLoaded", init);
