/**
 * Climate Profile Card
 *
 * A renderer for the `climate_profiles` integration. It shows the profiles,
 * the live values and lets you change them - but it never decides which
 * profile is active. That answer comes from the integration, so automations,
 * voice assistants and the developer tools all agree with what you see here.
 *
 * Plain web components on purpose: no build step, no external dependencies.
 */

const CARD_VERSION = "2.0.0-beta.1";

/* eslint-disable no-console */
console.info(
  `%c CLIMATE-PROFILE-CARD %c ${CARD_VERSION} `,
  "color:#fff;background:#03a9f4;font-weight:700;border-radius:3px 0 0 3px;padding:2px 4px",
  "color:#03a9f4;background:#f1f5f9;border-radius:0 3px 3px 0;padding:2px 4px"
);

const CUSTOM_ID = "__custom__";

/** Purely cosmetic icons - unknown modes fall back to a neutral one. */
const HVAC_ICONS = {
  off: "mdi:power",
  heat: "mdi:fire",
  cool: "mdi:snowflake",
  auto: "mdi:autorenew",
  dry: "mdi:water-percent",
  fan_only: "mdi:fan",
  heat_cool: "mdi:sun-snowflake-variant",
};

const FALLBACK_ICON = "mdi:tune-variant";

/* -------------------------------------------------------------------------
 * helpers
 * ---------------------------------------------------------------------- */

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

const isNum = (value) => typeof value === "number" && Number.isFinite(value);

function hexToRgb(hex) {
  const value = String(hex || "").trim();
  const match = /^#?([\da-f]{3}|[\da-f]{6})$/i.exec(value);
  if (!match) return [3, 169, 244];
  let body = match[1];
  if (body.length === 3) body = body.split("").map((c) => c + c).join("");
  return [0, 2, 4].map((i) => parseInt(body.slice(i, i + 2), 16));
}

