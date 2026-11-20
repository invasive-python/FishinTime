const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

test("counties are alphabetical and stations retain service order within each county", async () => {
    const html = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");
    const start = html.indexOf("        async function loadStations(");
    const end = html.indexOf("\n        }", start) + "\n        }".length;
    assert.ok(start >= 0 && end > start);
    const citySelect = {
        innerHTML: "",
        disabled: true,
        children: [],
        appendChild(element) { this.children.push(element); },
    };
    const document = {
        createElement(tag) {
            return { tag, children: [], appendChild(element) { this.children.push(element); } };
        },
    };
    const stations = [
        { id: "1", name: "Fort Lauderdale", county: "Broward County" },
        { id: "2", name: "Other", county: "Miami-Dade County" },
        { id: "3", name: "Lauderdale-by-the-Sea", county: "Broward County" },
        { id: "4", name: "Unmatched", county: null },
        { id: "5", name: "Fort Lauderdale", county: "Broward County" },
    ];
    const fetch = async () => ({ ok: true, json: async () => stations });
    const loadStations = vm.runInNewContext(
        `(${html.slice(start, end).trim()})`,
        { citySelect, document, fetch, API_BASE: "/api", console },
    );

    await loadStations("FL", "Fort Lauderdale");

    assert.deepEqual(citySelect.children.map(group => group.label), [
        "Broward County", "County unavailable", "Miami-Dade County",
    ]);
    assert.deepEqual(citySelect.children[0].children.map(option => option.value), [
        "1", "3", "5",
    ]);
    assert.equal(citySelect.children[1].children[0].value, "4");
    assert.equal(citySelect.value, "1");
    assert.equal(citySelect.disabled, false);

    await loadStations("FL", "5");
    assert.equal(citySelect.value, "5");
});

test("forecast submission sends the selected station ID and name", async () => {
    const html = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");
    const loadStart = html.indexOf("        async function loadForecast(");
    const start = html.indexOf('        forecastForm.addEventListener("submit"');
    const end = html.indexOf("\n        });", start) + "\n        });".length;
    assert.ok(loadStart >= 0 && start > loadStart && end > start);
    let submit;
    let requestedUrl;
    let saved;
    const context = {
        forecastForm: { addEventListener(_event, handler) { submit = handler; } },
        citySelect: { value: "8722937", selectedOptions: [{ textContent: "Fort Lauderdale, Andrews Ave. Bridge" }] },
        stateSelect: { value: "FL" },
        dateSelect: { value: "2026-10-14" },
        forecastSubmit: { disabled: false },
        forecastResult: { replaceChildren() {} },
        evaluation: {},
        stopEvaluationProgress() {},
        cancelEvaluationStream() {},
        showAiAvailabilityNotice() {},
        activeEvaluationRequest: 0,
        currentForecastSelection: null,
        currentForecastResult: null,
        URLSearchParams,
        apiUrl: value => value,
        authorizationHeaders: () => ({}),
        renderForecastTabs() {},
        forecastTabDates: () => ["2026-10-11"],
        renderForecastForDate() {},
        fetch: async url => {
            requestedUrl = url;
            return { ok: true, json: async () => ({}) };
        },
        saveForecastState: state => { saved = state; },
        renderForecastTable: () => ({}),
        console,
    };
    vm.runInNewContext(html.slice(loadStart, end), context);
    await submit({ preventDefault() {} });

    const params = new URL(requestedUrl, "https://example.test").searchParams;
    assert.equal(params.get("station_id"), "8722937");
    assert.equal(params.get("city"), "Fort Lauderdale, Andrews Ave. Bridge");
    assert.equal(params.get("start_date"), "2026-10-11");
    assert.equal(saved.station_id, "8722937");
    assert.equal(saved.city, "Fort Lauderdale, Andrews Ave. Bridge");
    assert.equal(saved.anchorDate, "2026-10-14");
});

function getForecastRenderer(extraContext = {}) {
    const html = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");
    const start = html.indexOf("        function renderForecastTable(");
    const helperStart = html.indexOf("        function formatObservationStation(");
    const helperEnd = html.indexOf("        function renderPressureIndicator(", helperStart);
    const end = html.indexOf("\n        }", start) + "\n        }".length;
    assert.ok(helperStart >= 0 && helperEnd > helperStart && start > helperEnd && end > start);
    const document = {
        createElement(tag) {
            return {
                tag,
                children: [],
                setAttribute() {},
                append(element) { this.children.push(element); },
            };
        },
    };
    const context = { document, ...extraContext };
    vm.runInNewContext(html.slice(helperStart, helperEnd), context);
    return vm.runInNewContext(`(${html.slice(start, end).trim()})`, context);
}

test("forecast table shows sun and moon times after the moon phase and hides alerts data", () => {
    const renderForecastTable = getForecastRenderer({
        renderMoonPhase: () => ({ tag: "moon" }),
    });
    const table = renderForecastTable({
        city: "Fort Lauderdale",
        moon_current_phase: "Full Moon",
        timezone: "America/New_York",
        alerts: { items: [] },
        sunrise: "06:44",
        sunset: "17:29",
        moonrise: "15:46",
        moonset: null,
    });
    assert.deepEqual(table.children.slice(0, 6).map(row => row.children[0].textContent), [
        "City", "Current Moon Phase", "Sunrise", "Sunset", "Moonrise", "Moonset",
    ]);
    assert.deepEqual(
        table.children.slice(2, 6).map(row => row.children[1].textContent),
        ["06:44", "17:29", "15:46", "Unavailable"],
    );
    assert.equal(table.children.some(row => row.children[0].textContent === "alerts"), false);
    assert.equal(table.children.some(row => row.children[0].textContent === "timezone"), false);
});

