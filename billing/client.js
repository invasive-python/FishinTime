(() => {
  const apiBase = (
    window.FISHINTIME_API_BASE_URL || window.location.origin
  ).replace(/\/+$/, "");
  const tokenStorageKey = "fishintime_access_token";
  const verifierStorageKey = "fishintime_pkce_verifier";
  const stateStorageKey = "fishintime_oauth_state";
  const message = document.getElementById("message");
  const plans = document.getElementById("plans");
  const planButtons = plans.querySelectorAll("button[data-plan]");
  const signInButton = document.getElementById("signInButton");
  const portalButton = document.getElementById("portalButton");

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
      scope: "openid email",
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
    window.location.assign(result.checkout_url);
  }

  async function openPortal() {
    message.textContent = "Opening billing management…";
    const result = await requestApi("/api/billing/portal", { method: "POST" });
    window.location.assign(result.portal_url);
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

      if (callback.searchParams.has("code")) {
        await exchangeAuthorizationCode(
          callback.searchParams.get("code"),
          callback.searchParams.get("state")
        );
      }

      const planData = await requestApi("/api/billing/plans");
      document.getElementById("monthlyPrice").textContent =
        formatPrice(planData.monthly.amount_cents, planData.monthly.interval);
      document.getElementById("annualPrice").textContent =
        formatPrice(planData.annual.amount_cents, planData.annual.interval);

      const token = sessionStorage.getItem(tokenStorageKey);
      if (!token) {
        message.textContent = "Choose a plan to sign in and subscribe.";
        signInButton.hidden = false;
        return;
      }

      const status = await requestApi("/api/billing/status");
      signInButton.hidden = false;
      signInButton.textContent = "Sign out";
      if (status.active) {
        message.textContent = "Your AI recommendation subscription is active.";
        portalButton.hidden = false;
        planButtons.forEach(button => { button.hidden = true; });
      } else {
        message.textContent = "Choose a plan to unlock AI fishing recommendations.";
      }
    } catch (error) {
      message.textContent = error.message;
      signInButton.hidden = false;
      signInButton.textContent = "Sign in";
    }
  }

  signInButton.addEventListener("click", async () => {
    if (sessionStorage.getItem(tokenStorageKey)) {
      sessionStorage.removeItem(tokenStorageKey);
      window.location.reload();
      return;
    }
    try {
      await beginSignIn();
    } catch (error) {
      message.textContent = error.message;
    }
  });

  plans.addEventListener("click", async event => {
    const button = event.target.closest("button[data-plan]");
    if (!button) return;
    button.disabled = true;
    try {
      if (!sessionStorage.getItem(tokenStorageKey)) {
        message.textContent = "Sign in, then choose your plan to continue.";
        await beginSignIn();
        return;
      }
      await createCheckout(button.dataset.plan);
    } catch (error) {
      message.textContent = error.message;
      button.disabled = false;
    }
  });

  portalButton.addEventListener("click", async () => {
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