/** WCAG relative luminance of a colour. */
function luminance(hex) {
  const [r, g, b] = hexToRgb(hex).map((channel) => {
    const c = channel / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Contrast ratio between two colours, 1:1 to 21:1. */
function contrastRatio(a, b) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

/**
 * Picks the text colour that is actually more readable on `hex`.
 *
 * A fixed luminance threshold gets edge cases wrong in both directions - a
 * mid purple like #8b5cf6 reads better on white, a mid green like #22c55e on
 * black - so both candidates are measured instead of guessed.
 */
const TEXT_DARK = "#101418";
const TEXT_LIGHT = "#ffffff";

function contrastColor(hex) {
  return contrastRatio(hex, TEXT_DARK) >= contrastRatio(hex, TEXT_LIGHT)
    ? TEXT_DARK
    : TEXT_LIGHT;
}

function roundToStep(value, step, min) {
  if (!isNum(value)) return value;
  const size = isNum(step) && step > 0 ? step : 0.5;
  const base = isNum(min) ? min : 0;
  const rounded = Math.round((value - base) / size) * size + base;
  return Math.round(rounded * 100) / 100;
}

function formatNumber(value, step) {
  if (!isNum(value)) return "–";
  const decimals = isNum(step) && step > 0 && step < 1 ? 1 : 0;
  return value.toFixed(decimals);
}

/* -------------------------------------------------------------------------
 * the card
 * ---------------------------------------------------------------------- */

class ClimateProfileCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._hass = null;
    this._built = false;
    this._signature = "";
    this._pending = new Map(); // key -> { value, until }
    this._tempTimer = null;
    //: One debounce timer per slider, keyed by the value it belongs to.
    this._sliderTimers = {};
    this._busy = 0;
    this._naming = false;
    this._error = null;
    this._errorTimer = null;
  }

  static getConfigElement() {
    return document.createElement("climate-profile-card-editor");
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) =>
        id.startsWith("sensor.") &&
        hass.states[id].attributes.active_profile_id !== undefined
    );
    return { type: "custom:climate-profile-card", entity: entity || "" };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Please pick the climate profile sensor of your device.");
    }
    if (!config.entity.startsWith("sensor.")) {
      throw new Error("entity must be the `sensor.…` entity of Climate Profiles.");
    }
    this._config = {
      // Everything is shown unless it is hidden, so a value added later needs
      // no change here and none in the dashboard.
      hide: [],
      profile_layout: "auto",
      ...config,
    };
    this._built = false;
    this._signature = "";
    if (this._hass) this._update();
  }

  getCardSize() {
    return 6;
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  /* ---- view model ---- */

  _model() {
    const hass = this._hass;
    const source = hass.states[this._config.entity];
    if (!source) return { error: `Entity ${this._config.entity} not found.` };

    const attrs = source.attributes || {};
    if (!Array.isArray(attrs.profiles) || !attrs.entities) {
      return {
        error: `${this._config.entity} is not a Climate Profiles sensor.`,
      };
    }

    const entities = attrs.entities || {};
    const caps = attrs.capabilities || {};
    const climate = entities.climate ? hass.states[entities.climate] : null;

    // The additional values: the integration says what they are called and how
    // to draw them, this only reads their state. The card knows no value by
    // name any more - it only ever sees ids here.
    const additional = (attrs.additional_values || [])
      .slice()
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
      .map((definition) => {
        const state = hass.states[definition.entity] || null;
        return {
          ...definition,
          state,
          value: this._readValue(definition, state),
        };
      })
      .filter((value) => value.kind);

    const unavailable =
      !climate || ["unavailable", "unknown"].includes(climate.state);

    return {
      source,
      attrs,
      entities,
      caps,
      climate,
      additional,
      unavailable,
      profiles: attrs.profiles || [],
      custom: attrs.custom_profile || {
        id: CUSTOM_ID,
        name: "Custom",
        color: "#78909c",
      },
      activeId: attrs.active_profile_id || CUSTOM_ID,
      applying: Boolean(attrs.applying) || this._busy > 0,
      changed: attrs.changed_values || [],
      lastMatched:
        (attrs.profiles || []).find(
          (profile) => profile.id === attrs.last_matched_profile_id
        ) || null,
      hvacMode: climate ? climate.state : null,
      hvacModes: caps.hvac_modes || [],
      fanModes: caps.fan_modes || [],
      swingModes: caps.swing_modes || [],
      fanMode: climate ? climate.attributes.fan_mode : null,
      swingMode: climate ? climate.attributes.swing_mode : null,
      target: this._value("temperature", climate?.attributes.temperature),
      current: climate ? climate.attributes.current_temperature : null,
      action: climate ? climate.attributes.hvac_action : null,
      unit: hass.config.unit_system.temperature || "°C",
    };
  }

  /** Read one additional value's state in the shape its kind needs. */
  _readValue(definition, state) {
    if (!state || ["unavailable", "unknown"].includes(state.state)) return null;
    if (definition.kind === "number") {
      const number = Number(state.state);
      return Number.isFinite(number) ? number : null;
    }
    if (definition.kind === "boolean") return state.state === "on";
    return state.state;
  }

  /** Optimistic value: what the user just asked for, until the state agrees. */
  _value(key, actual) {
    const pending = this._pending.get(key);
    if (!pending) return actual;
    if (Date.now() > pending.until) {
      this._pending.delete(key);
      return actual;
    }
    if (isNum(actual) && isNum(pending.value) && Math.abs(actual - pending.value) < 0.01) {
      this._pending.delete(key);
      return actual;
    }
    if (actual === pending.value) {
      this._pending.delete(key);
      return actual;
    }
    return pending.value;
  }

  _setPending(key, value, ms = 8000) {
    this._pending.set(key, { value, until: Date.now() + ms });
  }

  /**
   * Everything configured is shown unless it is hidden, so a value added later
   * appears without editing every dashboard. One list over one key space - the
   * four climate keys and the ids of the additional values, the same mix that
   * a profile's ``values`` carries.
   */
  _visible(key, available) {
    const hide = this._config.hide;
    const hidden = Array.isArray(hide) && hide.includes(key);
    return !hidden && Boolean(available);
  }

  /* ---- rendering ---- */

  _update() {
    if (!this._config || !this._hass) return;
    const model = this._model();

    if (model.error) {
      this._renderFatal(model.error);
      return;
    }

    const signature = [
      model.profiles.map((p) => `${p.id}:${p.name}:${p.color}`).join("|"),
      model.hvacModes.join(","),
      model.fanModes.join(","),
      model.swingModes.join(","),
      // A value added, removed, renamed or repointed changes the controls, so
      // the card has to be rebuilt rather than repainted.
      model.additional
        .map((v) => `${v.id}:${v.name}:${v.kind}:${Boolean(v.state)}`)
        .join("|"),
      (this._config.hide || []).join(","),
      this._config.profile_layout,
    ].join("::");

    if (!this._built || signature !== this._signature) {
      this._signature = signature;
      this._build(model);
      this._built = true;
    }
    this._paint(model);
  }

  _renderFatal(message) {
    this._built = false;
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="fatal">
          <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
          <span></span>
        </div>
      </ha-card>
      <style>${STYLES}</style>`;
    this.shadowRoot.querySelector(".fatal span").textContent = message;
  }

  _build(model) {
    const root = this.shadowRoot;
    root.innerHTML = `
      <ha-card>
        <div class="progress" part="progress"></div>
        <div class="alert" role="alert" hidden></div>

        <header class="header">
          <div class="badge"><ha-icon icon="mdi:air-conditioner"></ha-icon></div>
          <div class="titles">
            <h1 class="title"></h1>
            <p class="subtitle"></p>
          </div>
          <button class="pill" type="button" title="">
            <span class="dot"></span><span class="pill-text"></span>
          </button>
        </header>

        <section class="temp" hidden>
          <button class="step" data-step="down" type="button" aria-label="Warmer">
            <ha-icon icon="mdi:minus"></ha-icon>
          </button>
          <div class="readout">
            <div class="value"><span class="degrees">–</span><span class="unit"></span></div>
            <div class="meter"><div class="meter-fill"></div></div>
            <div class="ambient"></div>
          </div>
          <button class="step" data-step="up" type="button" aria-label="Cooler">
            <ha-icon icon="mdi:plus"></ha-icon>
          </button>
        </section>

        <section class="profiles" role="group"></section>

        <section class="capture" hidden>
          <div class="capture-main">
            <ha-icon icon="mdi:pencil-outline"></ha-icon>
            <div class="capture-text">
              <span class="capture-title"></span>
              <span class="capture-values"></span>
            </div>
          </div>
          <div class="capture-actions">
            <button class="capture-into" type="button">
              <ha-icon icon="mdi:content-save-outline"></ha-icon><span></span>
            </button>
            <button class="capture-new" type="button">
              <ha-icon icon="mdi:bookmark-plus-outline"></ha-icon><span></span>
            </button>
          </div>
          <form class="capture-form" hidden>
            <input class="capture-name" type="text" maxlength="40" />
            <button class="capture-save" type="submit">
              <ha-icon icon="mdi:check"></ha-icon>
            </button>
            <button class="capture-cancel" type="button">
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </form>
        </section>

        <section class="controls"></section>
      </ha-card>
      <style>${STYLES}</style>`;

    this._el = {
      card: root.querySelector("ha-card"),
      progress: root.querySelector(".progress"),
      alert: root.querySelector(".alert"),
      badge: root.querySelector(".badge ha-icon"),
      title: root.querySelector(".title"),
      subtitle: root.querySelector(".subtitle"),
      pill: root.querySelector(".pill"),
      pillText: root.querySelector(".pill-text"),
      temp: root.querySelector(".temp"),
      degrees: root.querySelector(".degrees"),
      unit: root.querySelector(".unit"),
      meter: root.querySelector(".meter-fill"),
      ambient: root.querySelector(".ambient"),
      profiles: root.querySelector(".profiles"),
      controls: root.querySelector(".controls"),
      capture: root.querySelector(".capture"),
      captureTitle: root.querySelector(".capture-title"),
      captureValues: root.querySelector(".capture-values"),
      captureActions: root.querySelector(".capture-actions"),
      captureInto: root.querySelector(".capture-into"),
      captureNew: root.querySelector(".capture-new"),
      captureForm: root.querySelector(".capture-form"),
      captureName: root.querySelector(".capture-name"),
      captureCancel: root.querySelector(".capture-cancel"),
    };

    root.querySelectorAll(".step").forEach((button) => {
      button.addEventListener("click", () =>
        this._nudgeTemperature(button.dataset.step === "up" ? 1 : -1)
      );
    });
    this._el.pill.addEventListener("click", () => this._togglePower());

    this._wireCapture();
    this._buildProfiles(model);
    this._buildControls(model);
  }

  _buildProfiles(model) {
    const wrap = this._el.profiles;
    wrap.innerHTML = "";
    wrap.setAttribute("aria-label", this._t("Profiles"));
    wrap.dataset.layout = this._layout(model.profiles.length);

    const all = [...model.profiles, { ...model.custom, virtual: true }];
    this._profileButtons = new Map();

    for (const profile of all) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "profile";
      button.dataset.id = profile.id;
      if (profile.virtual) button.classList.add("virtual");
      const [r, g, b] = hexToRgb(profile.color);
      button.style.setProperty("--profile-rgb", `${r}, ${g}, ${b}`);
      button.style.setProperty("--profile-color", profile.color);
      button.style.setProperty("--profile-contrast", contrastColor(profile.color));
      // An icon only when the user chose one - otherwise a dot in the
      // profile's colour, which says more than the same filler icon six times.
      const mark = profile.icon
        ? `<ha-icon icon="${profile.icon}"></ha-icon>`
        : `<span class="dot-mark" aria-hidden="true"></span>`;
      button.innerHTML = `
        ${mark}
        <span class="profile-name"></span>
        <span class="check" aria-hidden="true"><ha-icon icon="mdi:check"></ha-icon></span>`;
      button.querySelector(".profile-name").textContent = profile.name;
      if (profile.virtual) {
        button.disabled = true;
        button.title = this._t(
          "Shown when the current state matches none of your profiles."
        );
      } else {
        button.addEventListener("click", () => this._applyProfile(profile));
      }
      wrap.appendChild(button);
      this._profileButtons.set(profile.id, button);
    }
  }

  _wireCapture() {
    const el = this._el;
    el.captureInto.addEventListener("click", () => this._captureIntoProfile());
    el.captureNew.addEventListener("click", () => this._openNameField());
    el.captureCancel.addEventListener("click", () => this._closeNameField());
    el.captureForm.addEventListener("submit", (event) => {
      event.preventDefault();
      this._saveAsNewProfile(el.captureName.value);
    });
    el.captureName.addEventListener("keydown", (event) => {
      if (event.key === "Escape") this._closeNameField();
    });
  }

  _openNameField() {
    this._naming = true;
    const el = this._el;
    el.captureActions.hidden = true;
    el.captureForm.hidden = false;
    el.captureName.value = "";
    el.captureName.focus();
  }

  _closeNameField() {
    this._naming = false;
    const el = this._el;
    el.captureForm.hidden = true;
    el.captureActions.hidden = false;
  }

  _layout(count) {
    const configured = this._config.profile_layout;
    if (configured === "grid" || configured === "scroll") return configured;
    return count > 6 ? "scroll" : "grid";
  }

  _buildControls(model) {
    const wrap = this._el.controls;
    wrap.innerHTML = "";
    this._controls = {};

    if (this._visible("hvac_mode", model.hvacModes.length)) {
      wrap.appendChild(
        this._segmented({
          key: "hvac_mode",
          label: this._t("Mode"),
          options: model.hvacModes,
          icons: true,
          translate: (mode) =>
            this._localize(`component.climate.entity_component._.state.${mode}`, mode),
          onSelect: (mode) => this._setValue({ hvac_mode: mode }),
        })
      );
    }

    const row = document.createElement("div");
    row.className = "row";
    let rowUsed = false;

    if (this._visible("fan_mode", model.fanModes.length)) {
      row.appendChild(
        this._picker({
          key: "fan_mode",
          label: this._t("Fan mode"),
          icon: "mdi:fan",
          options: model.fanModes,
          translate: (value) =>
            this._localize(
              `component.climate.entity_component._.state_attributes.fan_mode.state.${value}`,
              value
            ),
          onSelect: (value) => this._setValue({ fan_mode: value }),
        })
      );
      rowUsed = true;
    }
    if (this._visible("swing_mode", model.swingModes.length)) {
      row.appendChild(
        this._picker({
          key: "swing_mode",
          label: this._t("Swing"),
          icon: "mdi:arrow-oscillating",
          options: model.swingModes,
          translate: (value) =>
            this._localize(
              `component.climate.entity_component._.state_attributes.swing_mode.state.${value}`,
              value
            ),
          onSelect: (value) => this._setValue({ swing_mode: value }),
        })
      );
      rowUsed = true;
    }
    if (rowUsed) wrap.appendChild(row);

    // The additional values, in their configured order. Which control to draw
    // follows from the kind, which follows from the entity's domain - nothing
    // here knows what any single value means.
    const toggles = document.createElement("div");
    toggles.className = "row toggles";
    let togglesUsed = false;

    for (const value of model.additional) {
      if (!this._visible(value.id, value.state)) continue;
      if (value.kind === "number") {
        wrap.appendChild(this._slider(value));
      } else if (value.kind === "boolean") {
        toggles.appendChild(
          this._toggle({
            key: value.id,
            label: value.name,
            icon: value.icon || "mdi:toggle-switch-outline",
            onToggle: (on) => this._setValue({ [value.id]: on }),
          })
        );
        togglesUsed = true;
      } else if (value.kind === "option" && (value.options || []).length) {
        wrap.appendChild(
          this._picker({
            key: value.id,
            label: value.name,
            icon: value.icon || FALLBACK_ICON,
            options: value.options,
            translate: (option) => this._prettify(option),
            onSelect: (option) => this._setValue({ [value.id]: option }),
          })
        );
      }
    }
    if (togglesUsed) wrap.appendChild(toggles);
  }

  _segmented({ key, label, options, icons, translate, onSelect }) {
    const block = document.createElement("div");
    block.className = "block";
    block.innerHTML = `<div class="label"></div><div class="segmented" role="group"></div>`;
    block.querySelector(".label").textContent = label;
    const group = block.querySelector(".segmented");
    group.setAttribute("aria-label", label);

    const buttons = new Map();
    for (const option of options) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "segment";
      button.dataset.value = option;
      const text = translate ? translate(option) : option;
      button.innerHTML = icons
        ? `<ha-icon icon="${HVAC_ICONS[option] || FALLBACK_ICON}"></ha-icon><span></span>`
        : `<span></span>`;
      button.querySelector("span").textContent = text;
      button.setAttribute("aria-label", `${label}: ${text}`);
      button.addEventListener("click", () => onSelect(option));
      group.appendChild(button);
      buttons.set(option, button);
    }
    this._controls[key] = { block, buttons, kind: "segmented" };
    return block;
  }

  _picker({ key, label, icon, options, translate, onSelect }) {
    const block = document.createElement("div");
    block.className = "block field";
    block.innerHTML = `
      <div class="field-head">
        <ha-icon icon="${icon}"></ha-icon>
        <div class="field-label"></div>
      </div>
      <div class="chips" role="group"></div>`;
    block.querySelector(".field-label").textContent = label;
    const chips = block.querySelector(".chips");
    chips.setAttribute("aria-label", label);

    const buttons = new Map();
    for (const option of options) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.dataset.value = option;
      const text = translate ? translate(option) : option;
      button.textContent = text;
      button.setAttribute("aria-label", `${label}: ${text}`);
      button.addEventListener("click", () => onSelect(option));
      chips.appendChild(button);
      buttons.set(option, button);
    }
    this._controls[key] = { block, buttons, kind: "chips" };
    return block;
  }

  _slider(definition) {
    const block = document.createElement("div");
    block.className = "block";
    block.innerHTML = `
      <div class="label-row">
        <div class="label"></div>
        <output class="slider-value"></output>
      </div>
      <input class="slider" type="range" />`;
    block.querySelector(".label").textContent = definition.name;

    // The range belongs to the entity, not to us.
    const input = block.querySelector(".slider");
    input.min = isNum(definition.min) ? definition.min : 0;
    input.max = isNum(definition.max) ? definition.max : 100;
    input.step = isNum(definition.step) && definition.step > 0 ? definition.step : 1;
    input.setAttribute("aria-label", definition.name);

    input.addEventListener("input", () => {
      const value = Number(input.value);
      this._setPending(definition.id, value);
      this._paintSliderFill(input);
      block.querySelector(".slider-value").textContent = `${formatNumber(value, Number(input.step))}`;
      clearTimeout(this._sliderTimers[definition.id]);
      this._sliderTimers[definition.id] = setTimeout(
        () => this._setValue({ [definition.id]: value }),
        500
      );
    });

    this._controls[definition.id] = { block, input, kind: "slider" };
    return block;
  }

  _toggle({ key, label, icon, onToggle }) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "toggle";
    button.innerHTML = `
      <ha-icon icon="${icon}"></ha-icon>
      <div class="toggle-text">
        <span class="toggle-label"></span>
        <span class="toggle-state"></span>
      </div>
      <span class="switch" aria-hidden="true"><span class="knob"></span></span>`;
    button.querySelector(".toggle-label").textContent = label;
    button.addEventListener("click", () => {
      const next = button.getAttribute("aria-pressed") !== "true";
      onToggle(next);
    });
    this._controls[key] = { block: button, button, label, kind: "toggle" };
    return button;
  }

  /* ---- painting ---- */

  _paint(model) {
    const el = this._el;
    const activeProfile =
      model.profiles.find((profile) => profile.id === model.activeId) || model.custom;

    el.card.classList.toggle("unavailable", model.unavailable);
    el.card.style.setProperty("--accent-color", activeProfile.color);
    const [r, g, b] = hexToRgb(activeProfile.color);
    el.card.style.setProperty("--accent-rgb", `${r}, ${g}, ${b}`);

    el.title.textContent =
      this._config.name || model.source.attributes.friendly_name || model.source.entity_id;
    el.subtitle.textContent = model.unavailable
      ? this._t("Unavailable")
      : activeProfile.name;
    el.badge.setAttribute(
      "icon",
      HVAC_ICONS[model.hvacMode] || "mdi:air-conditioner"
    );

    const on = model.hvacMode && model.hvacMode !== "off";
    el.pill.classList.toggle("on", Boolean(on));
    el.pill.setAttribute("aria-pressed", on ? "true" : "false");
    el.pillText.textContent = on
      ? this._localize(
          `component.climate.entity_component._.state.${model.hvacMode}`,
          model.hvacMode
        )
      : this._t("Off");
    el.pill.title = on ? this._t("Turn off") : this._t("Turn on");
    el.pill.disabled = model.unavailable || !model.hvacModes.includes("off");

    // temperature
    const showTemp =
      this._config.show_temperature !== false && isNum(model.target);
    el.temp.hidden = !showTemp;
    if (showTemp) {
      el.degrees.textContent = formatNumber(model.target, model.caps.target_temp_step);
      el.unit.textContent = model.unit;
      const min = isNum(model.caps.min_temp) ? model.caps.min_temp : 16;
      const max = isNum(model.caps.max_temp) ? model.caps.max_temp : 30;
      const ratio = max > min ? clamp((model.target - min) / (max - min), 0, 1) : 0;
      el.meter.style.width = `${(ratio * 100).toFixed(1)}%`;
      el.ambient.textContent = isNum(model.current)
        ? `${this._t("Currently")} ${formatNumber(model.current, 0.1)} ${model.unit}${
            model.action ? ` · ${this._localize(
              `component.climate.entity_component._.state_attributes.hvac_action.state.${model.action}`,
              model.action
            )}` : ""
          }`
        : "";
      this.shadowRoot.querySelectorAll(".step").forEach((button) => {
        button.disabled = model.unavailable;
      });
    }

    // profiles
    for (const [id, button] of this._profileButtons) {
      const isActive = id === model.activeId;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
      if (!button.classList.contains("virtual")) {
        button.disabled = model.unavailable;
      }
    }

    // controls
    this._paintGroup("hvac_mode", model.hvacMode, model.unavailable);
    this._paintGroup("fan_mode", model.fanMode, model.unavailable || !on);
    this._paintGroup("swing_mode", model.swingMode, model.unavailable || !on);

    for (const value of model.additional) {
      const control = this._controls[value.id];
      if (!control) continue;
      const shown = this._value(value.id, value.value);
      if (control.kind === "slider") {
        const number = isNum(shown) ? shown : Number(control.input.min);
        if (document.activeElement !== control.input) control.input.value = number;
        control.input.disabled = model.unavailable;
        control.block.querySelector(".slider-value").textContent = formatNumber(
          Number(control.input.value),
          Number(control.input.step)
        );
        control.input.setAttribute("aria-valuetext", `${control.input.value}`);
        this._paintSliderFill(control.input);
      } else if (control.kind === "toggle") {
        this._paintToggle(value.id, shown, model.unavailable);
      } else {
        this._paintGroup(value.id, shown, model.unavailable);
      }
    }

    this._paintCapture(model);

    el.progress.classList.toggle("busy", Boolean(model.applying));
    el.card.setAttribute("aria-busy", model.applying ? "true" : "false");
  }

  /**
   * Offers to write the manual changes back into a profile.
   *
   * Shown whenever something was adjusted since a profile became active -
   * including while a partial profile is still matching, because a value it
   * does not define never unmatches it.
   */
  _paintCapture(model) {
    const el = this._el;
    const changed = model.changed || [];
    const show = changed.length > 0 && !model.unavailable;
    el.capture.hidden = !show;
    if (!show) {
      if (this._naming) this._closeNameField();
      return;
    }

    el.captureTitle.textContent = this._t("Changed by hand");
    // Changed values arrive as keys: four are the climate ones, the rest are
    // ids only the definitions can name.
    el.captureValues.textContent = changed
      .map((key) => {
        if (CLIMATE_LABELS[key]) return this._t(CLIMATE_LABELS[key]);
        const value = model.additional.find((item) => item.id === key);
        return value ? value.name : key;
      })
      .join(" · ");

    const target = model.lastMatched;
    const protectedTarget = Boolean(target && target.protected);
    el.captureInto.hidden = !target || protectedTarget;
    if (target && !protectedTarget) {
      const label = `${this._t("Save into")} ${target.name}`;
      el.captureInto.querySelector("span").textContent = label;
      el.captureInto.setAttribute("aria-label", label);
      el.captureInto.style.setProperty("--profile-color", target.color);
      const [r, g, b] = hexToRgb(target.color);
      el.captureInto.style.setProperty("--profile-rgb", `${r}, ${g}, ${b}`);
    }

    const newLabel = this._t("New profile");
    el.captureNew.querySelector("span").textContent = newLabel;
    el.captureNew.setAttribute("aria-label", newLabel);
    el.captureName.placeholder = this._t("Name of the profile");
    el.captureName.setAttribute("aria-label", this._t("Name of the profile"));

    if (protectedTarget) {
      el.captureTitle.textContent = `${this._t("Changed by hand")} · ${
        target.name
      } ${this._t("is write protected")}`;
    }
  }

  _paintGroup(key, current, disabled) {
    const control = this._controls[key];
    if (!control) return;
    const value = this._value(key, current);
    for (const [option, button] of control.buttons) {
      const isActive = String(option).toLowerCase() === String(value).toLowerCase();
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
      button.disabled = Boolean(disabled);
    }
  }

  _paintSliderFill(input) {
    const min = Number(input.min);
    const max = Number(input.max);
    const ratio = max > min ? clamp((Number(input.value) - min) / (max - min), 0, 1) : 0;
    input.style.setProperty("--fill", `${(ratio * 100).toFixed(1)}%`);
  }

  _paintToggle(key, on, disabled) {
    const control = this._controls[key];
    if (!control) return;
    const isOn = on === true;
    control.button.classList.toggle("on", isOn);
    control.button.setAttribute("aria-pressed", isOn ? "true" : "false");
    control.button.disabled = Boolean(disabled) || on === null;
    control.button.querySelector(".toggle-state").textContent = isOn
      ? this._t("On")
      : this._t("Off");
    control.button.setAttribute(
      "aria-label",
      `${control.label}: ${isOn ? this._t("On") : this._t("Off")}`
    );
  }

  /* ---- actions ---- */

  _nudgeTemperature(direction) {
    const model = this._model();
    if (model.error || !isNum(model.target)) return;
    const step = isNum(model.caps.target_temp_step) ? model.caps.target_temp_step : 0.5;
    const min = isNum(model.caps.min_temp) ? model.caps.min_temp : 5;
    const max = isNum(model.caps.max_temp) ? model.caps.max_temp : 35;
    const next = clamp(
      roundToStep(model.target + direction * step, step, min),
      min,
      max
    );
    if (next === model.target) return;

    this._setPending("temperature", next);
    this._update();

    // Coalesce rapid taps into one service call.
    clearTimeout(this._tempTimer);
    this._tempTimer = setTimeout(() => this._setValue({ temperature: next }), 600);
  }

  _togglePower() {
    const model = this._model();
    if (model.error) return;
    const off = model.hvacModes.includes("off") ? "off" : null;
    if (!off) return;
    if (model.hvacMode === "off") {
      const fallback =
        model.hvacModes.find((mode) => mode !== "off") || null;
      if (fallback) this._setValue({ hvac_mode: fallback });
      return;
    }
    this._setValue({ hvac_mode: off });
  }

  async _captureIntoProfile() {
    await this._call("capture_profile", {});
  }

  async _saveAsNewProfile(name) {
    const trimmed = String(name || "").trim();
    if (!trimmed) {
      this._showError(this._t("Please enter a name."));
      return;
    }
    this._closeNameField();
    await this._call("save_as_profile", { name: trimmed });
  }

  async _applyProfile(profile) {
    await this._call("apply_profile", { profile: profile.id });
  }

  async _setValue(values) {
    for (const [key, value] of Object.entries(values)) {
      this._setPending(key, value);
    }
    this._update();
    await this._call("set_value", values);
  }

  async _call(service, data) {
    this._busy += 1;
    this._update();
    try {
      await this._hass.callService("climate_profiles", service, {
        entity_id: this._config.entity,
        ...data,
      });
      this._clearError();
    } catch (err) {
      this._pending.clear();
      this._showError(
        (err && (err.message || err.error)) || this._t("The command failed.")
      );
    } finally {
      this._busy = Math.max(0, this._busy - 1);
      this._update();
    }
  }

  _showError(message) {
    this._error = message;
    const alert = this._el && this._el.alert;
    if (!alert) return;
    alert.textContent = message;
    alert.hidden = false;
    clearTimeout(this._errorTimer);
    this._errorTimer = setTimeout(() => this._clearError(), 8000);
  }

  _clearError() {
    this._error = null;
    if (this._el && this._el.alert) this._el.alert.hidden = true;
  }

  /* ---- i18n ---- */

  _localize(key, fallback) {
    const translated = this._hass && this._hass.localize && this._hass.localize(key);
    return translated || this._prettify(fallback);
  }

  _prettify(value) {
    if (value === null || value === undefined) return "–";
    return String(value)
      .replace(/_/g, " ")
      .replace(/^\w/, (char) => char.toUpperCase());
  }

  /** Card-owned strings. German when Home Assistant is German. */
  _t(text) {
    const language = (this._hass && this._hass.language) || "en";
    if (!language.startsWith("de")) return text;
    return CARD_DE[text] || text;
  }
}

//: The four values Home Assistant defines. Everything else is named by the
//: user, which is why it is not in here.
const CLIMATE_LABELS = {
  hvac_mode: "Mode",
  temperature: "Temperature",
  swing_mode: "Swing",
  fan_mode: "Fan mode",
};

const CARD_DE = {
  Profiles: "Profile",
  Mode: "Modus",
  "Fan mode": "Lüftermodus",
  Swing: "Swing",
  On: "An",
  Off: "Aus",
  Currently: "Aktuell",
  Unavailable: "Nicht verfügbar",
  "Turn on": "Einschalten",
  "Turn off": "Ausschalten",
  "The command failed.": "Der Befehl ist fehlgeschlagen.",
  "Changed by hand": "Von Hand geändert",
  "Save into": "Übernehmen in",
  "New profile": "Neues Profil",
  "Name of the profile": "Name des Profils",
  "Please enter a name.": "Bitte gib einen Namen ein.",
  "is write protected": "ist schreibgeschützt",
  Temperature: "Temperatur",
  "Shown when the current state matches none of your profiles.":
    "Wird angezeigt, wenn der aktuelle Zustand zu keinem Profil passt.",
};

/* -------------------------------------------------------------------------
 * styles
 * ---------------------------------------------------------------------- */

const STYLES = `
:host {
  --cp-radius: var(--ha-card-border-radius, 16px);
  --cp-gap: 14px;
  --cp-surface: var(--card-background-color, #fff);
  --cp-text: var(--primary-text-color, #1f2933);
  --cp-muted: var(--secondary-text-color, #6b7280);
  --cp-line: var(--divider-color, rgba(127, 127, 127, 0.25));
  --cp-fill: rgba(var(--rgb-primary-text-color, 33, 33, 33), 0.06);
  --accent-color: var(--primary-color, #03a9f4);
  --accent-rgb: 3, 169, 244;
  display: block;
}

ha-card {
  position: relative;
  overflow: hidden;
  padding: 18px 18px 20px;
  display: flex;
  flex-direction: column;
  gap: var(--cp-gap);
  border-radius: var(--cp-radius);
  color: var(--cp-text);
}

ha-card::before {
  content: "";
  position: absolute;
  inset: 0 0 auto 0;
  height: 140px;
  background: linear-gradient(180deg, rgba(var(--accent-rgb), 0.16), transparent 85%);
  pointer-events: none;
  transition: background 320ms ease;
}

ha-card > * { position: relative; }

ha-card.unavailable { opacity: 0.6; }

/* progress + errors */
.progress {
  position: absolute;
  inset: 0 0 auto 0;
  height: 3px;
  overflow: hidden;
  opacity: 0;
  transition: opacity 160ms ease;
  z-index: 2;
}
.progress.busy { opacity: 1; }
.progress::after {
  content: "";
  position: absolute;
  inset: 0;
  width: 40%;
  border-radius: 3px;
  background: var(--accent-color);
  animation: slide 1.1s ease-in-out infinite;
}
@keyframes slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(320%); }
}

.alert[hidden] { display: none; }
.alert {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 12px;
  font-size: 0.85rem;
  line-height: 1.35;
  color: var(--error-color, #c62828);
  background: rgba(var(--rgb-error-color, 198, 40, 40), 0.12);
}

.fatal {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px;
  color: var(--error-color, #c62828);
  font-size: 0.9rem;
}

/* header */
.header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.badge {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  flex: none;
  border-radius: 14px;
  color: var(--accent-color);
  background: rgba(var(--accent-rgb), 0.16);
  transition: background 240ms ease, color 240ms ease;
}
.titles { flex: 1; min-width: 0; }
.title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.subtitle {
  margin: 2px 0 0;
  font-size: 0.82rem;
  color: var(--cp-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex: none;
  padding: 7px 13px;
  border: 1px solid var(--cp-line);
  border-radius: 999px;
  background: transparent;
  color: var(--cp-muted);
  font: inherit;
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
  transition: color 200ms ease, background 200ms ease, border-color 200ms ease;
}
.pill .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.55;
}
.pill.on {
  color: var(--accent-color);
  border-color: rgba(var(--accent-rgb), 0.45);
  background: rgba(var(--accent-rgb), 0.12);
}
.pill.on .dot { opacity: 1; }

/* temperature */
.temp {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 14px;
  padding: 14px 4px 4px;
}
.step {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border: none;
  border-radius: 18px;
  background: var(--cp-fill);
  color: var(--cp-text);
  cursor: pointer;
  transition: transform 120ms ease, background 200ms ease;
  -webkit-tap-highlight-color: transparent;
}
.step:hover:not(:disabled) { background: rgba(var(--accent-rgb), 0.16); }
.step:active:not(:disabled) { transform: scale(0.94); }
.readout { text-align: center; min-width: 0; }
.value {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: 2px;
  font-size: 3rem;
  font-weight: 300;
  line-height: 1;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
.value .unit { font-size: 1.1rem; font-weight: 500; margin-top: 6px; color: var(--cp-muted); }
.meter {
  height: 4px;
  margin: 12px auto 8px;
  width: min(220px, 100%);
  border-radius: 999px;
  background: var(--cp-fill);
  overflow: hidden;
}
.meter-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--accent-color);
  transition: width 260ms ease, background 260ms ease;
}
.ambient { font-size: 0.78rem; color: var(--cp-muted); min-height: 1.1em; }

/* profiles */
.profiles { display: grid; gap: 8px; }
.profiles[data-layout="grid"] {
  grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
}
.profiles[data-layout="scroll"] {
  grid-auto-flow: column;
  grid-auto-columns: minmax(104px, 1fr);
  overflow-x: auto;
  scroll-snap-type: x proximity;
  padding-bottom: 4px;
  scrollbar-width: thin;
}
.profiles[data-layout="scroll"] .profile { scroll-snap-align: start; }

.profile {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  min-height: 74px;
  padding: 11px 8px 10px;
  border: 1px solid var(--cp-line);
  border-radius: 16px;
  background: transparent;
  color: var(--cp-text);
  font: inherit;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  transition: border-color 180ms ease, background 180ms ease, transform 120ms ease;
  -webkit-tap-highlight-color: transparent;
}
.profile ha-icon { color: var(--profile-color); --mdc-icon-size: 22px; }
.dot-mark {
  width: 12px;
  height: 12px;
  margin: 5px 0;
  border-radius: 50%;
  background: var(--profile-color);
  box-shadow: 0 0 0 4px rgba(var(--profile-rgb), 0.18);
  transition: background 180ms ease, box-shadow 180ms ease;
}
.profile.active .dot-mark {
  background: var(--profile-contrast);
  box-shadow: 0 0 0 4px rgba(var(--profile-rgb), 0.35);
}
.profiles[data-layout="grid"] .profile.virtual .dot-mark { margin: 0; }
.profile-name {
  width: 100%;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.profile:hover:not(:disabled) {
  border-color: rgba(var(--profile-rgb), 0.5);
  background: rgba(var(--profile-rgb), 0.08);
}
.profile:active:not(:disabled) { transform: scale(0.97); }
.profile.active {
  border-color: transparent;
  background: var(--profile-color);
  color: var(--profile-contrast);
  box-shadow: 0 6px 18px -8px rgba(var(--profile-rgb), 0.9);
}
.profile.active ha-icon { color: var(--profile-contrast); }
.profile .check {
  position: absolute;
  top: 6px;
  right: 6px;
  display: none;
  --mdc-icon-size: 14px;
}
.profile.active .check { display: block; }
.profile.virtual {
  border-style: dashed;
  color: var(--cp-muted);
  cursor: default;
}
.profiles[data-layout="grid"] .profile.virtual {
  grid-column: 1 / -1;
  flex-direction: row;
  justify-content: center;
  gap: 8px;
  min-height: 0;
  padding: 9px 12px;
}
.profile.virtual.active {
  border-style: solid;
  color: var(--profile-contrast);
}

/* capture offer */
/* Every one of these is a flex container, and "display" beats the "hidden"
   attribute - so each needs its own [hidden] rule. */
.capture[hidden],
.capture-actions[hidden],
.capture-form[hidden],
.capture-into[hidden] { display: none; }

.capture {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px dashed rgba(var(--accent-rgb), 0.5);
  border-radius: 14px;
  background: rgba(var(--accent-rgb), 0.06);
}
.capture-main {
  display: flex;
  align-items: center;
  gap: 9px;
  flex: 1 1 140px;
  min-width: 0;
}
.capture-main > ha-icon { --mdc-icon-size: 18px; color: var(--cp-muted); flex: none; }
.capture-text { display: grid; min-width: 0; }
.capture-title {
  font-size: 0.8rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
}
.capture-values {
  font-size: 0.74rem;
  color: var(--cp-muted);
  overflow: hidden;
  text-overflow: ellipsis;
}
.capture-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.capture-actions button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 11px;
  border: 1px solid var(--cp-line);
  border-radius: 10px;
  background: var(--cp-surface);
  color: var(--cp-text);
  font: inherit;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease;
}
.capture-actions button ha-icon { --mdc-icon-size: 16px; }
.capture-actions button:hover:not(:disabled) { border-color: var(--accent-color); }
.capture-into {
  border-color: rgba(var(--profile-rgb, var(--accent-rgb)), 0.6) !important;
  color: var(--profile-color, var(--accent-color));
}

.capture-form { display: flex; gap: 6px; flex: 1 1 100%; }
.capture-name {
  flex: 1;
  min-width: 0;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--cp-line);
  border-radius: 10px;
  background: var(--cp-surface);
  color: var(--cp-text);
  font: inherit;
  font-size: 0.82rem;
}
.capture-name:focus-visible { outline: 2px solid var(--accent-color); outline-offset: 1px; }
.capture-form button {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: none;
  border: 1px solid var(--cp-line);
  border-radius: 10px;
  background: var(--cp-surface);
  color: var(--cp-text);
  cursor: pointer;
}
.capture-save { border-color: rgba(var(--accent-rgb), 0.6) !important; color: var(--accent-color); }

/* controls */
.controls { display: grid; gap: 12px; }
.block { display: grid; gap: 7px; min-width: 0; }
.label, .field-label {
  font-size: 0.74rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--cp-muted);
}
.label-row { display: flex; align-items: baseline; justify-content: space-between; }
.slider-value { font-size: 0.85rem; font-weight: 600; font-variant-numeric: tabular-nums; }

.segmented {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px;
  border-radius: 14px;
  background: var(--cp-fill);
}
.segment {
  flex: 1 1 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 38px;
  padding: 0 12px;
  border: none;
  border-radius: 11px;
  background: transparent;
  color: var(--cp-muted);
  font: inherit;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: background 180ms ease, color 180ms ease;
}
.segment ha-icon { --mdc-icon-size: 19px; }
.segment:hover:not(:disabled) { color: var(--cp-text); }
.segment.active {
  background: var(--cp-surface);
  color: var(--accent-color);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.14);
}

.row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}
.field {
  padding: 11px 12px;
  border: 1px solid var(--cp-line);
  border-radius: 14px;
}
.field-head { display: flex; align-items: center; gap: 7px; }
.field-head ha-icon { --mdc-icon-size: 17px; color: var(--cp-muted); }
.chips { display: flex; flex-wrap: wrap; gap: 5px; }
.chip {
  padding: 5px 11px;
  border: 1px solid var(--cp-line);
  border-radius: 999px;
  background: transparent;
  color: var(--cp-muted);
  font: inherit;
  font-size: 0.78rem;
  cursor: pointer;
  transition: background 160ms ease, color 160ms ease, border-color 160ms ease;
}
.chip:hover:not(:disabled) { color: var(--cp-text); }
.chip.active {
  border-color: transparent;
  background: rgba(var(--accent-rgb), 0.16);
  color: var(--accent-color);
  font-weight: 600;
}

.slider {
  width: 100%;
  height: 34px;
  margin: 0;
  appearance: none;
  background: transparent;
  cursor: pointer;
}
.slider::-webkit-slider-runnable-track {
  height: 8px;
  border-radius: 999px;
  background: linear-gradient(
    to right,
    var(--accent-color) 0 var(--fill, 0%),
    var(--cp-fill) var(--fill, 0%) 100%
  );
}
.slider::-moz-range-track {
  height: 8px;
  border-radius: 999px;
  background: linear-gradient(
    to right,
    var(--accent-color) 0 var(--fill, 0%),
    var(--cp-fill) var(--fill, 0%) 100%
  );
}
.slider::-webkit-slider-thumb {
  appearance: none;
  width: 22px;
  height: 22px;
  margin-top: -7px;
  border-radius: 50%;
  background: var(--accent-color);
  border: 2px solid var(--cp-surface);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
}
.slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--accent-color);
  border: 2px solid var(--cp-surface);
}