test("forecast table hides coordinates without changing other rows", () => {
    const renderForecastTable = getForecastRenderer();
    const result = {
        city: "Fort Lauderdale",
        city_lat: "26.1183",
        city_long: "-80.145",
        temp: 80,
        weather_forecast: [{ name: "Tuesday" }],
        precipitation_forecast: [{ start_time: "2026-11-21T18:00:00Z" }],
    };

    const table = renderForecastTable(result);

    assert.deepEqual(table.children.map(row => row.children[0].textContent), [
        "City", "Current Air Temperature",
    ]);
    assert.equal(table.children[1].children[1].textContent, "80°F");
    assert.equal(result.city_lat, "26.1183");
    assert.equal(result.city_long, "-80.145");
});

test("water temperature follows air temperature and identifies the observation station", () => {
    const renderForecastTable = getForecastRenderer();
    const table = renderForecastTable({
        city: "Station",
        temp: 80,
        wind_direction: "E",
        water_temperature: {
            temperature_f: 76.2, observed_at: "2026-11-20T08:54:00-05:00",
            station: { station_id: "8722956", name: "South Port Everglades", distance_miles: 3.08 },
        },
    });
    assert.deepEqual(table.children.map(row => row.children[0].textContent), [
        "City", "Current Air Temperature", "Current Water Temperature", "Wind",
    ]);
    assert.equal(table.children[2].children[1].textContent,
        "76.2°F — NOAA station: South Port Everglades, 3.1 miles away");
    const unnamed = renderForecastTable({
        temp: 80, water_temperature: {
            temperature_f: 76, observed_at: "2026-11-20T08:54:00-05:00",
            station: { station_id: "8722956", name: null, distance_miles: 3.08 },
        },
    });
    assert.equal(unnamed.children[1].children[1].textContent,
        "76°F — NOAA station: name unavailable, 3.1 miles away");
    const unavailable = renderForecastTable({
        temp: null, water_temperature: { temperature_f: null, error: "No sensor" },
    });
    assert.equal(unavailable.children[1].children[1].textContent, "Unavailable");
});

test("pressure indicator identifies the nearby observation station", () => {
    const html = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");
    const helperStart = html.indexOf("        function formatObservationStation(");
    const helperEnd = html.indexOf("        function renderPressureIndicator(", helperStart);
    const start = html.indexOf("        function renderPressureIndicator(");
    const end = html.indexOf("        function addChartPointDetails(", start);
    const document = { createElement: () => ({
        children: [], setAttribute() {}, append(element) { this.children.push(element); },
    }) };
    const context = { document };
    vm.runInNewContext(html.slice(helperStart, helperEnd) + html.slice(start, end), context);
    const indicator = context.renderPressureIndicator({
        current_pressure_inhg: 29.9,
        station: { station_id: "8722956", name: "South Port Everglades", distance_miles: 3.08 },
        observed_at: "2026-11-20T16:06:00-05:00",
    });
    assert.equal(indicator.children[1].textContent,
        "NOAA station: South Port Everglades, 3.1 miles away");
    assert.equal(indicator.children[2].textContent,
        "NOAA observation: 2026-11-20T16:06:00-05:00");
    assert.equal(indicator.children[3].textContent, "Trend unavailable");
});

test("forecast table formats the selected calendar date without changing it", () => {
    const renderForecastTable = getForecastRenderer();
    for (const [date, expected] of [
        ["2026-11-21", "Saturday, November 21"],
        ["2027-01-01", "Friday, January 1"],
    ]) {
        const result = { date };
        const table = renderForecastTable(result);
        assert.equal(table.children[0].children[1].textContent, expected);
        assert.equal(result.date, date);
    }
    const invalid = renderForecastTable({ date: "2026-02-30" });
    assert.equal(invalid.children[0].children[1].textContent, "Unavailable");
});

test("forecast table displays precipitation start time without its date", () => {
    const renderForecastTable = getForecastRenderer();
    const result = { start_time: "2026-11-21 06:00" };
    const table = renderForecastTable(result);
    assert.equal(table.children[0].children[0].textContent, "First Chance of Precipitation");
    assert.equal(table.children[0].children[1].textContent, "06:00");
    assert.equal(result.start_time, "2026-11-21 06:00");
    const missing = renderForecastTable({ start_time: null });
    assert.equal(missing.children[0].children[1].textContent, "Unavailable");
});

test("forecast table combines wind direction and available speeds", () => {
    const renderForecastTable = getForecastRenderer();
    const cases = [
        [{ wind_speed_max: 23.02, wind_speed_min: 19.56, wind_direction: "E" },
            "E 19.56 MPH (min) - 23.02 MPH (max)"],
        [{ wind_speed_min: 5, wind_speed_max: 5, wind_direction: "SW" }, "SW 5.00 MPH"],
        [{ wind_speed_max: 0, wind_speed_min: null, wind_direction: "N" }, "N 0.00 MPH"],
        [{ wind_speed_min: 3.5, wind_direction: "S" }, "S 3.50 MPH"],
        [{ wind_speed_max: 7, wind_direction: "" }, "7.00 MPH"],
        [{ wind_direction: "W" }, "W"],
    ];

    for (const [wind, expected] of cases) {
        const table = renderForecastTable({ city: "Fort Lauderdale", ...wind });
        assert.deepEqual(table.children.map(row => row.children[0].textContent), ["City", "Wind"]);
        assert.equal(table.children[1].children[1].textContent, expected);
    }
});
