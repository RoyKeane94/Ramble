(async function mountEmbeddedCheckout() {
  var configEl = document.getElementById("signup-checkout-config");
  var mountEl = document.getElementById("checkout-form");
  var errorEl = document.getElementById("checkout-error");
  if (!configEl || !mountEl) return;

  function showError(message) {
    if (!errorEl) return;
    errorEl.hidden = false;
    errorEl.textContent = message || "Could not load checkout. Please try again.";
  }

  if (typeof Stripe === "undefined") {
    showError("Could not load Stripe. Please refresh and try again.");
    return;
  }

  try {
    var config = JSON.parse(configEl.textContent);
    var stripe = Stripe(config.publishable_key);
    var fontUrl =
      window.location.origin + "/static/fonts/SuperSans-VF-Upright.woff2";
    var appearance = {
      theme: "stripe",
      inputs: "spaced",
      labels: "auto",
      variables: {
        borderRadius: "12px",
        colorBackground: "#ffffff",
        colorDanger: "#df1b41",
        colorPrimary: "#051A9C",
        colorSuccess: "#00c853",
        colorText: "#0B1B4A",
        fontFamily:
          '"Super Sans VF", Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        fontSizeBase: "16px",
        spacingUnit: "4px"
      }
    };
    var checkout = stripe.initCheckoutFormSdk({
      clientSecret: config.client_secret,
      appearance: appearance,
      fonts: [
        {
          family: "Super Sans VF",
          src: "url(" + fontUrl + ")",
          weight: "100 900",
          style: "normal",
          display: "swap"
        },
        {
          cssSrc:
            "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
        }
      ]
    });
    var checkoutForm = checkout.createForm({ layout: "expanded" });
    checkoutForm.mount("#checkout-form");

    var loadActionsResult = await checkout.loadActions();
    if (loadActionsResult.type === "success") {
      checkoutForm.on("confirm", function (event) {
        loadActionsResult.actions.confirm({ formConfirmEvent: event });
      });
    } else {
      showError(loadActionsResult.error && loadActionsResult.error.message);
    }
  } catch (err) {
    showError(err && err.message ? err.message : "Could not load checkout.");
  }
})();