.toggles { gap: 10px; }
.toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 13px;
  border: 1px solid var(--cp-line);
  border-radius: 14px;
  background: transparent;
  color: var(--cp-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 180ms ease, background 180ms ease;
}
.toggle ha-icon { --mdc-icon-size: 20px; color: var(--cp-muted); flex: none; }
.toggle-text { display: grid; flex: 1; min-width: 0; }
.toggle-label { font-size: 0.85rem; font-weight: 500; }
.toggle-state { font-size: 0.74rem; color: var(--cp-muted); }
.toggle .switch {
  position: relative;
  width: 38px;
  height: 22px;
  flex: none;
  border-radius: 999px;
  background: var(--cp-fill);
  transition: background 200ms ease;
}
.toggle .knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--cp-muted);
  transition: transform 200ms cubic-bezier(0.2, 0, 0, 1), background 200ms ease;
}
.toggle.on { border-color: rgba(var(--accent-rgb), 0.4); background: rgba(var(--accent-rgb), 0.08); }
.toggle.on ha-icon { color: var(--accent-color); }
.toggle.on .switch { background: rgba(var(--accent-rgb), 0.35); }
.toggle.on .knob { transform: translateX(16px); background: var(--accent-color); }

/* shared states */
button:disabled { opacity: 0.45; cursor: not-allowed; }
button:focus-visible,
.slider:focus-visible {
  outline: 2px solid var(--accent-color);
  outline-offset: 2px;
}

