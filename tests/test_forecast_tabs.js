const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");

function getChartRenderer(name, nextFunction) {
    const helperStart = html.indexOf("        function addChartPointDetails(");
    const start = html.indexOf(`        function ${name}(`);
    const end = html.indexOf(`        function ${nextFunction}(`, start);
    assert.ok(helperStart >= 0 && start > helperStart && end > start);
    const element = tag => ({
        tag, children: [], attributes: {}, listeners: {},
        setAttribute(name, value) { this.attributes[name] = value; },
        append(...children) { this.children.push(...children); },
        addEventListener(name, callback) { this.listeners[name] = callback; },
    });
    const context = {
        Date, String, Number, Math, Array,
        document: {
            createElement: element,
            createElementNS: (_ns, tag) => element(tag),
            createTextNode: text => ({ textContent: text }),
        },
        formatWaveDirection: value => String(value),
    };
    vm.runInNewContext(html.slice(helperStart, html.indexOf(
        "        function renderWaveChart(", helperStart
    )) + html.slice(start, end), context);
    return context[name];
}

test("AI thinking indicator is shown only while loading and respects reduced motion", () => {
    const noticeStart = html.indexOf("        function showAiAvailabilityNotice(");
    const noticeEnd = html.indexOf("        function clearForecastAfterSignOut(", noticeStart);
    const stopStart = html.indexOf("        function stopEvaluationProgress(");
    const stopEnd = html.indexOf("        async function loadEvaluation(", stopStart);
    const progressStart = html.indexOf("        function createEvaluationProgressMessage(");
    const progressEnd = html.indexOf("        // Initialize application", progressStart);
    assert.ok(noticeStart >= 0 && noticeEnd > noticeStart && stopEnd > stopStart && progressEnd > progressStart);

    const timers = [];
    const cleared = [];
    const media = { matches: false };
    const element = tag => ({
        tag, children: [], attributes: {}, dataset: {},
        setAttribute(name, value) { this.attributes[name] = value; },
        append(...children) { this.children.push(...children); },
    });
    const evaluation = { replaceChildren(...children) { this.children = children; } };
    const context = {
        document: { createElement: element, createTextNode: text => ({ textContent: text }) },
        evaluation, signedInUser: { id: "subscriber" }, evaluationProgressTimer: null,
        window: { matchMedia: () => media },
        setInterval(callback) { timers.push(callback); return timers.length; },
        clearInterval(id) { cleared.push(id); },
    };
    vm.runInNewContext(
        html.slice(noticeStart, noticeEnd) + html.slice(stopStart, stopEnd) +
            html.slice(progressStart, progressEnd),
        context,
    );

    context.showAiAvailabilityNotice();
    assert.equal(evaluation.children[1].textContent,
        "Get fishing conditions to receive an AI recommendation.");
    assert.equal(timers.length, 0);
    context.showAiAvailabilityNotice(true);
    const message = evaluation.children[1];
    assert.equal(message.attributes.role, "status");
    assert.equal(message.children[0].className, "evaluation-spinner");
    assert.equal(message.children[0].attributes["aria-hidden"], "true");
    assert.equal(message.children[1].children[0].textContent, "Your AI response may take some time");
    assert.equal(timers.length, 1);
    context.createEvaluationProgressMessage();
    assert.deepEqual(cleared, [1]);
    context.stopEvaluationProgress();
    assert.deepEqual(cleared, [1, 2]);
    media.matches = true;
    context.createEvaluationProgressMessage();
    assert.equal(timers.length, 2);
    context.signedInUser = null;
    context.showAiAvailabilityNotice(true);
    assert.match(evaluation.children[1].textContent, /active subscribers/);
});

