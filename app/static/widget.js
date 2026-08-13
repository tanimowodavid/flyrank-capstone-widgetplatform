/**
 * FlyRank Widget Embed Script
 *
 * Vanilla JavaScript, no dependencies, runs on any page.
 *
 * Usage: <script src="http://localhost:8000/widget.js?id=WIDGET_ID"></script>
 *
 * This script:
 * 1. Extracts its own widget ID from the query parameter
 * 2. Fetches the widget config from the public endpoint
 * 3. Renders a form at the location of this script tag
 * 4. Posts submissions to the backend
 */

(function () {
  "use strict";

  /**
   * Get this script's widget ID from the src query parameter.
   * Returns null if not found or if document.currentScript is unavailable.
   */
  function getWidgetIdFromScript() {
    var script = document.currentScript;
    if (!script) {
      console.warn(
        "[FlyRank Widget] Unable to locate script tag (document.currentScript not available)",
      );
      return null;
    }

    var src = script.src;
    var match = src.match(/[?&]id=([^&]+)/);
    if (!match) {
      console.warn("[FlyRank Widget] No widget ID in script src");
      return null;
    }

    return match[1];
  }

  /**
   * Validate a CSS color value. Returns true if valid, false otherwise.
   * Handles hex colors, named colors, rgb/rgba, etc.
   */
  function isValidCssColor(color) {
    if (!color || typeof color !== "string") return false;

    // Create a temporary element to test the color
    var div = document.createElement("div");
    div.style.color = color;

    // If the color was set, it will be a valid CSS color
    // (except for '' and 'inherit', etc. which we filter separately)
    return div.style.color !== "";
  }

  /**
   * Get a valid CSS color, defaulting to skyblue if the provided color is invalid.
   */
  function getValidColor(color) {
    return isValidCssColor(color) ? color : "skyblue";
  }

  /**
   * Fetch widget config from the public endpoint.
   * Returns the config object on success, null on failure (silently).
   */
  async function fetchWidgetConfig(widgetId, baseUrl) {
    try {
      var response = await fetch(
        baseUrl + "/api/v1/widgets/" + widgetId + "/config",
        {
          method: "GET",
          credentials: "omit", // Don't send cookies (public endpoint)
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
   * Get the base URL for API calls (protocol + host, no trailing slash).
   * If needed, could be configured via data attribute or global variable.
   */
  function getBaseUrl() {
    // For now, use the current page's protocol and host
    return window.location.protocol + "//" + window.location.host;
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
      input.style.height = "120px";
    } else if (field.field_type === "email") {
      input = document.createElement("input");
      input.type = "email";
    } else if (field.field_type === "number") {
      input = document.createElement("input");
      input.type = "number";
    } else {
      // Default to text
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
    return container;
  }

  /**
   * Render the widget form into a container.
   */
  function renderForm(container, config, widgetId, baseUrl) {
    container.innerHTML = "";

    // Title
    if (config.title) {
      var title = document.createElement("h3");
      title.textContent = config.title;
      title.style.margin = "0 0 12px 0";
      title.style.fontSize = "18px";
      title.style.fontWeight = "bold";
      container.appendChild(title);
    }

    // Description
    if (config.description) {
      var desc = document.createElement("p");
      desc.textContent = config.description;
      desc.style.margin = "0 0 16px 0";
      desc.style.fontSize = "14px";
      desc.style.color = "#666";
      container.appendChild(desc);
    }

    // Form
    var form = document.createElement("form");
    form.style.display = "flex";
    form.style.flexDirection = "column";

    // Render form fields
    if (config.form_fields && Array.isArray(config.form_fields)) {
      config.form_fields.forEach(function (field) {
        form.appendChild(createFormInput(field));
      });
    }

    // Submit button
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
    button.style.transition = "opacity 0.2s";
    button.onmouseover = function () {
      this.style.opacity = "0.9";
    };
    button.onmouseout = function () {
      this.style.opacity = "1";
    };

    form.appendChild(button);

    // Form submission handler
    form.onsubmit = function (e) {
      e.preventDefault();
      submitForm(form, widgetId, baseUrl);
    };

    container.appendChild(form);
  }

  /**
   * Collect form data and post to the submission endpoint.
   * TODO: wire to POST /api/v1/widgets/{id}/submit once built
   */
  function submitForm(form, widgetId, baseUrl) {
    var formData = new FormData(form);
    var payload = {};

    formData.forEach(function (value, key) {
      payload[key] = value;
    });

    console.log("[FlyRank Widget] Submission payload:", payload);

    // TODO: Once submission endpoint is built, uncomment:
    // fetch(baseUrl + '/api/v1/widgets/' + widgetId + '/submit', {
    //   method: 'POST',
    //   headers: { 'Content-Type': 'application/json' },
    //   body: JSON.stringify(payload),
    //   credentials: 'omit',
    //   mode: 'cors',
    // })
    // .then(function (response) {
    //   if (!response.ok) {
    //     console.error('[FlyRank Widget] Submission failed:', response.status);
    //     return;
    //   }
    //   console.log('[FlyRank Widget] Submission successful');
    //   form.reset();
    // })
    // .catch(function (error) {
    //   console.error('[FlyRank Widget] Submission error:', error.message);
    // });

    // For now, just log success
    alert("Form submitted! (Submission endpoint not yet implemented)");
    form.reset();
  }

  /**
   * Main initialization: load config and render.
   */
  async function init() {
    var widgetId = getWidgetIdFromScript();
    if (!widgetId) {
      console.error("[FlyRank Widget] Cannot initialize without widget ID");
      return;
    }

    var baseUrl = getBaseUrl();
    var config = await fetchWidgetConfig(widgetId, baseUrl);
    if (!config) {
      console.error("[FlyRank Widget] Failed to load widget config");
      return;
    }

    // Create container and insert after script tag
    var script = document.currentScript;
    var container = document.createElement("div");
    container.id = "flyrank-widget-" + widgetId;
    container.style.fontFamily = "sans-serif";
    container.style.maxWidth = "500px";
    container.style.margin = "0";
    container.style.padding = "20px";
    container.style.border = "1px solid #eee";
    container.style.borderRadius = "6px";
    container.style.backgroundColor = "#fafafa";
    container.style.boxSizing = "border-box";

    // Insert after the script tag
    if (script.parentNode) {
      script.parentNode.insertBefore(container, script.nextSibling);
    }

    renderForm(container, config, widgetId, baseUrl);
  }

  // Run init when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
