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

const CARD_VERSION = "2.2.0-beta.1";

/* eslint-disable no-console */
console.info(
  `%c CLIMATE-PROFILE-CARD %c ${CARD_VERSION} `,
  "color:#fff;background:#03a9f4;font-weight:700;border-radius:3px 0 0 3px;padding:2px 4px",
  "color:#03a9f4;background:#f1f5f9;border-radius:0 3px 3px 0;padding:2px 4px"
);

const CUSTOM_ID = "__custom__";

/**
 * The mark in front of a profile's name: an icon only when the user chose
 * one, otherwise a dot in the profile's colour - which says more than the
 * same filler icon six times over.
 */
function profileMark(profile) {
  return profile.icon
    ? `<ha-icon icon="${profile.icon}"></ha-icon>`
    : `<span class="dot-mark" aria-hidden="true"></span>`;
}

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

//: The dial: a 270 degree arc with its gap at the bottom, where the two step
//: buttons sit. Angles run clockwise from the top, so -135 is the minimum of
//: the range and +135 its maximum. In the 100x100 user space of the svg.
const DIAL = { cx: 50, cy: 50, r: 40, span: 135 };

/** Return the point on the arc at ``fraction`` of the range, 0 to 1. */
function dialPoint(fraction) {
  const angle = ((2 * DIAL.span * fraction - DIAL.span) * Math.PI) / 180;
  return [
    DIAL.cx + DIAL.r * Math.sin(angle),
    DIAL.cy - DIAL.r * Math.cos(angle),
  ];
}

/** Fill one reading inside the dial, and take its row out when there is none. */
function setReading(row, text) {
  row.style.display = text ? "" : "none";
  row.querySelector("span").textContent = text;
}

/** Return the ``d`` of the arc between two fractions of the range. */
function dialPath(from, to) {
  const [x1, y1] = dialPoint(from);
  const [x2, y2] = dialPoint(to);
  const large = (to - from) * 2 * DIAL.span > 180 ? 1 : 0;
  const fixed = (value) => value.toFixed(2);
  return `M ${fixed(x1)} ${fixed(y1)} A ${DIAL.r} ${DIAL.r} 0 ${large} 1 ${fixed(x2)} ${fixed(y2)}`;
}

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