test("sign-in during forecast loading keeps the AI thinking indicator active", () => {
    const start = html.indexOf('        window.addEventListener("fishintime:auth-state-changed"');
    const end = html.indexOf("        function saveForecastState(", start);
    assert.ok(start >= 0 && end > start);
    let onAuthChange;
    const calls = [];
    const context = {
        window: { addEventListener(_name, listener) { onAuthChange = listener; } },
        signedInUser: null,
        forecastResult: { childElementCount: 0 },
        forecastSubmit: { disabled: true },
        showAiAvailabilityNotice: loading => calls.push(loading),
    };
    vm.runInNewContext(html.slice(start, end), context);
    onAuthChange({ detail: { account: { id: "subscriber" } } });
    assert.deepEqual(calls, [true]);
    context.forecastSubmit.disabled = false;
    onAuthChange({ detail: { account: { id: "subscriber" } } });
    assert.deepEqual(calls, [true, false]);
});

function getEvaluationRunner(responses) {
    const start = html.indexOf("        function showEvaluationError(");
    const end = html.indexOf("        function appendMarkdownInline(", start);
    assert.ok(start >= 0 && end > start);
    const element = tag => ({
        tag, children: [],
        replaceChildren(...children) { this.children = children; },
        remove() { evaluation.children = evaluation.children.filter(child => child !== this); },
    });
    const progress = { className: "evaluation-progress", remove() {
        evaluation.children = evaluation.children.filter(child => child !== this);
    } };
    const evaluation = {
        children: [element("h3"), progress],
        replaceChildren(...children) { this.children = children; },
        insertBefore(child, reference) {
            const index = this.children.indexOf(reference);
            this.children.splice(index < 0 ? this.children.length : index, 0, child);
        },
        querySelector(selector) {
            return selector === ".evaluation-progress"
                ? this.children.find(child => child.className === "evaluation-progress") || null
                : null;
        },
        append(child) { this.children.push(child); },
    };
    const rendered = [];
    const saved = [];
    const encoder = new TextEncoder();
    const context = {
        document: { createElement: element },
        evaluation, activeEvaluationRequest: 1, evaluationStreamController: null,
        AbortController, TextDecoder,
        fetch: async () => ({
            ok: true,
            body: { getReader: () => ({
                async read() {
                    if (!responses.length) return { done: true };
                    return { done: false, value: encoder.encode(`data: ${JSON.stringify(responses.shift())}\n\n`) };
                },
                async cancel() {},
                releaseLock() {},
            }) },
        }),
        apiUrl: value => value,
        authorizationHeaders: () => ({}),
        stopEvaluationProgress() {},
        saveCompletedEvaluation: value => saved.push(value),
        renderMarkdown: value => { rendered.push(value); return { textContent: value }; },
        createEvaluationHeading: () => ({ textContent: "Overall Recommendation — November 20, 2026" }),
    };
    vm.runInNewContext(html.slice(start, end), context);
    return { context, evaluation, rendered, saved };
}

test("AI evaluation displays partial text before saving the final answer", async () => {
    const { context, evaluation, rendered, saved } = getEvaluationRunner([
        { status: "pending", ai_evaluation: "Fish" },
        { status: "pending", ai_evaluation: "Fish at dawn" },
        { status: "completed", ai_evaluation: "Fish at dawn." },
    ]);
    await context.loadEvaluation("job", 1);
    assert.deepEqual(rendered, ["Fish", "Fish at dawn", "Fish at dawn."]);
    assert.deepEqual(saved, ["Fish at dawn."]);
    assert.equal(evaluation.children[0].textContent, "Overall Recommendation — November 20, 2026");
    assert.equal(evaluation.children[1].textContent, "Fish at dawn.");
    assert.equal(evaluation.children.length, 2);
});

test("AI evaluation preserves partial text and displays a failure", async () => {
    const { context, evaluation, rendered, saved } = getEvaluationRunner([
        { status: "pending", ai_evaluation: "Fish" },
        { status: "failed", ai_evaluation: "Fish at", error: "Evaluation interrupted." },
    ]);
    await context.loadEvaluation("job", 1);
    assert.deepEqual(rendered, ["Fish", "Fish at"]);
    assert.deepEqual(saved, []);
    assert.equal(evaluation.children[1].children[0].textContent, "Fish at");
    assert.equal(evaluation.children[2].textContent, "Evaluation interrupted.");
});

