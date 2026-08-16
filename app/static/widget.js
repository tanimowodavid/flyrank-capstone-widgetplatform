/**
 * FlyRank Widget Embed Script
 *
 * Vanilla JavaScript, no dependencies, runs on any page.
 *
 * Usage: <script src="http://localhost:8000/api/v1/widget.js?id=WIDGET_ID"></script>
 */

(function () {
  "use strict";

  // 1. CAPTURE SCRIPT TAG IMMEDIATELY AT EVALUATION TIME
  // (Must happen synchronously before any async functions or DOMContentLoaded listeners)
  var currentScript = document.currentScript;

  if (!currentScript) {
    // Fallback if currentScript is unsupported: query the last script tag on page
    var scripts = document.getElementsByTagName("script");
    currentScript = scripts[scripts.length - 1];
  }

  /**
   * Get this script's widget ID from the src query parameter.
   */
  function getWidgetIdFromScript(script) {
    if (!script || !script.src) {
      console.warn("[FlyRank Widget] Unable to locate script tag");
      return null;
    }

    try {
      var url = new URL(script.src);
      return url.searchParams.get("id");
    } catch (e) {
      // Fallback regex if URL parsing fails
      var match = script.src.match(/[?&]id=([^&]+)/);
      return match ? match[1] : null;
    }
  }

  /**
   * Get the base API URL directly from the script tag's origin (e.g., http://localhost:8000).
   */
  function getBaseUrl(script) {
    if (script && script.src) {
      try {
        var url = new URL(script.src);
        return url.origin; // Returns "http://localhost:8000"
      } catch (e) {
        // Fallback
      }
    }
    return "http://localhost:8000";
  }

  /**
   * Validate a CSS color value.
   */
  function isValidCssColor(color) {
    if (!color || typeof color !== "string") return false;
    var div = document.createElement("div");
    div.style.color = color;
    return div.style.color !== "";
  }

  function getValidColor(color) {
    return isValidCssColor(color) ? color : "#55b6e6";
  }

  /**
   * Fetch widget config from the public endpoint.
   */
  async function fetchWidgetConfig(widgetId, baseUrl) {
    try {
      var response = await fetch(
        baseUrl + "/api/v1/widgets/" + widgetId + "/config",
        {
          method: "GET",
          credentials: "omit",
          mode: "cors",
        },
      );

      if (!response.ok) {
        console.warn(
          "[FlyRank Widget] Failed to fetch config: " + response.status,
        );
        return null;
      }

      return await response.json();
    } catch (error) {
      console.warn("[FlyRank Widget] Error fetching config: " + error.message);
      return null;
    }
  }

  /**
   * Move a field out of sight without removing it from the form.
   *
   * Off-screen rather than display:none or type=hidden, because bots routinely
   * skip fields hidden those two ways, and a trap a bot skips catches nothing.
   * Positioned off-screen it looks like an ordinary input to anything reading
   * the DOM, while a sighted visitor never sees it.
   *
   * The input keeps its name and stays inside the form, so FormData collects it
   * exactly like every other field.
   */
  function hideFromView(container, input) {
    container.style.position = "absolute";
    container.style.left = "-9999px";
    // Absolute positioning takes the container out of flow, so its spacing would
    // otherwise be dead margin in the middle of the visible form.
    container.style.marginBottom = "0";

    // aria-hidden and tabindex go together. Hiding a focusable element from
    // assistive tech alone would strand a keyboard user on a field they cannot
    // see and screen readers will not announce.
    container.setAttribute("aria-hidden", "true");
    input.tabIndex = -1;

    // Autofill is the one way a real visitor could ever fill this in: a browser
    // matching on the "Confirm your email" label would get them flagged as a bot.
    input.setAttribute("autocomplete", "off");
  }

  /**
   * Create a form input based on field_type.
   */
  function createFormInput(field) {
    var container = document.createElement("div");
    container.style.marginBottom = "16px";

    var label = document.createElement("label");
    label.style.display = "block";
    label.style.marginBottom = "6px";
    label.style.fontWeight = "bold";
    label.style.fontSize = "14px";
    label.textContent = field.label;

    var input;
    if (field.field_type === "textarea") {
      input = document.createElement("textarea");
      input.style.height = "100px";
    } else if (field.field_type === "email") {
      input = document.createElement("input");
      input.type = "email";
    } else if (field.field_type === "number") {
      input = document.createElement("input");
      input.type = "number";
    } else {
      input = document.createElement("input");
      input.type = "text";
    }

    input.name = field.field_name;
    input.placeholder = field.placeholder || "";
    input.required = field.is_required || false;
    input.style.width = "100%";
    input.style.padding = "10px";
    input.style.border = "1px solid #ccc";
    input.style.borderRadius = "4px";
    input.style.fontSize = "14px";
    input.style.boxSizing = "border-box";

    container.appendChild(label);
    container.appendChild(input);

    // Built identically to every other field first, then hidden. Whether the
    // server flagged it is the only thing this script knows or cares about; it
    // never reads the value back, and the spam decision is the server's alone.
    if (field.is_honeypot) {
      hideFromView(container, input);
    }

    return container;
  }

  /**
   * Render the widget form into a container.
   */
  function renderForm(container, config, widgetId, baseUrl) {
    container.innerHTML = "";

    if (config.title) {
      var title = document.createElement("h3");
      title.textContent = config.title;
      title.style.margin = "0 0 12px 0";
      title.style.fontSize = "18px";
      title.style.fontWeight = "bold";
      container.appendChild(title);
    }

    if (config.description) {
      var desc = document.createElement("p");
      desc.textContent = config.description;
      desc.style.margin = "0 0 16px 0";
      desc.style.fontSize = "14px";
      desc.style.color = "#666";
      container.appendChild(desc);
    }

    var form = document.createElement("form");
    form.style.display = "flex";
    form.style.flexDirection = "column";

    if (config.form_fields && Array.isArray(config.form_fields)) {
      config.form_fields.forEach(function (field) {
        form.appendChild(createFormInput(field));
      });
    }

    var buttonColor = getValidColor(config.theme_color);
    var button = document.createElement("button");
    button.type = "submit";
    button.textContent = config.button_text || "Submit";
    button.style.marginTop = "16px";
    button.style.padding = "12px 24px";
    button.style.backgroundColor = buttonColor;
    button.style.color = "white";
    button.style.border = "none";
    button.style.borderRadius = "4px";
    button.style.fontSize = "16px";
    button.style.fontWeight = "bold";
    button.style.cursor = "pointer";

    form.appendChild(button);

    form.onsubmit = function (e) {
      e.preventDefault();
      submitForm(form, widgetId, baseUrl);
    };

    container.appendChild(form);
  }

  /**
   * Post submission payload to backend.
   */
  function submitForm(form, widgetId, baseUrl) {
    var formData = new FormData(form);
    var fieldValues = {};

    formData.forEach(function (value, key) {
      fieldValues[key] = value;
    });

    var payload = {
      field_values: fieldValues,
      referrer: typeof document !== "undefined" ? document.referrer : null,
      user_agent: navigator.userAgent,
    };

    fetch(baseUrl + "/api/v1/widgets/" + widgetId + "/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      credentials: "omit",
      mode: "cors",
    })
      .then(function (response) {
        if (!response.ok) {
          console.warn(
            "[FlyRank Widget] Submission failed with status " + response.status,
          );
          return;
        }
        return response.json();
      })
      .then(function (data) {
        if (data) {
          form.reset();
          var successMsg = document.createElement("div");
          successMsg.textContent =
            data.message || "Thank you for your submission";
          successMsg.style.color = "green";
          successMsg.style.marginTop = "10px";
          successMsg.style.fontSize = "14px";
          form.parentNode.insertBefore(successMsg, form.nextSibling);
          setTimeout(function () {
            successMsg.remove();
          }, 3000);
        }
      })
      .catch(function (error) {
        console.warn("[FlyRank Widget] Submission error: " + error.message);
      });
  }

  /**
   * Main initialization.
   */
  async function init() {
    var targetScript = currentScript;
    var widgetId = getWidgetIdFromScript(targetScript);

    if (!widgetId) {
      console.error("[FlyRank Widget] Cannot initialize without widget ID");
      return;
    }

    var baseUrl = getBaseUrl(targetScript);
    var config = await fetchWidgetConfig(widgetId, baseUrl);

    if (!config) {
      console.error("[FlyRank Widget] Failed to load widget config");
      return;
    }

    var container = document.createElement("div");
    container.id = "flyrank-widget-" + widgetId;
    container.style.fontFamily = "sans-serif";
    container.style.maxWidth = "500px";
    container.style.margin = "20px 0";
    container.style.padding = "20px";
    container.style.border = "1px solid #eee";
    container.style.borderRadius = "6px";
    container.style.backgroundColor = "#fafafa";
    container.style.boxSizing = "border-box";

    // Safely insert container after script tag
    if (targetScript && targetScript.parentNode) {
      targetScript.parentNode.insertBefore(container, targetScript.nextSibling);
    } else {
      document.body.appendChild(container);
    }

    renderForm(container, config, widgetId, baseUrl);
  }

  // Run initialization
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
