(() => {
  const apiBase = (
    window.FISHINTIME_API_BASE_URL || window.location.origin
  ).replace(/\/+$/, "");
  const tokenStorageKey = "fishintime_access_token";
  const navigation = document.querySelector("[data-site-navigation]");
  if (!navigation) return;

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
      const statusResponse = await fetch(`${apiBase}/api/billing/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (statusResponse.ok) {
        const status = await statusResponse.json();
        activeSubscriber = status.active === true;
      } else if (statusResponse.status !== 401) {
        throw new Error(`Subscription check failed (${statusResponse.status}).`);
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

  renderNavigation();
  getAccount();
  window.addEventListener("fishintime:auth-changed", getAccount);
  window.addEventListener("storage", event => {
    if (event.key === tokenStorageKey) getAccount();
  });
})();