test("a superseded AI evaluation cannot display its partial response", async () => {
    const { context, rendered } = getEvaluationRunner([]);
    context.fetch = async () => {
        context.activeEvaluationRequest = 2;
        return { ok: true, body: { getReader: () => ({
            async read() { return { done: false, value: new TextEncoder().encode(
                'data: {"status":"pending","ai_evaluation":"Old"}\n\n'
            ) }; },
            async cancel() {},
        }) } };
    };
    await context.loadEvaluation("old-job", 1);
    assert.deepEqual(rendered, []);
});

test("AI activity streams while waiting and is replaced by answer text", async () => {
    const { context, evaluation, rendered } = getEvaluationRunner([
        { status: "pending", activity: "Checking tides" },
        { status: "pending", activity: "Checking tides and wind" },
        { status: "pending", ai_evaluation: "Fish", activity: null },
        { status: "completed", ai_evaluation: "Fish at dawn." },
    ]);
    await context.loadEvaluation("job", 1);
    assert.deepEqual(rendered, ["Checking tides", "Checking tides and wind", "Fish", "Fish at dawn."]);
    assert.equal(evaluation.children.length, 2);
    assert.equal(evaluation.children[1].textContent, "Fish at dawn.");
});

test("cancelling an evaluation closes its active stream", async () => {
    const { context } = getEvaluationRunner([]);
    let aborted = false;
    context.fetch = (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
            aborted = true;
            reject(new Error("aborted"));
        });
    });
    const request = context.loadEvaluation("job", 1);
    context.cancelEvaluationStream();
    await assert.rejects(request, /aborted/);
    assert.equal(aborted, true);
});

test("AI stream handles split UTF-8 events and reports interrupted streams", async () => {
    const { context, rendered, evaluation } = getEvaluationRunner([]);
    const bytes = new TextEncoder().encode('data: {"status":"pending","ai_evaluation":"Café"}\n\n');
    const accent = bytes.indexOf(0xc3);
    const chunks = [bytes.slice(0, accent + 1), bytes.slice(accent + 1)];
    context.fetch = async () => ({
        ok: true, body: { getReader: () => ({
            async read() {
                return chunks.length ? { done: false, value: chunks.shift() } : { done: true };
            },
            async cancel() {},
        }) },
    });
    await assert.rejects(context.loadEvaluation("job", 1), /ended unexpectedly/);
    assert.deepEqual(rendered, ["Café"]);
    assert.equal(evaluation.children[1].children[0].textContent, "Café");
});

function getTabFunctions(today) {
    const start = html.indexOf("        function forecastTabDates(");
    const end = html.indexOf("        function renderNearshoreForecast(", start);
    assert.ok(start >= 0 && end > start);
    const calls = [];
    const tabs = {
        children: [], scrollLeft: 0, clientWidth: 200,
        replaceChildren(...children) { this.children = children; },
    };
    const result = {
        setAttribute(name, value) { this[name] = value; },
        getAttribute(name) { return this[name]; },
        replaceChildren(value) { this.displayed = value; },
    };
    const context = {
        Date, Array, String,
        document: {
            createElement() {
                return {
                    attributes: {}, offsetLeft: 0, offsetWidth: 54,
                    listeners: {},
                    setAttribute(name, value) { this.attributes[name] = value; },
                    addEventListener(name, callback) { this.listeners[name] = callback; },
                    focus() { this.focused = true; },
                };
            },
        },
        forecastTabs: tabs,
        forecastResult: result,
        dateSelect: { value: "" },
        currentForecastSelection: { state: "FL", city: "Station", anchorDate: "2026-11-09" },
        currentForecastResult: { date: "original", daily_forecasts: [] },
        renderForecastTable: value => value,
        sessionStorage: { getItem() { return null; } },
        forecastStorageKey: "forecast",
        saveForecastState() {},
        showRecommendationDateNotice() {},
        console,
        loadForecast: (...args) => calls.push(args),
    };
    vm.runInNewContext(html.slice(start, end), context);
    return Object.assign(context, { tabs, result, calls, today });
}

