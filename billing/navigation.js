(() => {
  const apiBase = (
    window.FISHINTIME_API_BASE_URL || window.location.origin
  ).replace(/\/+$/, "");
  const tokenStorageKey = "fishintime_access_token";
  const navigation = document.querySelector("[data-site-navigation]");

  const links = [
    { href: "/", label: "Forecast", paths: ["/"] },
    {
      href: "/billing/subscribe",
      label: "Subscription plans",
      paths: ["/billing/subscribe", "/billing/success", "/billing/cancel"],
    },
    {
      href: "/billing/account?manage=1",
      label: "Account",
      paths: ["/billing/account"],
    },
  ];

  function renderNavigation(account = null) {
    navigation.replaceChildren();

    const list = document.createElement("ul");
    for (const item of links) {
      const listItem = document.createElement("li");
      if (item.paths.includes(window.location.pathname)) {
        const currentPage = document.createElement("span");
        currentPage.className = "site-navigation-current";
        currentPage.textContent = item.label;
        currentPage.setAttribute("aria-current", "page");
        currentPage.setAttribute("aria-disabled", "true");
        listItem.append(currentPage);
      } else {
        const link = document.createElement("a");
        link.href = item.href;
        link.textContent = item.label;
        listItem.append(link);
      }
      list.append(listItem);
    }
    navigation.append(list);

    document.querySelectorAll("[data-account-welcome]").forEach(welcome => {
      if (account) {
        welcome.replaceChildren(
          document.createElement("br"),
          document.createTextNode(
            `Welcome ${account.username || account.email || "angler"}`
          )
        );
        welcome.hidden = false;
      } else {
        welcome.replaceChildren();
        welcome.hidden = true;
      }
    });
    document.querySelectorAll("[data-signed-out-only]").forEach(element => {
      element.hidden = Boolean(account);
    });
  }

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

  async function getAccount() {
    const token = getAccessToken();
    if (!token) {
      renderNavigation();
      window.dispatchEvent(
        new CustomEvent("fishintime:auth-state-changed", {
          detail: { account: null, activeSubscriber: false },
        })
      );
      return;
    }

    try {
      const response = await fetch(`${apiBase}/api/billing/account`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.status === 401) {
        localStorage.removeItem(tokenStorageKey);
        sessionStorage.removeItem(tokenStorageKey);
        renderNavigation();
        window.dispatchEvent(
          new CustomEvent("fishintime:auth-state-changed", {
            detail: { account: null, activeSubscriber: false },
          })
        );
        return;
      }
      if (!response.ok) {
        throw new Error(`Account check failed (${response.status}).`);
      }

      const account = await response.json();
      let activeSubscriber = false;
      try {
        const statusResponse = await fetch(`${apiBase}/api/billing/status`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (statusResponse.ok) {
          const status = await statusResponse.json();
          activeSubscriber = status.active === true;
        } else if (statusResponse.status !== 401) {
          throw new Error(
            `Subscription check failed (${statusResponse.status}).`,
          );
        }
      } catch (error) {
        console.error("Unable to check subscription status:", error);
      }

      renderNavigation(account);
      window.dispatchEvent(
        new CustomEvent("fishintime:auth-state-changed", {
          detail: { account, activeSubscriber },
        })
      );
    } catch (error) {
      console.error("Unable to check the signed-in account:", error);
      renderNavigation();
      window.dispatchEvent(
        new CustomEvent("fishintime:auth-state-changed", {
          detail: { account: null, activeSubscriber: false },
        })
      );
    }
  }

  if (navigation) {
    renderNavigation();
    getAccount();
    window.addEventListener("fishintime:auth-changed", getAccount);
    window.addEventListener("storage", event => {
      if (event.key === tokenStorageKey) getAccount();
    });
  }

  document.addEventListener("click", async event => {
    const link = event.target.closest("[data-direct-signin]");
    if (!link) return;
    event.preventDefault();
    try {
      const configResponse = await fetch(`${apiBase}/api/billing/config`);
      const config = await configResponse.json();
      if (!configResponse.ok) {
        throw new Error(config.detail || "Sign-in is unavailable.");
      }

      const callbackOrigin = new URL(config.redirect_uri).origin;
      if (window.location.origin !== callbackOrigin) {
        const canonicalCallback = new URL(config.redirect_uri);
        canonicalCallback.searchParams.set("signin", "1");
        window.location.assign(canonicalCallback);
        return;
      }

      const encode = bytes => {
        let binary = "";
        bytes.forEach(byte => { binary += String.fromCharCode(byte); });
        return btoa(binary)
          .replace(/\+/g, "-")
          .replace(/\//g, "_")
          .replace(/=+$/, "");
      };
      const verifierBytes = new Uint8Array(32);
      const stateBytes = new Uint8Array(32);
      crypto.getRandomValues(verifierBytes);
      crypto.getRandomValues(stateBytes);
      const verifier = encode(verifierBytes);
      const state = encode(stateBytes);
      const digest = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(verifier)
      );

      sessionStorage.setItem("fishintime_pkce_verifier", verifier);
      sessionStorage.setItem("fishintime_oauth_state", state);
      const authorization = new URL(
        `${config.login_domain}/oauth2/authorize`
      );
      authorization.search = new URLSearchParams({
        response_type: "code",
        client_id: config.client_id,
        redirect_uri: config.redirect_uri,
        scope: "openid email profile aws.cognito.signin.user.admin",
        state,
        code_challenge: encode(new Uint8Array(digest)),
        code_challenge_method: "S256",
      });
      window.location.assign(authorization);
    } catch (error) {
      console.error("Unable to start sign-in directly:", error);
      const status = document.createElement("p");
      status.className = "billing-message";
      status.setAttribute("role", "alert");
      status.textContent = error.message;
      link.insertAdjacentElement("afterend", status);
    }
  });
})();
