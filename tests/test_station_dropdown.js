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
    const start = html.indexOf('        forecastForm.addEventListener("submit"');
    const end = html.indexOf("\n        });", start) + "\n        });".length;
    assert.ok(start >= 0 && end > start);
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
        showAiAvailabilityNotice() {},
        activeEvaluationRequest: 0,
        URLSearchParams,
        apiUrl: value => value,
        authorizationHeaders: () => ({}),
        fetch: async url => {
            requestedUrl = url;
            return { ok: true, json: async () => ({}) };
        },
        saveForecastState: state => { saved = state; },
        renderForecastTable: () => ({}),
        console,
    };
    vm.runInNewContext(html.slice(start, end), context);
    await submit({ preventDefault() {} });

    const params = new URL(requestedUrl, "https://example.test").searchParams;
    assert.equal(params.get("station_id"), "8722937");
    assert.equal(params.get("city"), "Fort Lauderdale, Andrews Ave. Bridge");
    assert.equal(saved.station_id, "8722937");
    assert.equal(saved.city, "Fort Lauderdale, Andrews Ave. Bridge");
});

function getForecastRenderer() {
    const html = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");
    const start = html.indexOf("        function renderForecastTable(");
    const end = html.indexOf("\n        }", start) + "\n        }".length;
    assert.ok(start >= 0 && end > start);
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
    return vm.runInNewContext(
        `(${html.slice(start, end).trim()})`,
        { document },
    );
}

test("forecast table hides coordinates without changing other rows", () => {
    const renderForecastTable = getForecastRenderer();
    const result = {
        city: "Fort Lauderdale",
        city_lat: "26.1183",
        city_long: "-80.145",
        temp: 80,
    };

    const table = renderForecastTable(result);

    assert.deepEqual(table.children.map(row => row.children[0].textContent), [
        "City", "Temperature",
    ]);
    assert.equal(table.children[1].children[1].textContent, "80°F");
    assert.equal(result.city_lat, "26.1183");
    assert.equal(result.city_long, "-80.145");
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