test("recommendation notice opt-out lasts only for the browser session", () => {
    const start = html.indexOf("        function formatRecommendationDate(");
    const end = html.indexOf("        function showAiAvailabilityNotice(", start);
    assert.ok(start >= 0 && end > start);
    const stored = new Map();
    const dialog = {
        opens: 0,
        addEventListener(_name, listener) { this.onClose = listener; },
        showModal() { this.opens++; },
    };
    const message = {};
    const checkbox = { checked: false };
    const context = {
        Date, document: { createElement: () => ({}) }, console,
        currentEvaluationDate: "2026-11-20",
        recommendationDateDialog: dialog, recommendationDateMessage: message,
        hideRecommendationDateNotice: checkbox, hideRecommendationDateNoticeKey: "hide",
        sessionStorage: {
            getItem: key => stored.get(key),
            setItem: (key, value) => stored.set(key, value),
        },
    };
    vm.runInNewContext(html.slice(start, end), context);
    assert.equal(context.createEvaluationHeading().textContent,
        "Overall Recommendation — November 20, 2026");
    context.showRecommendationDateNotice("2026-11-20");
    assert.equal(dialog.opens, 0);
    context.showRecommendationDateNotice("2026-11-21");
    assert.equal(dialog.opens, 1);
    assert.equal(message.textContent, "Forecast shown: November 21, 2026. " +
        "This recommendation is still for November 20, 2026. " +
        "Click Get Fishing Conditions to generate one for November 21, 2026.");
    dialog.onClose();
    context.showRecommendationDateNotice("2026-11-22");
    assert.equal(dialog.opens, 2);
    checkbox.checked = true;
    dialog.onClose();
    context.showRecommendationDateNotice("2026-11-23");
    assert.equal(dialog.opens, 2);
    assert.equal(stored.get("hide"), "true");
    stored.clear();
    context.showRecommendationDateNotice("2026-11-24");
    assert.equal(dialog.opens, 3);
    context.currentEvaluationDate = null;
    context.showRecommendationDateNotice("2026-11-25");
    assert.equal(dialog.opens, 3);
});

test("sign-in and sign-out reset the recommendation notice preference", async () => {
    const client = fs.readFileSync(path.join(__dirname, "../billing/client.js"), "utf8");
    const startLogin = client.indexOf("  async function exchangeAuthorizationCode(");
    const endLogin = client.indexOf("  async function beginSignIn(", startLogin);
    const startLogout = client.indexOf("  async function signOut(");
    const endLogout = client.indexOf("  async function loadAccount(", startLogout);
    assert.ok(startLogin >= 0 && endLogin > startLogin && startLogout >= 0 && endLogout > startLogout);
    const key = "fishintime_hide_recommendation_date_notice";
    const stored = new Map([[key, "true"]]);
    const context = {
        URL, URLSearchParams,
        config: { login_domain: "https://example.test", client_id: "client",
            redirect_uri: "https://example.test/callback", logout_uri: "https://example.test/" },
        getOAuthValue: name => name === "state" ? "state-value" : "verifier",
        stateStorageKey: "state", verifierStorageKey: "verifier",
        oauthStateRetryStorageKey: "retry", pendingPlanStorageKey: "plan",
        tokenStorageKey: "token", clearOAuthValues() {}, clearAccessToken() {},
        sessionStorage: { getItem: name => stored.get(name), removeItem: name => stored.delete(name),
            setItem: (name, value) => stored.set(name, value) },
        localStorage: { setItem() {} },
        fetch: async () => ({ ok: true, json: async () => ({ access_token: "token" }) }),
        history: { replaceState() {} },
        CustomEvent: class {},
        window: { location: { pathname: "/callback", assign() {}, replace() {} }, dispatchEvent() {} },
    };
    vm.runInNewContext(client.slice(startLogin, endLogin) + client.slice(startLogout, endLogout), context);
    await context.exchangeAuthorizationCode("code", "state-value");
    assert.equal(stored.has(key), false);
    stored.set(key, "true");
    await context.signOut();
    assert.equal(stored.has(key), false);
});