@media (max-width: 420px) {
  ha-card { padding: 16px 14px 18px; }
  .value { font-size: 2.6rem; }
  .step { width: 48px; height: 48px; }
  .row { grid-template-columns: 1fr; }
}

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
`;

/* -------------------------------------------------------------------------
 * editor
 * ---------------------------------------------------------------------- */

class ClimateProfileCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) {
      this._form.hass = hass;
      this._render();
    }
  }

  /**
   * The switches are built from the sensor's own definitions, so a value the
   * user added shows up here by itself. They are stored the other way round -
   * as the list of what to hide - so a value added later is visible without
   * every dashboard having to be edited.
   */
  _values() {
    const entity = this._config && this._config.entity;
    const state = entity && this._hass ? this._hass.states[entity] : null;
    const attrs = state ? state.attributes || {} : {};
    const climate = [
      ["temperature", "Temperature"],
      ["hvac_mode", "Mode"],
      ["fan_mode", "Fan mode"],
      ["swing_mode", "Swing"],
    ];
    const additional = (attrs.additional_values || [])
      .slice()
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
      .map((value) => [value.id, value.name]);
    return [...climate, ...additional];
  }

  _schema() {
    return [
      ...SCHEMA,
      {
        type: "grid",
        name: "",
        schema: this._values().map(([key]) => ({
          name: `show_${key}`,
          selector: { boolean: {} },
        })),
      },
    ];
  }

  /** Turn the stored hide list into the switches the form shows. */
  _data() {
    const hide = Array.isArray(this._config.hide) ? this._config.hide : [];
    const data = { ...this._config };
    delete data.hide;
    for (const [key] of this._values()) data[`show_${key}`] = !hide.includes(key);
    return data;
  }

  _render() {
    const labels = new Map(this._values());
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.hass = this._hass;
      this._form.computeLabel = (schema) => {
        if (EDITOR_LABELS[schema.name]) return EDITOR_LABELS[schema.name];
        const key = String(schema.name).replace(/^show_/, "");
        return labels.get(key) || schema.name;
      };
      this._form.addEventListener("value-changed", (event) => {
        const value = { ...event.detail.value };
        const hide = [];
        for (const [key] of this._values()) {
          if (value[`show_${key}`] === false) hide.push(key);
          delete value[`show_${key}`];
        }
        if (hide.length) value.hide = hide;
        else delete value.hide;
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: value },
            bubbles: true,
            composed: true,
          })
        );
      });
      this.appendChild(this._form);
    }
    this._form.schema = this._schema();
    this._form.data = this._data();
  }
}

const SCHEMA = [
  {
    name: "entity",
    required: true,
    selector: { entity: { integration: "climate_profiles", domain: "sensor" } },
  },
  { name: "name", selector: { text: {} } },
  {
    name: "profile_layout",
    selector: {
      select: {
        mode: "dropdown",
        options: [
          { value: "auto", label: "Auto" },
          { value: "grid", label: "Grid" },
          { value: "scroll", label: "Scroll" },
        ],
      },
    },
  },
];

const EDITOR_LABELS = {
  entity: "Climate profile sensor",
  name: "Name (optional)",
  profile_layout: "Profile layout",
};

/* -------------------------------------------------------------------------
 * registration
 * ---------------------------------------------------------------------- */

if (!customElements.get("climate-profile-card")) {
  customElements.define("climate-profile-card", ClimateProfileCard);
}
if (!customElements.get("climate-profile-card-editor")) {
  customElements.define("climate-profile-card-editor", ClimateProfileCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "climate-profile-card")) {
  window.customCards.push({
    type: "climate-profile-card",
    name: "Climate Profile Card",
    description:
      "Profiles, temperature and every extra control of your air conditioner in one card.",
    preview: true,
    documentationURL: "https://github.com/julezdean/ha-climate-profiles",
  });
}