/** What is left of a temporary profile: "4:59", or "1:05:09" from an hour. */
function formatRemaining(ms) {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, "0");
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${seconds}`;
  return `${minutes}:${seconds}`;
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
    this._error = null;
    this._errorTimer = null;
    //: The temporary profile counting down, and the timer that repaints it.
    this._running = null;
    this._countdownTimer = null;
  }

  disconnectedCallback() {
    // Started again by the next paint once the card is back on a view.
    clearInterval(this._countdownTimer);
    this._countdownTimer = null;
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
      profile_layout: "grid",
      temperature_style: "bar",
      show_protection: false,
      show_automatic: false,
      show_target: true,
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
    // ``null`` without a profile sensor. On means anything but off: waiting
    // for the sensor is on too, and it still decides.
    const automatic = attrs.automatic || null;
    const running =
      automatic && automatic.status === "temporary" && automatic.temporary
        ? automatic.temporary
        : null;

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
      automatic,
      autoOn: Boolean(automatic && automatic.status !== "off"),
      running,
      // Automatic mode holds a write protected profile: nothing on the card
      // may change it - the integration refuses it as well. Only temporary
      // profiles, automatic mode itself and the lock stay usable.
      frozen: Boolean(
        automatic &&
          automatic.status !== "off" &&
          (attrs.profiles || []).some(
            (profile) =>
              profile.id === (attrs.active_profile_id || CUSTOM_ID) && profile.protected
          )
      ),
      applying: Boolean(attrs.applying) || this._busy > 0,
      hvacMode: climate ? climate.state : null,
      hvacModes: caps.hvac_modes || [],
      fanModes: caps.fan_modes || [],
      swingModes: caps.swing_modes || [],
      fanMode: climate ? climate.attributes.fan_mode : null,
      swingMode: climate ? climate.attributes.swing_mode : null,
      target: this._value("temperature", climate?.attributes.temperature),
      current: climate ? climate.attributes.current_temperature : null,
      humidity: climate ? climate.attributes.current_humidity : null,
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

  /**
   * Whether the card offers ``profile`` to be picked. Custom is a status, not
   * a preset; a hidden profile is set elsewhere; and in automatic mode only a
   * temporary profile can be started - the rest is the sensor's to choose.
   */
  _pickable(model, profile) {
    if (profile.virtual || profile.hidden) return false;
    return !model.autoOn || Boolean(profile.temporary);
  }

  /**
   * Whether the active profile is one the card lists only while it is active:
   * custom, which is a status and not a preset, a profile hidden from the
   * card, or one automatic mode chose.
   */
  _shownWhileActive(model) {
    if (model.activeId === (model.custom.id || CUSTOM_ID)) return true;
    const active = model.profiles.find((profile) => profile.id === model.activeId);
    return Boolean(active && !this._pickable(model, active));
  }

  /* ---- rendering ---- */

  _update() {
    if (!this._config || !this._hass) return;
    const model = this._model();

    if (model.error) {
      this._renderFatal(model.error);
      return;
    }

    // Custom and a hidden profile are in the list only while they are what
    // the device is doing, so that coming and going changes what is built -
    // the active profile itself is only painted.
    const shownWhileActive = this._shownWhileActive(model) ? model.activeId : "";
    const signature = [
      model.profiles
        .map(
          (p) =>
            `${p.id}:${p.name}:${p.color}:${Boolean(p.hidden)}:${Boolean(p.temporary)}`
        )
        .join("|"),
      shownWhileActive,
      // Automatic mode changes what is offered, not only how it is painted.
      model.autoOn,
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
      this._config.temperature_style,
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

  /**
   * The temperature, in one of two shapes. The bar is the compact default; the
   * dial is what a thermostat card looks like, and keeps the two step buttons
   * in the gap of its arc - a finger dragged around a ring rarely lands on the
   * half degree somebody meant. Both drive the same code underneath.
   */
  _tempSection() {
    const minus = `<button class="step" data-step="down" type="button" aria-label="Cooler">
            <ha-icon icon="mdi:minus"></ha-icon>
          </button>`;
    const plus = `<button class="step" data-step="up" type="button" aria-label="Warmer">
            <ha-icon icon="mdi:plus"></ha-icon>
          </button>`;

    if (this._config.temperature_style !== "dial") {
      return `
        <section class="temp" hidden>
          ${minus}
          <div class="readout">
            <div class="value"><span class="degrees">–</span><span class="unit"></span></div>
            <div class="meter"><div class="meter-fill"></div></div>
            <div class="ambient"></div>
          </div>
          ${plus}
        </section>`;
    }

    return `
        <section class="temp dial" hidden>
          <div class="ring">
            <svg class="arc" viewBox="0 0 100 100" role="slider" tabindex="0">
              <path class="arc-track" d="${dialPath(0, 1)}"></path>
              <path class="arc-fill" d="${dialPath(0, 0)}"></path>
              <circle class="arc-current" r="1.7"></circle>
              <circle class="arc-handle" r="4.6"></circle>
            </svg>
            <div class="ring-center">
              <div class="ring-action"></div>
              <div class="value"><span class="degrees">–</span><span class="unit"></span></div>
              <div class="ring-reading ring-current">
                <ha-icon icon="mdi:thermometer"></ha-icon><span></span>
              </div>
              <div class="ring-reading ring-humidity">
                <ha-icon icon="mdi:water-percent"></ha-icon><span></span>
              </div>
            </div>
            <div class="ring-steps">${minus}${plus}</div>
          </div>
        </section>`;
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
          <div class="header-actions">
            <button class="auto" type="button" title="" hidden>
              <ha-icon icon="mdi:auto-mode"></ha-icon>
            </button>
            <button class="lock" type="button" title="" hidden>
              <ha-icon icon="mdi:lock-open-variant-outline"></ha-icon>
            </button>
            <button class="pill" type="button" title="">
              <span class="dot"></span><span class="pill-text"></span>
            </button>
          </div>
        </header>

        <section class="target" role="status" hidden>
          <ha-icon class="target-icon" icon="mdi:target"></ha-icon>
          <span class="target-label"></span>
          <span class="target-mark"></span>
          <span class="target-name"></span>
        </section>

        ${this._tempSection()}

        <section class="profiles" role="group"></section>

        <section class="unreached" role="status" hidden>
          <div class="notice-main">
            <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
            <div class="notice-text">
              <span class="notice-title unreached-title"></span>
              <span class="notice-values unreached-values"></span>
            </div>
          </div>
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
      lock: root.querySelector(".lock"),
      lockIcon: root.querySelector(".lock ha-icon"),
      auto: root.querySelector(".auto"),
      target: root.querySelector(".target"),
      targetLabel: root.querySelector(".target-label"),
      targetMark: root.querySelector(".target-mark"),
      targetName: root.querySelector(".target-name"),
      pillText: root.querySelector(".pill-text"),
      temp: root.querySelector(".temp"),
      degrees: root.querySelector(".degrees"),
      unit: root.querySelector(".unit"),
      meter: root.querySelector(".meter-fill"),
      ambient: root.querySelector(".ambient"),
      // Only one of the two temperature sections is built, so everything
      // below is null in the other one - every use is guarded.
      arc: root.querySelector(".arc"),
      arcFill: root.querySelector(".arc-fill"),
      arcHandle: root.querySelector(".arc-handle"),
      arcCurrent: root.querySelector(".arc-current"),
      ringAction: root.querySelector(".ring-action"),
      ringCurrent: root.querySelector(".ring-current"),
      ringHumidity: root.querySelector(".ring-humidity"),
      profiles: root.querySelector(".profiles"),
      controls: root.querySelector(".controls"),
      unreached: root.querySelector(".unreached"),
      unreachedTitle: root.querySelector(".unreached-title"),
      unreachedValues: root.querySelector(".unreached-values"),
    };

    root.querySelectorAll(".step").forEach((button) => {
      button.addEventListener("click", () =>
        this._nudgeTemperature(button.dataset.step === "up" ? 1 : -1)
      );
    });

    const arc = this._el.arc;
    if (arc) {
      const drag = (event) => {
        event.preventDefault();
        this._dialTo(event);
      };
      arc.addEventListener("pointerdown", (event) => {
        arc.setPointerCapture(event.pointerId);
        drag(event);
      });
      arc.addEventListener("pointermove", (event) => {
        if (arc.hasPointerCapture(event.pointerId)) drag(event);
      });
      // A ring that can only be dragged is a ring half the people cannot use.
      arc.addEventListener("keydown", (event) => {
        const by = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[
          event.key
        ];
        if (!by) return;
        event.preventDefault();
        this._nudgeTemperature(by);
      });
    }
    this._el.pill.addEventListener("click", () => this._togglePower());
    this._el.lock.addEventListener("click", () => this._toggleProtection());
    this._el.auto.addEventListener("click", () => this._toggleAutomatic());

    this._buildProfiles(model);
    this._buildControls(model);
  }

  _buildProfiles(model) {
    const wrap = this._el.profiles;
    wrap.innerHTML = "";
    wrap.setAttribute("aria-label", this._t("Profiles"));
    const layout = this._layout();
    wrap.dataset.layout = layout;

    const all = [...model.profiles, { ...model.custom, virtual: true }];
    this._profileButtons = new Map();
    this._openProfileList(false);
    this._profilePicker = null;

    if (layout === "dropdown") {
      this._buildProfileSelect(model, all);
      return;
    }

    const iconsOnly = layout === "icons";
    for (const profile of all) {
      const pickable = this._pickable(model, profile);
      const isActive = profile.id === model.activeId;
      // Custom has no icon of its own, and a row of icons has no room for a
      // dashed box that says nothing: it joins only while it is what is on.
      // In automatic mode it is no different from any other profile the
      // card does not offer.
      const always = profile.virtual && !iconsOnly && !model.autoOn;
      // What is not offered - hidden, or chosen by automatic mode - is still
      // there while it is on: the card does not pretend the device is doing
      // something else.
      if (!pickable && !isActive && !always) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = iconsOnly ? "profile icon-only" : "profile";
      button.dataset.id = profile.id;
      if (!pickable) button.classList.add("fixed");
      if (profile.virtual) button.classList.add("virtual");
      if (profile.hidden) button.classList.add("hidden-profile");
      else if (!profile.virtual && !pickable) button.classList.add("chosen");
      const [r, g, b] = hexToRgb(profile.color);
      button.style.setProperty("--profile-rgb", `${r}, ${g}, ${b}`);
      button.style.setProperty("--profile-color", profile.color);
      button.style.setProperty("--profile-contrast", contrastColor(profile.color));
      // The time a temporary profile has left goes under its name - or, with
      // no name to go under, next to or below the icon, as room allows. A
      // timer beside an icon would be two icons, so there it is the time only.
      const timer = iconsOnly ? "" : '<ha-icon icon="mdi:timer-outline"></ha-icon>';
      const countdown = profile.virtual
        ? ""
        : `<span class="profile-countdown" hidden>${timer}<span class="countdown-text"></span></span>`;
      button.innerHTML = iconsOnly
        ? `
        <span class="icon-stack">${profileMark(profile)}${countdown}</span>
        <span class="check" aria-hidden="true"><ha-icon icon="mdi:check"></ha-icon></span>`
        : `
        ${profileMark(profile)}
        <span class="profile-name"></span>
        ${countdown}
        <span class="check" aria-hidden="true"><ha-icon icon="mdi:check"></ha-icon></span>`;
      if (iconsOnly) {
        // The name is the label now - there is nothing else to go by, for a
        // pointer or for a screen reader.
        button.title = profile.name;
        button.setAttribute("aria-label", profile.name);
      } else {
        button.querySelector(".profile-name").textContent = profile.name;
      }
      if (profile.virtual) {
        button.disabled = true;
        if (!iconsOnly) {
          button.title = this._t(
            "Shown when the current state matches none of your profiles."
          );
        }
      } else if (profile.hidden) {
        button.disabled = true;
        if (!iconsOnly) button.title = this._t("Hidden on the card, set elsewhere.");
      } else if (!pickable) {
        button.disabled = true;
        if (!iconsOnly) button.title = this._t("Chosen by automatic mode.");
      } else {
        button.addEventListener("click", () => this._tapProfile(profile));
      }
      button.dataset.title = button.title;
      wrap.appendChild(button);
      this._profileButtons.set(profile.id, button);
    }
  }

  /**
   * The profiles as one dropdown instead of a wall of buttons - for a
   * dashboard where the card is one of many.
   *
   * Not a ``<select>``: a native list cannot draw an icon or a colour, and
   * those are how a profile is recognised at a glance. So it is a button and
   * a list of buttons, with the same marks the grid uses, and the keyboard
   * and screen reader behaviour spelled out by hand.
   */
  _buildProfileSelect(model, all) {
    const picker = document.createElement("div");
    picker.className = "picker";

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "picker-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-label", this._t("Profiles"));
    trigger.innerHTML = `
      <span class="picker-mark"></span>
      <span class="picker-name"></span>
      <span class="picker-countdown" hidden><ha-icon icon="mdi:timer-outline"></ha-icon><span class="countdown-text"></span></span>
      <ha-icon class="picker-arrow" icon="mdi:chevron-down"></ha-icon>`;

    const list = document.createElement("div");
    list.className = "picker-list";
    list.setAttribute("role", "listbox");
    list.hidden = true;

    const options = new Map();
    for (const profile of all) {
      // Custom is a status, not something to pick: it is in the list while it
      // is what the device is doing, and cannot be chosen. A hidden profile,
      // and one automatic mode chose, are treated the same way.
      const onlyWhileActive = !this._pickable(model, profile);
      if (onlyWhileActive && profile.id !== model.activeId) continue;
      const option = document.createElement("button");
      option.type = "button";
      option.className = "picker-option";
      option.setAttribute("role", "option");
      option.dataset.id = profile.id;
      if (profile.hidden) option.classList.add("hidden-profile");
      else if (onlyWhileActive && !profile.virtual) option.classList.add("chosen");
      option.style.setProperty("--profile-color", profile.color);
      option.innerHTML = `
        ${profileMark(profile)}
        <span class="picker-option-name"></span>
        <span class="check" aria-hidden="true"><ha-icon icon="mdi:check"></ha-icon></span>`;
      option.querySelector(".picker-option-name").textContent = profile.name;
      if (onlyWhileActive) {
        option.disabled = true;
      } else {
        option.addEventListener("click", () => {
          this._openProfileList(false);
          this._tapProfile(profile);
        });
      }
      list.appendChild(option);
      options.set(profile.id, option);
    }

    // While a temporary profile counts down, the closed list is that profile:
    // a tap ends it, as the button would in every other layout.
    trigger.addEventListener("click", () => {
      if (this._running) {
        this._endTemporary();
        return;
      }
      this._openProfileList(list.hidden);
    });
    picker.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !list.hidden) {
        event.stopPropagation();
        this._openProfileList(false);
        trigger.focus();
        return;
      }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      if (list.hidden) {
        this._openProfileList(true);
        return;
      }
      const usable = [...list.querySelectorAll(".picker-option:not(:disabled)")];
      const at = usable.indexOf(this.shadowRoot.activeElement);
      const step = event.key === "ArrowDown" ? 1 : -1;
      const next = at < 0 ? 0 : (at + step + usable.length) % usable.length;
      usable[next]?.focus();
    });

    picker.append(trigger, list);
    this._el.profiles.appendChild(picker);
    this._profilePicker = { trigger, list, options };
  }

  /** Open or close the profile list, and listen for the click that ends it. */
  _openProfileList(open) {
    const picker = this._profilePicker;
    if (!picker) return;
    picker.list.hidden = !open;
    picker.trigger.setAttribute("aria-expanded", open ? "true" : "false");

    if (this._closePicker) {
      window.removeEventListener("pointerdown", this._closePicker, true);
      this._closePicker = null;
    }
    if (!open) return;
    // A click anywhere else closes it - including on another card, which is
    // why this hangs off the window rather than off the card.
    this._closePicker = (event) => {
      if (event.composedPath().includes(picker.list)) return;
      if (event.composedPath().includes(picker.trigger)) return;
      this._openProfileList(false);
    };
    window.addEventListener("pointerdown", this._closePicker, true);
  }

  /**
   * The configured layout, grid when there is none. There used to be an
   * "auto" that picked grid or scroll by the number of profiles; automatic
   * mode changes that number, and the card jumped between layouts with it.
   */
  _layout() {
    const configured = this._config.profile_layout;
    if (["grid", "scroll", "dropdown", "icons"].includes(configured)) {
      return configured;
    }
    return "grid";
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
    el.card.classList.toggle("frozen", model.frozen);
    // What cannot be changed right now: the device is away, or automatic
    // mode holds a write protected profile.
    const locked = model.unavailable || model.frozen;
    const why = model.frozen
      ? this._t("Write protected, and held by automatic mode.")
      : "";
    el.temp.title = why;
    el.controls.title = why;
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
    el.pill.disabled = locked || !model.hvacModes.includes("off");

    // temperature
    const showTemp = this._visible("temperature", isNum(model.target));
    el.temp.hidden = !showTemp;
    if (showTemp) {
      el.degrees.textContent = formatNumber(model.target, model.caps.target_temp_step);
      el.unit.textContent = model.unit;
      const min = isNum(model.caps.min_temp) ? model.caps.min_temp : 16;
      const max = isNum(model.caps.max_temp) ? model.caps.max_temp : 30;
      const ratio = max > min ? clamp((model.target - min) / (max - min), 0, 1) : 0;
      if (el.meter) el.meter.style.width = `${(ratio * 100).toFixed(1)}%`;
      if (el.arc) this._paintDial(model, ratio, min, max);
      // What the device reports about the room. Each part only when there is
      // something to show: a device without a humidity sensor must not print
      // an empty "%". The bar puts them in one line, the dial in its middle.
      const current = isNum(model.current)
        ? `${formatNumber(model.current, 0.1)} ${model.unit}`
        : "";
      const humidity = isNum(model.humidity)
        ? `${formatNumber(model.humidity, 1)} %`
        : "";
      const action = model.action
        ? this._localize(
            `component.climate.entity_component._.state_attributes.hvac_action.state.${model.action}`,
            model.action
          )
        : "";
      if (el.ambient) {
        const ambient = [];
        if (current) ambient.push(`${this._t("Currently")} ${current}`);
        if (humidity) ambient.push(humidity);
        if (action) ambient.push(action);
        el.ambient.textContent = ambient.join(" · ");
      }
      if (el.ringAction) {
        el.ringAction.textContent = action;
        setReading(el.ringCurrent, current);
        setReading(el.ringHumidity, humidity);
      }
      this.shadowRoot.querySelectorAll(".step").forEach((button) => {
        button.disabled = locked;
      });
    }

    // profiles
    if (this._profilePicker) {
      const active =
        model.profiles.find((profile) => profile.id === model.activeId) ||
        model.custom;
      const { trigger, list, options } = this._profilePicker;
      trigger.querySelector(".picker-name").textContent = active.name;
      trigger.querySelector(".picker-mark").innerHTML = profileMark(active);
      trigger.style.setProperty("--profile-color", active.color);
      trigger.disabled = model.unavailable;
      if (model.unavailable) this._openProfileList(false);
      for (const [id, option] of options) {
        const isActive = id === model.activeId;
        option.classList.toggle("active", isActive);
        option.setAttribute("aria-selected", isActive ? "true" : "false");
      }
      list.setAttribute("aria-label", this._t("Profiles"));
    }
    for (const [id, button] of this._profileButtons) {
      const isActive = id === model.activeId;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
      if (!button.classList.contains("fixed")) button.disabled = model.unavailable;
    }

    // controls
    this._paintGroup("hvac_mode", model.hvacMode, locked);
    this._paintGroup("fan_mode", model.fanMode, locked || !on);
    this._paintGroup("swing_mode", model.swingMode, locked || !on);

    for (const value of model.additional) {
      const control = this._controls[value.id];
      if (!control) continue;
      const shown = this._value(value.id, value.value);
      if (control.kind === "slider") {
        const number = isNum(shown) ? shown : Number(control.input.min);
        if (document.activeElement !== control.input) control.input.value = number;
        control.input.disabled = locked;
        control.block.querySelector(".slider-value").textContent = formatNumber(
          Number(control.input.value),
          Number(control.input.step)
        );
        control.input.setAttribute("aria-valuetext", `${control.input.value}`);
        this._paintSliderFill(control.input);
      } else if (control.kind === "toggle") {
        this._paintToggle(value.id, shown, locked);
      } else {
        this._paintGroup(value.id, shown, locked);
      }
    }

    this._paintUnreached(model);
    this._paintProtection(model, activeProfile);
    this._paintAutomatic(model);
    this._paintTarget(model);
    this._paintCountdown(model);

    el.progress.classList.toggle("busy", Boolean(model.applying));
    el.card.setAttribute("aria-busy", model.applying ? "true" : "false");
  }

  /**
   * Says that a profile was applied but did not take, and which of its values
   * the device did not keep.
   *
   * Only a report, no button: the likely cause is two values of the profile
   * contradicting each other on the device, and only the user knows which of
   * the two was meant. Offering to write the result into the profile would be
   * the wrong answer half of the time.
   */
  _paintUnreached(model) {
    const el = this._el;
    const report = model.attrs.unreached;
    const show = Boolean(report) && !model.unavailable;
    el.unreached.hidden = !show;
    if (!show) return;

    el.unreachedTitle.textContent = `${report.profile} ${this._t("not reached")}`;
    el.unreachedValues.textContent = Object.entries(report.values || {})
      .map(([key, { wanted, actual }]) => {
        const label = CLIMATE_LABELS[key]
          ? this._t(CLIMATE_LABELS[key])
          : (model.additional.find((item) => item.id === key) || {}).name || key;
        const show = (value) => this._valueText(key, value);
        return `${label}: ${show(actual)} ${this._t("instead of")} ${show(wanted)}`;
      })
      .join(" · ");
  }

  /** A stored value the way the controls show it. */
  _valueText(key, value) {
    if (value === null || value === undefined) return "–";
    if (key === "hvac_mode") {
      return this._localize(`component.climate.entity_component._.state.${value}`, value);
    }
    if (key === "fan_mode" || key === "swing_mode") {
      return this._localize(
        `component.climate.entity_component._.state_attributes.${key}.state.${value}`,
        value
      );
    }
    if (value === "on" || value === "off") return this._t(value === "on" ? "On" : "Off");
    return typeof value === "number" ? String(value) : this._prettify(String(value));
  }

  /**
   * The write protection of the active profile, as a lock next to the power
   * button - only when the card asks for it, and only for a real profile:
   * custom has nothing to protect. The lock flips the profile's own switch,
   * so the card, the entity and the options cannot disagree.
   */
  _paintProtection(model, activeProfile) {
    const el = this._el;
    const entity = activeProfile.protection_entity;
    const show =
      Boolean(this._config.show_protection) &&
      !activeProfile.virtual &&
      activeProfile.id !== (model.custom.id || CUSTOM_ID) &&
      Boolean(entity);
    el.lock.hidden = !show;
    this._protection = show ? { entity, on: Boolean(activeProfile.protected) } : null;
    if (!show) return;

    const on = Boolean(activeProfile.protected);
    el.lock.classList.toggle("on", on);
    el.lock.setAttribute("aria-pressed", on ? "true" : "false");
    el.lock.setAttribute("aria-label", this._t("Write protection"));
    el.lock.title = `${activeProfile.name} ${
      on ? this._t("is write protected") : this._t("takes changes made by hand")
    }`;
    el.lockIcon.setAttribute(
      "icon",
      on ? "mdi:lock" : "mdi:lock-open-variant-outline"
    );
  }

  /**
   * Automatic mode, as a round button left of the lock - only when the card
   * asks for it and the device has a profile sensor. Filled while on, with a
   * warning dot while it waits for a profile it can follow. It flips the
   * device's own switch, so the card and an automation cannot disagree.
   */
  _paintAutomatic(model) {
    const el = this._el;
    const automatic = model.automatic;
    const show =
      Boolean(this._config.show_automatic) && Boolean(automatic && automatic.switch);
    el.auto.hidden = !show;
    if (!show) return;

    const on = automatic.status !== "off";
    const waiting = automatic.status === "waiting";
    el.auto.classList.toggle("on", on);
    el.auto.classList.toggle("waiting", waiting);
    el.auto.setAttribute("aria-pressed", on ? "true" : "false");
    el.auto.setAttribute("aria-label", this._t("Automatic mode"));
    el.auto.title = !on
      ? this._t("Automatic mode is off")
      : waiting
        ? this._t("Automatic mode is waiting for a profile")
        : this._t("Automatic mode is on");
  }

  /**
   * What the profile sensor names - also while automatic mode is off, and
   * while a temporary profile runs: it is what comes next. Without a profile
   * to name, the reason, in the warning colour.
   */
  _paintTarget(model) {
    const el = this._el;
    const automatic = model.automatic;
    const show = this._config.show_target !== false && Boolean(automatic);
    el.target.hidden = !show;
    if (!show) return;

    el.targetLabel.textContent = this._t("Target");
    const profile = automatic.target_id
      ? model.profiles.find((item) => item.id === automatic.target_id)
      : null;
    el.target.classList.toggle("problem", !profile);
    if (profile) {
      el.targetMark.innerHTML = profileMark(profile);
      el.targetMark.style.setProperty("--profile-color", profile.color);
      el.targetName.textContent = profile.name;
      return;
    }
    el.targetMark.innerHTML = "";
    el.targetName.textContent =
      automatic.problem === "unknown_profile"
        ? this._noProfile(automatic.sensor_state ?? "")
        : this._t("Sensor unavailable");
  }

  /** Count the running temporary profile down, once a second. */
  _paintCountdown(model) {
    this._running = model.running;
    const until = model.running ? Date.parse(model.running.until) : NaN;
    if (Number.isFinite(until)) {
      if (!this._countdownTimer) {
        this._countdownTimer = setInterval(() => this._tick(), 1000);
      }
    } else {
      clearInterval(this._countdownTimer);
      this._countdownTimer = null;
    }
    this._tick();
  }

  _tick() {
    const running = this._running;
    const until = running ? Date.parse(running.until) : NaN;
    const text = Number.isFinite(until) ? formatRemaining(until - Date.now()) : "";
    const end = this._t("Tap to end");

    for (const [id, button] of this._profileButtons || []) {
      const span = button.querySelector(".profile-countdown");
      if (!span) continue;
      const counting = Boolean(text) && id === running.profile_id;
      span.hidden = !counting;
      span.querySelector(".countdown-text").textContent = counting ? text : "";
      button.classList.toggle("counting", counting);
      button.title = counting ? `${text} · ${end}` : button.dataset.title || "";
    }

    const picker = this._profilePicker;
    if (picker) {
      const span = picker.trigger.querySelector(".picker-countdown");
      span.hidden = !text;
      span.querySelector(".countdown-text").textContent = text;
      picker.trigger.title = text ? `${text} · ${end}` : "";
      picker.trigger.setAttribute("aria-haspopup", text ? "false" : "listbox");
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

  /** Move the arc, its handle and the dot marking the room's temperature. */
  _paintDial(model, ratio, min, max) {
    const el = this._el;
    el.arcFill.setAttribute("d", dialPath(0, ratio));
    const [hx, hy] = dialPoint(ratio);
    el.arcHandle.setAttribute("cx", hx.toFixed(2));
    el.arcHandle.setAttribute("cy", hy.toFixed(2));

    const showsCurrent = isNum(model.current) && max > min;
    el.arcCurrent.style.display = showsCurrent ? "" : "none";
    if (showsCurrent) {
      const [cx, cy] = dialPoint(clamp((model.current - min) / (max - min), 0, 1));
      el.arcCurrent.setAttribute("cx", cx.toFixed(2));
      el.arcCurrent.setAttribute("cy", cy.toFixed(2));
    }

    el.arc.setAttribute("aria-valuemin", String(min));
    el.arc.setAttribute("aria-valuemax", String(max));
    el.arc.setAttribute("aria-valuenow", String(model.target));
    el.arc.setAttribute("aria-valuetext", `${model.target} ${model.unit}`);
    el.arc.setAttribute(
      "aria-disabled",
      model.unavailable || model.frozen ? "true" : "false"
    );
  }

  /* ---- actions ---- */

  /** Where on the ring the pointer is, as a temperature. */
  _dialTo(event) {
    const model = this._model();
    if (model.error || model.unavailable || model.frozen || !isNum(model.target)) {
      return;
    }

    const box = this._el.arc.getBoundingClientRect();
    const dx = event.clientX - (box.left + box.width / 2);
    const dy = event.clientY - (box.top + box.height / 2);
    // Clockwise from the top. The gap at the bottom is dead ground: a touch
    // there belongs to whichever end of the range it is nearer to.
    const degrees = clamp(
      (Math.atan2(dx, -dy) * 180) / Math.PI,
      -DIAL.span,
      DIAL.span
    );
    const fraction = (degrees + DIAL.span) / (2 * DIAL.span);

    const step = isNum(model.caps.target_temp_step) ? model.caps.target_temp_step : 0.5;
    const min = isNum(model.caps.min_temp) ? model.caps.min_temp : 5;
    const max = isNum(model.caps.max_temp) ? model.caps.max_temp : 35;
    const next = clamp(
      roundToStep(min + fraction * (max - min), step, min),
      min,
      max
    );
    if (next === model.target) return;
    this._commitTemperature(next);
  }

  _nudgeTemperature(direction) {
    const model = this._model();
    if (model.error || model.frozen || !isNum(model.target)) return;
    const step = isNum(model.caps.target_temp_step) ? model.caps.target_temp_step : 0.5;
    const min = isNum(model.caps.min_temp) ? model.caps.min_temp : 5;
    const max = isNum(model.caps.max_temp) ? model.caps.max_temp : 35;
    const next = clamp(
      roundToStep(model.target + direction * step, step, min),
      min,
      max
    );
    if (next === model.target) return;
    this._commitTemperature(next);
  }

  /** Show the new value at once and tell the device about it in a moment. */
  _commitTemperature(next) {
    this._setPending("temperature", next);
    this._update();

    // Coalesce rapid taps - and every step of a drag - into one service call.
    clearTimeout(this._tempTimer);
    this._tempTimer = setTimeout(() => this._setValue({ temperature: next }), 600);
  }

  _togglePower() {
    const model = this._model();
    if (model.error || model.frozen) return;
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

  /** Flip the active profile's write protection through its own switch. */
  async _toggleProtection() {
    const protection = this._protection;
    if (!protection) return;
    await this._callService("switch", protection.on ? "turn_off" : "turn_on", {
      entity_id: protection.entity,
    });
  }

  /** Flip automatic mode through the device's own switch. */
  async _toggleAutomatic() {
    const automatic = this._model().automatic;
    if (!automatic || !automatic.switch) return;
    await this._callService(
      "switch",
      automatic.status === "off" ? "turn_on" : "turn_off",
      { entity_id: automatic.switch }
    );
  }

  /** A tap on a profile: the running temporary one ends, any other starts. */
  async _tapProfile(profile) {
    if (this._running && this._running.profile_id === profile.id) {
      await this._endTemporary();
      return;
    }
    await this._applyProfile(profile);
  }

  async _endTemporary() {
    await this._call("end_temporary", {});
  }

  async _applyProfile(profile) {
    await this._call("apply_profile", { profile: profile.id });
  }

  async _setValue(values) {
    // Every control ends here; the disabled buttons are only what is seen.
    if (this._model().frozen) return;
    for (const [key, value] of Object.entries(values)) {
      this._setPending(key, value);
    }
    this._update();
    await this._call("set_value", values);
  }

  async _call(service, data) {
    await this._callService("climate_profiles", service, {
      entity_id: this._config.entity,
      ...data,
    });
  }

  async _callService(domain, service, data) {
    this._busy += 1;
    this._update();
    try {
      await this._hass.callService(domain, service, data);
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

  /** "No profile "X"" - the quotes are part of the language. */
  _noProfile(name) {
    const language = (this._hass && this._hass.language) || "en";
    return language.startsWith("de") ? `kein Profil „${name}“` : `No profile "${name}"`;
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

/**
 * The climate values this device actually has, read from the sensor's own
 * attributes - the same ones the card draws from, so the editor cannot offer
 * a switch for a control that never appears. A radiator thermostat has no fan
 * and no swing; the additional values were always read this way, these four
 * were not.
 */
function climateKeys(attrs, hass) {
  const caps = attrs.capabilities || {};
  const entities = attrs.entities || {};
  const climate =
    hass && entities.climate ? hass.states[entities.climate] : null;
  const keys = [];
  if (climate && isNum(climate.attributes.temperature)) keys.push("temperature");
  if ((caps.hvac_modes || []).length) keys.push("hvac_mode");
  if ((caps.fan_modes || []).length) keys.push("fan_mode");
  if ((caps.swing_modes || []).length) keys.push("swing_mode");
  return keys;
}

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
  "not reached": "nicht erreicht",
  "instead of": "statt",
  "Write protection": "Schreibschutz",
  "is write protected": "ist schreibgeschützt",
  "takes changes made by hand": "übernimmt Änderungen von Hand",
  Temperature: "Temperatur",
  "Shown when the current state matches none of your profiles.":
    "Wird angezeigt, wenn der aktuelle Zustand zu keinem Profil passt.",
  "Hidden on the card, set elsewhere.":
    "In der Karte ausgeblendet, wird anderswo gesetzt.",
  "Chosen by automatic mode.": "Von der Automatik gewählt.",
  "Automatic mode": "Automatik",
  "Automatic mode is off": "Automatik ist aus",
  "Automatic mode is on": "Automatik ist an",
  "Automatic mode is waiting for a profile": "Automatik wartet auf ein Profil",
  Target: "Ziel",
  "Sensor unavailable": "Sensor nicht verfügbar",
  "Tap to end": "Tippen beendet",
  "Write protected, and held by automatic mode.":
    "Schreibgeschützt, und von der Automatik gehalten.",
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
  /* Home Assistant's warning colour as RGB, for tinted backgrounds. */
  --cp-warning-rgb: 255, 166, 0;
  --cp-line: var(--divider-color, rgba(127, 127, 127, 0.25));
  /* The height of the buttons in the header: the power pill and the lock. */
  --cp-header-control: 31px;
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
  box-sizing: border-box;
  height: var(--cp-header-control);
  padding: 0 13px;
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
/* The active profile's write protection. Same outline and height as the
   power button beside it, filled in the profile's colour while the lock is
   closed. */
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}
.lock[hidden],
.auto[hidden] { display: none; }
.lock,
.auto {
  display: grid;
  place-items: center;
  box-sizing: border-box;
  width: var(--cp-header-control);
  height: var(--cp-header-control);
  flex: none;
  padding: 0;
  border: 1px solid var(--cp-line);
  border-radius: 50%;
  background: transparent;
  color: var(--cp-muted);
  cursor: pointer;
  transition: color 200ms ease, background 200ms ease, border-color 200ms ease;
}
.lock ha-icon,
.auto ha-icon { --mdc-icon-size: 16px; }
.lock.on,
.auto.on {
  color: var(--accent-color);
  border-color: rgba(var(--accent-rgb), 0.45);
  background: rgba(var(--accent-rgb), 0.12);
}
/* On, but nothing to follow: the dot says so without changing the button's
   meaning - automatic mode is still what decides. */
.auto { position: relative; }
.auto.waiting::after {
  content: "";
  position: absolute;
  top: -1px;
  right: -1px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: rgb(var(--cp-warning-rgb));
  box-shadow: 0 0 0 2px var(--cp-surface);
}

/* what the profile sensor names */
.target[hidden] { display: none; }
.target {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 8px 12px;
  border: 1px solid var(--cp-line);
  border-radius: 14px;
  font-size: 0.82rem;
  color: var(--cp-muted);
}
.target-icon { --mdc-icon-size: 16px; flex: none; }
.target-mark { display: flex; flex: none; align-items: center; }
.target-mark ha-icon { --mdc-icon-size: 16px; color: var(--profile-color); }
.target-mark .dot-mark {
  width: 10px;
  height: 10px;
  margin: 0;
  border-radius: 50%;
  background: var(--profile-color);
  box-shadow: none;
}
.target-name {
  min-width: 0;
  color: var(--cp-text);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.target.problem {
  border-color: rgba(var(--cp-warning-rgb), 0.55);
  background: rgba(var(--cp-warning-rgb), 0.08);
}

/* temperature */
.temp[hidden] { display: none; }
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

/* the dial */
.temp.dial { display: block; padding: 8px 4px 0; }
.ring {
  position: relative;
  width: min(268px, 86%);
  margin: 0 auto;
  aspect-ratio: 1 / 1;
  background: radial-gradient(
    circle at 50% 48%,
    rgba(var(--accent-rgb), 0.1),
    transparent 62%
  );
}
.arc {
  display: block;
  width: 100%;
  height: 100%;
  /* Without this the browser scrolls the dashboard instead of turning the
     dial - the one line that decides whether it works on a phone. */
  touch-action: none;
  cursor: pointer;
  outline: none;
}
.arc-track {
  fill: none;
  stroke: var(--cp-fill);
  stroke-width: 7;
  stroke-linecap: round;
}
.arc-fill {
  fill: none;
  stroke: var(--accent-color);
  stroke-width: 7;
  stroke-linecap: round;
  transition: stroke 260ms ease;
}
.arc-current { fill: var(--cp-muted); }
.arc-handle {
  fill: var(--cp-surface);
  stroke: var(--accent-color);
  stroke-width: 2.4;
}
.arc:focus-visible .arc-handle { stroke-width: 4; }
.ring-center {
  position: absolute;
  inset: 24% 20% 28%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  pointer-events: none;
  text-align: center;
}
.ring-center .value { font-size: 2.6rem; }
.ring-action {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--cp-muted);
  min-height: 1.1em;
}
.ring-reading {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.78rem;
  color: var(--cp-muted);
}
.ring-reading:first-of-type { margin-top: 6px; }
.ring-reading ha-icon { --mdc-icon-size: 15px; width: 15px; height: 15px; }
.ring-steps {
  position: absolute;
  left: 50%;
  bottom: 0;
  transform: translateX(-50%);
  display: flex;
  gap: 14px;
}
.dial .step { width: 46px; height: 46px; border-radius: 16px; }

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

/* the icons layout: one row, the name only as a label */
.profiles[data-layout="icons"] {
  grid-auto-flow: column;
  grid-auto-columns: 1fr;
  gap: 8px;
}
.profile.icon-only {
  min-height: 0;
  padding: 12px 6px;
  gap: 0;
}
.profile.icon-only ha-icon { --mdc-icon-size: 24px; }
/* No check mark in here: there is one icon in the button and the mark lands
   on top of it. The filled button is what says "this one is on" - and
   aria-pressed says it where no shape is seen at all. */
/* ".profile.active .check" comes later and is just as specific, so this has
   to out-weigh it rather than merely contradict it. */
.profile.icon-only.active .check,
.profile.icon-only .check { display: none; }
.profile.icon-only .dot-mark { width: 14px; height: 14px; margin: 5px 0; }
/* The time left sits below the icon, or beside it once the button is wide
   enough - measured on the button, not the screen. */
.icon-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
@container (min-width: 88px) {
  .icon-stack { flex-direction: row; gap: 6px; }
}

/* the dropdown layout */
.profiles[data-layout="dropdown"] { display: block; }
.picker { position: relative; }
.picker-trigger,
.picker-option {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  border: 1px solid transparent;
  border-radius: 14px;
  background: transparent;
  color: var(--cp-text);
  font: inherit;
  font-size: 0.95rem;
  text-align: left;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.picker-trigger {
  padding: 12px 12px 12px 14px;
  border-color: var(--cp-line);
  background: var(--cp-fill);
  font-weight: 500;
}
.picker-trigger .picker-name { flex: 1; min-width: 0; }
.picker-countdown[hidden] { display: none; }
.picker-countdown {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
  color: var(--profile-color, var(--accent-color));
  font-size: 0.95rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.picker-countdown ha-icon { --mdc-icon-size: 16px; }
.picker-arrow {
  --mdc-icon-size: 20px;
  color: var(--cp-muted);
  flex: none;
}
.picker-trigger[aria-expanded="true"] .picker-arrow { transform: rotate(180deg); }
.picker-trigger:disabled { opacity: 0.6; cursor: default; }
.picker-list[hidden] { display: none; }
/* In the flow, not floating above it: an overlay is at the mercy of whoever
   clips the card - a theme that hides ha-card's overflow, a view that crops
   it - and a list cut off at the card's edge is worse than one that pushes
   the rest down for as long as it is open. (No backticks in here: the whole
   stylesheet is one template literal.) */
.picker-list {
  display: grid;
  gap: 2px;
  max-height: 320px;
  margin-top: 6px;
  padding: 6px;
  overflow-y: auto;
  border: 1px solid var(--cp-line);
  border-radius: 16px;
  background: var(--cp-surface);
}
.picker-option { padding: 10px 10px 10px 12px; }
.picker-option .picker-option-name { flex: 1; min-width: 0; }
.picker-option:hover:not(:disabled) { background: rgba(var(--accent-rgb), 0.1); }
.picker-option.active { background: rgba(var(--accent-rgb), 0.14); font-weight: 600; }
.picker-option:disabled { color: var(--cp-muted); cursor: default; }
.picker-option .check { display: none; }
.picker-option.active .check {
  display: block;
  --mdc-icon-size: 18px;
  color: var(--profile-color, var(--accent-color));
}
.picker-trigger ha-icon,
.picker-option ha-icon {
  --mdc-icon-size: 20px;
  flex: none;
  color: var(--profile-color);
}
.picker-trigger .picker-arrow { color: var(--cp-muted); }
/* The mark sits in a span of its own, and an inline span gives a dot no box
   to be 12px in - the rows get theirs from being flex items. */
.picker-mark { display: flex; flex: none; align-items: center; }
/* The grid draws its dot with a halo around it; in a row of text that would
   only make the line taller. */
.picker-trigger .dot-mark,
.picker-option .dot-mark {
  width: 12px;
  height: 12px;
  flex: none;
  margin: 0;
  border-radius: 50%;
  background: var(--profile-color);
  box-shadow: none;
}
.picker-trigger:focus-visible,
.picker-option:focus-visible {
  outline: 2px solid var(--profile-color, var(--accent-color));
  outline-offset: -2px;
}

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
/* A hidden profile is disabled only so it cannot be picked here. It is a real
   profile the device is running, not a status like custom, so it is not
   faded the way every other disabled button is. */
.profile.hidden-profile,
.picker-option.hidden-profile:disabled {
  opacity: 1;
  color: var(--cp-text);
  cursor: default;
}
.profile.hidden-profile.active { color: var(--profile-contrast); }
/* Chosen by automatic mode: shown like a hidden profile, for the same reason. */
.profile.chosen,
.picker-option.chosen:disabled {
  opacity: 1;
  color: var(--cp-text);
  cursor: default;
}
.profile.chosen.active { color: var(--profile-contrast); }

/* the time a temporary profile has left */
.profile-countdown[hidden] { display: none; }
/* Every button measures itself, so the time left grows with the room it has:
   small in a row of six, as large as the name allows on a button of its own. */
.profile { container-type: inline-size; }
.profile-countdown {
  display: inline-flex;
  align-items: center;
  gap: 0.25em;
  font-size: clamp(0.85rem, 8cqi, 1.3rem);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.profile .profile-countdown ha-icon { --mdc-icon-size: 1.05em; color: inherit; }

/* notices */
/* A flex container, and "display" beats the "hidden" attribute. */
.unreached[hidden] { display: none; }

/* A report that something did not happen, in the warning colour. */
.unreached {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid rgba(var(--cp-warning-rgb), 0.55);
  border-radius: 14px;
  background: rgba(var(--cp-warning-rgb), 0.08);
}
.notice-main {
  display: flex;
  align-items: center;
  gap: 9px;
  flex: 1 1 140px;
  min-width: 0;
}
.notice-main > ha-icon {
  --mdc-icon-size: 18px;
  color: var(--warning-color, #ffa600);
  flex: none;
}
.notice-text { display: grid; min-width: 0; }
.notice-title {
  font-size: 0.8rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
}
.notice-values {
  font-size: 0.74rem;
  color: var(--cp-muted);
  overflow: hidden;
  text-overflow: ellipsis;
}

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
.slider:disabled { opacity: 0.45; cursor: not-allowed; }
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
    const climate = climateKeys(attrs, this._hass).map((key) => [
      key,
      CLIMATE_LABELS[key],
    ]);
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
    // On unless switched off - the form has to show what the card does.
    data.show_target = this._config.show_target !== false;
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
        const offered = this._values().map(([key]) => key);
        // What is not on offer keeps whatever was decided about it. An entity
        // that is away for a moment takes its switch with it, and editing the
        // name must not quietly unhide the value along with it.
        const hide = (Array.isArray(this._config.hide) ? this._config.hide : [])
          .filter((key) => !offered.includes(key));
        for (const key of offered) {
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
    name: "temperature_style",
    selector: {
      select: {
        mode: "dropdown",
        options: [
          { value: "bar", label: "Bar" },
          { value: "dial", label: "Dial" },
        ],
      },
    },
  },
  {
    name: "profile_layout",
    selector: {
      select: {
        mode: "dropdown",
        options: [
          { value: "grid", label: "Grid" },
          { value: "dropdown", label: "Dropdown" },
          { value: "icons", label: "Icons only" },
          { value: "scroll", label: "Scroll" },
        ],
      },
    },
  },
  { name: "show_protection", selector: { boolean: {} } },
  { name: "show_automatic", selector: { boolean: {} } },
  { name: "show_target", selector: { boolean: {} } },
];

const EDITOR_LABELS = {
  entity: "Climate profile sensor",
  name: "Name (optional)",
  profile_layout: "Profile layout",
  temperature_style: "Temperature control",
  show_protection: "Show the write protection of the active profile",
  show_automatic: "Show the automatic mode switch",
  show_target: "Show the profile automatic mode is aiming for",
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