test("authentication changes in another tab reset the notice preference", () => {
    const start = html.indexOf('        window.addEventListener("storage"');
    const end = html.indexOf('        window.addEventListener("fishintime:auth-state-changed"', start);
    assert.ok(start >= 0 && end > start);
    let onStorage;
    const removed = [];
    vm.runInNewContext(html.slice(start, end), {
        window: { addEventListener(_name, listener) { onStorage = listener; } },
        sessionStorage: { removeItem: key => removed.push(key) },
        hideRecommendationDateNoticeKey: "notice",
    });
    onStorage({ key: "unrelated", oldValue: "a", newValue: "b" });
    onStorage({ key: "fishintime_access_token", oldValue: "a", newValue: "a" });
    assert.deepEqual(removed, []);
    onStorage({ key: "fishintime_access_token", oldValue: "a", newValue: null });
    assert.deepEqual(removed, ["notice"]);
});

test("tab changes show the notice only when the displayed date changes", () => {
    const runner = getTabFunctions();
    const notices = [];
    runner.showRecommendationDateNotice = date => notices.push(date);
    runner.renderForecastTabs("2026-11-20", "2026-11-20", "2026-11-20");
    runner.selectForecastDate("2026-11-20");
    runner.dateSelect.value = "2026-11-21";
    runner.selectForecastDate("2026-11-21");
    assert.deepEqual(notices, ["2026-11-21"]);
});

test("restoring a forecast keeps the evaluation date separate from the selected tab", async () => {
    const start = html.indexOf("        async function restoreForecastState(");
    const end = html.indexOf("        async function loadStations(", start);
    assert.ok(start >= 0 && end > start);
    const savedState = {
        state: "FL", city: "Station", date: "2026-11-21",
        result: { date: "2026-11-20", evaluation_id: "job" },
        aiEvaluation: "Fish at dawn.",
    };
    const evaluation = { replaceChildren(...children) { this.children = children; } };
    const context = {
        sessionStorage: { getItem: () => JSON.stringify(savedState) },
        forecastStorageKey: "forecast", stateSelect: {}, dateSelect: {}, evaluation,
        loadStations: async () => {}, renderForecastTabs() {}, renderForecastForDate() {},
        renderMarkdown: text => ({ textContent: text }),
        createEvaluationHeading: () => ({ textContent: context.currentEvaluationDate }),
        console,
    };
    vm.runInNewContext(html.slice(start, end), context);
    await context.restoreForecastState(["FL"]);
    assert.equal(context.currentEvaluationDate, "2026-11-20");
    assert.equal(context.dateSelect.value, "2026-11-21");
    assert.equal(evaluation.children[0].textContent, "2026-11-20");

    savedState.evaluationDate = "2026-11-19";
    savedState.aiEvaluation = null;
    context.activeEvaluationRequest = 0;
    context.createEvaluationProgressMessage = () => ({});
    context.loadEvaluation = async () => {};
    await context.restoreForecastState(["FL"]);
    assert.equal(context.currentEvaluationDate, "2026-11-19");
    assert.equal(evaluation.children[0].textContent, "2026-11-19");
});

test("tab dates use the first position for a date less than three days away", () => {
    const { forecastTabDates } = getTabFunctions();
    const today = new Date(2026, 10, 7, 12);
    assert.deepEqual(Array.from(forecastTabDates("2026-11-09", today)), [
        "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12",
        "2026-11-13", "2026-11-14", "2026-11-15",
    ]);
});

test("tab dates center the selected date at exactly three or more days away", () => {
    const { forecastTabDates } = getTabFunctions();
    const today = new Date(2026, 10, 7, 12);
    assert.deepEqual(Array.from(forecastTabDates("2026-11-14", today)), [
        "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14",
        "2026-11-15", "2026-11-16", "2026-11-17",
    ]);
    assert.equal(forecastTabDates("2026-11-10", today)[3], "2026-11-10");
    assert.deepEqual(Array.from(forecastTabDates("2027-01-01", today)).slice(0, 4), [
        "2026-12-29", "2026-12-30", "2026-12-31", "2027-01-01",
    ]);
});

