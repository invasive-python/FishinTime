(() => {
  const apiBase = (
    window.FISHINTIME_API_BASE_URL || window.location.origin
  ).replace(/\/+$/, "");
  const tokenStorageKey = "fishintime_access_token";
  const verifierStorageKey = "fishintime_pkce_verifier";
  const stateStorageKey = "fishintime_oauth_state";
  const pendingPlanStorageKey = "fishintime_pending_plan";
  const message = document.getElementById("message");
  const plans = document.getElementById("plans");
  const planButtons = plans?.querySelectorAll("button[data-plan]") || [];
  const signInButton = document.getElementById("signInButton");
  const portalButton = document.getElementById("portalButton");
  const accountDetails = document.getElementById("accountDetails");
  const emailForm = document.getElementById("emailForm");
  const emailConfirmForm = document.getElementById("emailConfirmForm");
  const passwordForm = document.getElementById("passwordForm");
  const accountEmail = document.getElementById("accountEmail");
  const subscriptionStatus = document.getElementById("subscriptionStatus");

  let config;

  function base64UrlEncode(bytes) {
    let binary = "";
    bytes.forEach(byte => { binary += String.fromCharCode(byte); });
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function randomUrlSafeString() {
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    return base64UrlEncode(bytes);
  }

  async function exchangeAuthorizationCode(code, returnedState) {
    const expectedState = sessionStorage.getItem(stateStorageKey);
    const verifier = sessionStorage.getItem(verifierStorageKey);
    if (!expectedState || returnedState !== expectedState || !verifier) {
      throw new Error("The sign-in response could not be verified. Please sign in again.");
    }

    const body = new URLSearchParams({
      grant_type: "authorization_code",
      client_id: config.client_id,
      redirect_uri: config.redirect_uri,
      code,
      code_verifier: verifier,
    });
    const response = await fetch(`${config.login_domain}/oauth2/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    const result = await response.json();
    if (!response.ok || !result.access_token) {
      throw new Error(result.error_description || "Unable to complete sign-in.");
    }

    sessionStorage.setItem(tokenStorageKey, result.access_token);
    sessionStorage.removeItem(stateStorageKey);
    sessionStorage.removeItem(verifierStorageKey);
    history.replaceState(null, "", window.location.pathname);
  }

  async function beginSignIn() {
    const verifier = randomUrlSafeString();
    const state = randomUrlSafeString();
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(verifier)
    );
    const challenge = base64UrlEncode(new Uint8Array(digest));
    sessionStorage.setItem(verifierStorageKey, verifier);
    sessionStorage.setItem(stateStorageKey, state);

    const authorization = new URL(`${config.login_domain}/oauth2/authorize`);
    authorization.search = new URLSearchParams({
      response_type: "code",
      client_id: config.client_id,
      redirect_uri: config.redirect_uri,
      scope: "openid email profile aws.cognito.signin.user.admin",
      state,
      code_challenge: challenge,
      code_challenge_method: "S256",
    });
    window.location.assign(authorization);
  }

  async function requestApi(path, options = {}) {
    const token = sessionStorage.getItem(tokenStorageKey);
    const headers = new Headers(options.headers || {});
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(`${apiBase}${path}`, {
      ...options,
      headers,
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || `Request failed (${response.status}).`);
    }
    return result;
  }

  function formatPrice(cents, interval) {
    const amount = new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: "USD",
    }).format(cents / 100);
    return `${amount} / ${interval}`;
  }

  async function createCheckout(plan) {
    message.textContent = "Opening secure checkout…";
    const result = await requestApi("/api/billing/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan }),
    });
    sessionStorage.removeItem(pendingPlanStorageKey);
    window.location.assign(result.checkout_url);
  }

  async function openPortal() {
    message.textContent = "Opening subscription management…";
    const result = await requestApi("/api/billing/portal", { method: "POST" });
    window.location.assign(result.portal_url);
  }

  async function signOut() {
    sessionStorage.removeItem(tokenStorageKey);
    sessionStorage.removeItem(pendingPlanStorageKey);
    const logout = new URL(`${config.login_domain}/logout`);
    logout.search = new URLSearchParams({
      client_id: config.client_id,
      logout_uri: config.logout_uri,
    });
    window.location.assign(logout);
  }

  async function loadAccount() {
    signInButton.hidden = false;
    signInButton.textContent = "Sign out";
    accountDetails.hidden = false;

    const account = await requestApi("/api/billing/account");
    accountEmail.textContent = account.email
      ? `${account.email}${account.email_verified ? " (verified)" : " (verification required)"}`
      : "No email address is associated with this account.";

    try {
      const status = await requestApi("/api/billing/status");
      subscriptionStatus.textContent = status.active
        ? `Active ${status.plan || ""} subscription`.trim()
        : status.status === "inactive"
          ? "No active subscription."
          : `Subscription status: ${status.status}.`;
      portalButton.hidden = status.status === "inactive";
    } catch (error) {
      subscriptionStatus.textContent = error.message;
      portalButton.hidden = true;
    }
  }

  async function initializePlans() {
    const planData = await requestApi("/api/billing/plans");
    document.getElementById("monthlyPrice").textContent =
      formatPrice(planData.monthly.amount_cents, planData.monthly.interval);
    document.getElementById("annualPrice").textContent =
      formatPrice(planData.annual.amount_cents, planData.annual.interval);

    const token = sessionStorage.getItem(tokenStorageKey);
    if (token) {
      const status = await requestApi("/api/billing/status");
      if (status.active) {
        message.textContent = "Your subscription is active. Manage it from your account.";
        planButtons.forEach(button => { button.hidden = true; });
        return;
      }
    }
    message.textContent = "Choose a plan to subscribe.";
  }

  async function initialize() {
    try {
      const callback = new URL(window.location.href);
      config = await requestApi("/api/billing/config");
      if (callback.searchParams.has("error")) {
        throw new Error(
          callback.searchParams.get("error_description") || "Sign-in was canceled."
        );
      }

      const receivedCode = callback.searchParams.has("code");
      if (receivedCode) {
        await exchangeAuthorizationCode(
          callback.searchParams.get("code"),
          callback.searchParams.get("state")
        );
      }

      const pendingPlan = sessionStorage.getItem(pendingPlanStorageKey);
      if (
        receivedCode &&
        (pendingPlan === "monthly" || pendingPlan === "annual")
      ) {
        await createCheckout(pendingPlan);
        return;
      }

      if (plans) {
        await initializePlans();
      } else if (accountDetails) {
        if (sessionStorage.getItem(tokenStorageKey)) {
          await loadAccount();
          message.textContent = "You are signed in.";
        } else {
          accountDetails.hidden = true;
          signInButton.hidden = false;
          signInButton.textContent = "Sign in or create account";
          message.textContent = "Sign in or create an account to manage your subscription.";
        }
      }
    } catch (error) {
      message.textContent = error.message;
      if (signInButton) {
        signInButton.hidden = false;
        signInButton.textContent = sessionStorage.getItem(tokenStorageKey)
          ? "Sign out"
          : "Sign in or create account";
      }
    }
  }

  signInButton?.addEventListener("click", async () => {
    try {
      if (sessionStorage.getItem(tokenStorageKey)) {
        await signOut();
      } else {
        await beginSignIn();
      }
    } catch (error) {
      message.textContent = error.message;
    }
  });

  plans?.addEventListener("click", async event => {
    const button = event.target.closest("button[data-plan]");
    if (!button) return;
    button.disabled = true;
    try {
      const token = sessionStorage.getItem(tokenStorageKey);
      if (!token) {
        sessionStorage.setItem(pendingPlanStorageKey, button.dataset.plan);
        message.textContent = "Sign in or create an account to continue to checkout.";
        await beginSignIn();
        return;
      }
      await createCheckout(button.dataset.plan);
    } catch (error) {
      message.textContent = error.message;
      button.disabled = false;
    }
  });

  emailForm?.addEventListener("submit", async event => {
    event.preventDefault();
    const email = new FormData(emailForm).get("email");
    const button = emailForm.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const result = await requestApi("/api/billing/account/email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      message.textContent = result.message;
      emailConfirmForm.hidden = false;
    } catch (error) {
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

  emailConfirmForm?.addEventListener("submit", async event => {
    event.preventDefault();
    const code = new FormData(emailConfirmForm).get("code");
    const button = emailConfirmForm.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const result = await requestApi("/api/billing/account/email/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      message.textContent = result.message;
      emailConfirmForm.hidden = true;
      await loadAccount();
    } catch (error) {
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

  passwordForm?.addEventListener("submit", async event => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(passwordForm));
    const button = passwordForm.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const result = await requestApi("/api/billing/account/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      message.textContent = result.message;
      passwordForm.reset();
    } catch (error) {
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

  portalButton?.addEventListener("click", async () => {
    portalButton.disabled = true;
    try {
      await openPortal();
    } catch (error) {
      message.textContent = error.message;
      portalButton.disabled = false;
    }
  });

  initialize();
})();
