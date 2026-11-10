(() => {
  const apiBase = (
    window.FISHINTIME_API_BASE_URL || window.location.origin
  ).replace(/\/+$/, "");
  const tokenStorageKey = "fishintime_access_token";
  const verifierStorageKey = "fishintime_pkce_verifier";
  const stateStorageKey = "fishintime_oauth_state";
  const pendingPlanStorageKey = "fishintime_pending_plan";
  const oauthStateRetryStorageKey = "fishintime_oauth_state_retry";
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
  planButtons.forEach(button => { button.disabled = true; });

  function getAccessToken() {
    const token = localStorage.getItem(tokenStorageKey);
    if (token) return token;

    const legacyToken = sessionStorage.getItem(tokenStorageKey);
    if (legacyToken) {
      localStorage.setItem(tokenStorageKey, legacyToken);
      sessionStorage.removeItem(tokenStorageKey);
    }
    return legacyToken;
  }

  function clearAccessToken() {
    localStorage.removeItem(tokenStorageKey);
    sessionStorage.removeItem(tokenStorageKey);
  }

  function getOAuthValue(key) {
    const value = sessionStorage.getItem(key);
    if (value) return value;

    const legacyValue = localStorage.getItem(key);
    if (legacyValue) {
      sessionStorage.setItem(key, legacyValue);
      localStorage.removeItem(key);
    }
    return legacyValue;
  }

  function clearOAuthValues() {
    for (const key of [stateStorageKey, verifierStorageKey]) {
      localStorage.removeItem(key);
      sessionStorage.removeItem(key);
    }
  }

  function getCanonicalUrl(url) {
    const canonicalUrl = new URL(config.redirect_uri);
    canonicalUrl.pathname = url.pathname;
    canonicalUrl.search = url.search;
    canonicalUrl.hash = url.hash;
    return canonicalUrl;
  }

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
    const expectedState = getOAuthValue(stateStorageKey);
    const verifier = getOAuthValue(verifierStorageKey);
    if (!expectedState || returnedState !== expectedState || !verifier) {
      const error = new Error(
        "The sign-in response could not be verified. Start sign-in from the configured site address and try again."
      );
      error.code = "OAUTH_STATE_INVALID";
      throw error;
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

    localStorage.setItem(tokenStorageKey, result.access_token);
    clearOAuthValues();
    sessionStorage.removeItem(oauthStateRetryStorageKey);
    history.replaceState(null, "", window.location.pathname);
    window.dispatchEvent(new CustomEvent("fishintime:auth-changed"));
    const pendingPlan = sessionStorage.getItem(pendingPlanStorageKey);
    if (pendingPlan !== "monthly" && pendingPlan !== "annual") {
      window.location.replace(new URL("/", config.redirect_uri));
      return true;
    }
    return false;
  }

  async function beginSignIn() {
    const callbackOrigin = new URL(config.redirect_uri).origin;
    if (window.location.origin !== callbackOrigin) {
      const canonicalUrl = getCanonicalUrl(new URL(window.location.href));
      canonicalUrl.searchParams.set("signin", "1");
      window.location.replace(canonicalUrl);
      return;
    }

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
    const token = getAccessToken();
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
    clearAccessToken();
    sessionStorage.removeItem(pendingPlanStorageKey);
    window.dispatchEvent(new CustomEvent("fishintime:auth-changed"));
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

    const token = getAccessToken();
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
      const callbackOrigin = new URL(config.redirect_uri).origin;
      if (window.location.origin !== callbackOrigin) {
        window.location.replace(getCanonicalUrl(callback));
        return;
      }

      if (callback.searchParams.has("error")) {
        throw new Error(
          callback.searchParams.get("error_description") || "Sign-in was canceled."
        );
      }

      if (callback.searchParams.get("signin") === "1") {
        callback.searchParams.delete("signin");
        history.replaceState(null, "", callback);
        await beginSignIn();
        return;
      }

      const receivedCode = callback.searchParams.has("code");
      if (receivedCode) {
        try {
          const redirected = await exchangeAuthorizationCode(
            callback.searchParams.get("code"),
            callback.searchParams.get("state")
          );
          if (redirected) return;
        } catch (error) {
          const existingToken = getAccessToken();
          if (existingToken) {
            let tokenIsValid = false;
            try {
              await requestApi("/api/billing/account");
              tokenIsValid = true;
            } catch {
              clearAccessToken();
            }
            if (tokenIsValid) {
              clearOAuthValues();
              history.replaceState(null, "", callback.pathname);
              const pendingPlan = sessionStorage.getItem(pendingPlanStorageKey);
              if (pendingPlan === "monthly" || pendingPlan === "annual") {
                await createCheckout(pendingPlan);
                return;
              }
              window.location.replace("/");
              return;
            }
          }
          if (
            error.code === "OAUTH_STATE_INVALID" &&
            sessionStorage.getItem(oauthStateRetryStorageKey) !== "1"
          ) {
            sessionStorage.setItem(oauthStateRetryStorageKey, "1");
            clearOAuthValues();
            history.replaceState(null, "", callback.pathname);
            await beginSignIn();
            return;
          }
          throw error;
        }
      }

      const pendingPlan = sessionStorage.getItem(pendingPlanStorageKey);
      if (
        receivedCode &&
        (pendingPlan === "monthly" || pendingPlan === "annual")
      ) {
        await createCheckout(pendingPlan);
        return;
      }
      if (receivedCode) {
        window.location.replace("/");
        return;
      }

      if (plans) {
        planButtons.forEach(button => { button.disabled = false; });
        await initializePlans();
      } else if (accountDetails) {
        if (getAccessToken()) {
          await loadAccount();
          const currentUrl = new URL(window.location.href);
          if (currentUrl.searchParams.get("manage") !== "1") {
            window.location.replace("/");
            return;
          }
          message.textContent = "You are signed in.";
        } else {
          accountDetails.hidden = true;
          signInButton.hidden = false;
          signInButton.textContent = "Sign in or create account";
          message.textContent = "Sign in or create an account to manage your subscription.";
        }
      }
    } catch (error) {
      const callback = new URL(window.location.href);
      if (
        callback.searchParams.has("code") ||
        callback.searchParams.has("state") ||
        callback.searchParams.has("error")
      ) {
        history.replaceState(null, "", callback.pathname);
        clearOAuthValues();
        sessionStorage.removeItem(oauthStateRetryStorageKey);
      }
      message.textContent = error.message;
      if (signInButton) {
        signInButton.hidden = false;
        signInButton.textContent = getAccessToken()
          ? "Sign out"
          : "Sign in or create account";
      }
    }
  }

  signInButton?.addEventListener("click", async () => {
    try {
      if (getAccessToken()) {
        await signOut();
      } else {
        await beginSignIn();
      }
    } catch (error) {
      message.textContent = error.message;
    }
  });

  window.addEventListener("fishintime:auth-state-changed", event => {
    if (!accountDetails || !event.detail?.account) return;
    if (new URL(window.location.href).searchParams.get("manage") !== "1") {
      window.location.replace("/");
      return;
    }
    signInButton.hidden = false;
    signInButton.textContent = "Sign out";
    accountDetails.hidden = false;
    message.textContent = "You are signed in.";
  });

  plans?.addEventListener("click", async event => {
    const button = event.target.closest("button[data-plan]");
    if (!button) return;
    button.disabled = true;
    try {
      const token = getAccessToken();
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