test("tab labels include weekdays and calendar days across month and year boundaries", () => {
    const { renderForecastTabs, tabs } = getTabFunctions();
    renderForecastTabs("2026-11-20", "2026-11-20", "2026-11-20");
    assert.deepEqual(tabs.children.map(button => button.textContent), [
        "F-20", "S-21", "S-22", "M-23", "T-24", "W-25", "Th-26",
    ]);
    assert.equal(tabs.children[0].attributes["aria-label"], "Friday, November 20, 2026");

    renderForecastTabs("2026-12-29", "2027-01-01", "2026-12-29");
    assert.deepEqual(tabs.children.map(button => button.textContent), [
        "T-29", "W-30", "Th-31", "F-1", "S-2", "S-3", "M-4",
    ]);
    tabs.children[3].offsetLeft = 180;
    tabs.children[3].offsetWidth = 54;
    tabs.children[3].listeners.click();
    assert.equal(tabs.scrollLeft, 34);
});

test("tabs render cached daily data without fetching and retain the original week", () => {
    const { renderForecastTabs, tabs, result, calls, dateSelect, currentForecastResult } = getTabFunctions();
    const date = new Date();
    date.setDate(date.getDate() + 1);
    const selected = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"),
        String(date.getDate()).padStart(2, "0")].join("-");

    renderForecastTabs(selected, selected);
    const originalDates = tabs.children.map(button => button.id);
    const nextDate = originalDates[1].slice("forecast-tab-".length);
    currentForecastResult.daily_forecasts.push(
        { date: selected, temp: 80, moon_current_phase: "Full Moon" },
        { date: nextDate, temp: 74, moon_current_phase: "Waning Gibbous" },
    );
    currentForecastResult.water_temperature = {
        temperature_f: 76.2, observed_at: "2026-11-20T08:54:00-05:00",
    };
    assert.equal(tabs.children.length, 7);
    assert.equal(tabs.children[0].attributes["aria-selected"], "true");
    assert.equal(tabs.children[0].tabIndex, 0);
    tabs.children[1].listeners.click();

    assert.equal(dateSelect.value, nextDate);
    assert.equal(tabs.children[0].attributes["aria-selected"], "false");
    assert.equal(tabs.children[1].attributes["aria-selected"], "true");
    assert.equal(result["aria-labelledby"], originalDates[1]);
    assert.equal(calls.length, 0);
    assert.equal(result.displayed.date, nextDate);
    assert.equal(result.displayed.temp, 74);
    assert.equal(result.displayed.moon_current_phase, "Waning Gibbous");
    assert.equal(result.displayed.water_temperature.temperature_f, 76.2);
    assert.deepEqual(tabs.children.map(button => button.id), originalDates);
    tabs.children[1].listeners.keydown({ key: "ArrowRight", preventDefault() {} });
    assert.equal(tabs.children[2].focused, true);
});

test("future-day tabs retain the current pressure observation instead of daily unavailability", () => {
    const { renderForecastForDate, currentForecastResult, result } = getTabFunctions();
    const observation = {
        current_pressure_inhg: 29.86,
        observed_at: "2026-11-20T16:06:00-05:00",
    };
    currentForecastResult.date = "2026-11-21";
    currentForecastResult.pressure = observation;
    currentForecastResult.daily_forecasts = [
        { date: "2026-11-21", pressure: { error: "No pressure observation for this date." } },
        { date: "2026-11-22", pressure: { error: "No pressure observation for this date." } },
    ];

    renderForecastForDate("2026-11-21");
    assert.equal(result.displayed.pressure, observation);
    renderForecastForDate("2026-11-22");
    assert.equal(result.displayed.pressure, observation);
    assert.equal(result.displayed.date, "2026-11-22");

    currentForecastResult.pressure = null;
    renderForecastForDate("2026-11-22");
    assert.equal(result.displayed.pressure.error, "No pressure observation for this date.");
});

test("a late response cannot replace the forecast for a newer tab", async () => {
    const start = html.indexOf("        async function loadForecast(");
    const end = html.indexOf('        forecastForm.addEventListener("submit"', start);
    assert.ok(start >= 0 && end > start);
    const pending = [];
    const displayed = [];
    const saved = [];
    const context = {
        stopEvaluationProgress() {},
        cancelEvaluationStream() {},
        showAiAvailabilityNotice() {},
        forecastSubmit: { disabled: false },
        forecastResult: { replaceChildren(value) { displayed.push(value); } },
        evaluation: {},
        activeEvaluationRequest: 0,
        URLSearchParams,
        apiUrl: value => value,
        authorizationHeaders: () => ({}),
        fetch: () => new Promise(resolve => pending.push(resolve)),
        saveForecastState: state => saved.push(state),
        renderForecastForDate: date => displayed.push(date),
        console,
    };
    vm.runInNewContext(html.slice(start, end), context);
    const selection = { city: "Station", state: "FL", station_id: "1" };
    const first = context.loadForecast(selection, "2026-11-09");
    const second = context.loadForecast(selection, "2026-11-10");
    pending[1]({ ok: true, json: async () => ({ date: "2026-11-10" }) });
    await second;
    pending[0]({ ok: true, json: async () => ({ date: "2026-11-09" }) });
    await first;

    assert.deepEqual(displayed, ["2026-11-10"]);
    assert.equal(saved.length, 1);
    assert.equal(saved[0].date, "2026-11-10");
    assert.equal(context.forecastSubmit.disabled, false);
});

test("nearshore chart includes independent swell intervals and clips them to the selected day", () => {
    const start = html.indexOf("        function renderNearshoreForecast(");
    const end = html.indexOf("        function renderForecastTable(", start);
    let rows;
    let swells;
    const render = vm.runInNewContext(`(${html.slice(start, end).trim()})`, {
        Intl, Date, String, Number,
        document: {
            createElement() {
                return { children: [], append(value) { this.children.push(value); },
                    set textContent(value) { this.text = value; } };
            },
        },
        renderWaveChart: (value, _date, series) => { rows = value; swells = series; return {}; },
    });
    const chart = render({
        grid: { office: "MFL", x: 1, y: 1, distance_km: 1, inferred: false },
        timezone: "America/New_York",
        wave_height: { values: [
            { valid_start: "2026-11-09T23:00:00Z", duration: "PT12H", value: 3 },
        ] },
        wave_period: { values: [
            { valid_start: "2026-11-09T22:00:00Z", duration: "PT12H", value: 7 },
        ] },
        wave_direction: { values: [] },
        primary_swell_height: { values: [
            { valid_start: "2026-11-09T22:00:00Z", duration: "PT24H", value: 1.5 },
        ] },
        primary_swell_direction: { values: [
            { valid_start: "2026-11-09T21:00:00Z", duration: "PT24H", value: 90 },
        ] },
        secondary_swell_height: { values: [
            { valid_start: "2026-11-10T18:00:00Z", duration: "PT3H", value: 0.5 },
            { valid_start: "2026-11-10T21:00:00Z", duration: "PT1H", value: null },
        ] },
    }, "2026-11-10");
    assert.equal(chart.children[0].text, "NOAA marine grid cell: 0.6 miles away.");
    assert.equal(rows.length, 2);
    assert.equal(rows[0].date, "2026-11-10T00:00");
    assert.equal(rows[0].wave_height, 3);
    assert.equal(rows[0].wave_period, 7);
    assert.equal(rows[1].date, "2026-11-10T06:00");
    assert.equal(swells[0].label, "Primary swell");
    assert.equal(swells[0].rows[0].date, "2026-11-10T00:00");
    assert.equal(swells[0].rows[0].wave_height, 1.5);
    assert.equal(swells[0].rows[0].wave_direction, 90);
    assert.equal(swells[1].label, "Secondary swell");
    assert.equal(swells[1].rows.length, 2);
    assert.equal(swells[1].rows[0].wave_height, 0.5);
});

test("wave chart renders separate series, scales all heights, and marks missing swell", () => {
    const render = getChartRenderer("renderWaveChart", "renderMoonPhase");
    const row = (date, height, segment, is_end = false) => ({
        date, wave_height: height, segment, is_end,
    });
    const chart = render([
        row("2026-11-10T00:00", 2, 0), row("2026-11-10T06:00", 2, 0, true),
        row("2026-11-10T12:00", 2, 2), row("2026-11-10T18:00", 2, 2, true),
    ], "2026-11-10", [
        { label: "Primary swell", style: "primary", rows: [
            row("2026-11-10T00:00", 4, 0), row("2026-11-11T00:00", 4, 0, true),
        ] },
        { label: "Secondary swell", style: "secondary", rows: [] },
    ]);
    const legend = chart.children[0];
    assert.equal(legend.children[2].children[1].textContent, "Secondary swell (unavailable)");
    const svg = chart.children[1];
    const paths = svg.children.filter(child => child.tag === "path");
    assert.equal(paths.length, 2);
    const total = paths.find(path => path.attributes.class.endsWith("total"));
    const primary = paths.find(path => path.attributes.class.endsWith("primary"));
    assert.equal((total.attributes.d.match(/M/g) || []).length, 2);
    assert.equal((primary.attributes.d.match(/M/g) || []).length, 1);
    const axisValues = svg.children
        .filter(child => child.tag === "text")
        .map(child => Number(child.textContent))
        .filter(Number.isFinite);
    assert.ok(Math.max(...axisValues) >= 4);
    const titles = svg.children.filter(child => child.tag === "circle")
        .map(child => child.children[0].textContent);
    assert.ok(titles.some(title => title.includes("Total wave height") && title.includes("2.00 ft")));
    assert.ok(titles.some(title => title.includes("Primary swell") && title.includes("4.00 ft")));

    const swellOnly = render([], "2026-11-10", [
        { label: "Primary swell", style: "primary", rows: [
            row("2026-11-10T00:00", 1, 0), row("2026-11-10T06:00", 1, 0, true),
        ] },
        { label: "Secondary swell", style: "secondary", rows: [] },
    ]);
    assert.equal(swellOnly.children[0].children[0].children[1].textContent,
        "Total wave height (unavailable)");
    assert.equal(swellOnly.children[1].children.filter(child => child.tag === "path").length, 1);
});

test("wave chart shows each series' details on hover, focus, and tap", () => {
    const render = getChartRenderer("renderWaveChart", "renderMoonPhase");
    const chart = render([
        { date: "2026-11-10T00:00", wave_height: 2, wave_direction: 90, wave_period: 7 },
    ], "2026-11-10", [
        { label: "Primary swell", style: "primary", rows: [
            { date: "2026-11-10T06:00", wave_height: 1.5 },
        ] },
    ]);
    const [total, swell] = chart.children[1].children.filter(child => child.tag === "circle");
    const readout = chart.children[2];
    total.listeners.pointerenter();
    assert.equal(readout.textContent, "Total wave height, 00:00: 2.00 ft, direction 90, period 7 s");
    assert.equal(total.attributes["aria-label"], readout.textContent);
    swell.listeners.focus();
    assert.equal(readout.textContent, "Primary swell, 06:00: 1.50 ft");
    total.listeners.click();
    assert.match(readout.textContent, /^Total wave height/);
    assert.equal(swell.attributes.tabindex, "0");
    let prevented = false;
    swell.listeners.keydown({ key: " ", preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
    assert.match(readout.textContent, /^Primary swell/);
});

test("tide chart shows high and low predictions on hover and focus", () => {
    const render = getChartRenderer("renderTideChart", "renderMarkdown");
    const chart = render([
        { t: "2026-11-10 03:15", v: "2.5", type: "H" },
        { t: "2026-11-10 09:30", v: "-0.2", type: "L" },
    ], "2026-11-10");
    assert.equal(chart.children[2].attributes.role, "group");
    const [high, low] = chart.children[2].children.filter(child => child.tag === "circle");
    const readout = chart.children[3];
    high.listeners.pointerenter();
    assert.equal(readout.textContent, "High tide: 11/10 03:15, 2.50 ft");
    low.listeners.focus();
    assert.equal(readout.textContent, "Low tide: 11/10 09:30, -0.20 ft");
    assert.equal(low.attributes["aria-label"], readout.textContent);
});
