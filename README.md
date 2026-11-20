# fishin_time

Static files used by the page belong in `static/`. The Docker image copies this
directory and FastAPI serves it under `/static`; for example,
`static/mermaid-diagram.png` is available at `/static/mermaid-diagram.png`.

## Station county labels

The station dropdown groups NOAA tide-prediction stations by county, with
county labels in alphabetical order. It uses
the bundled `services/station_counties.json` lookup, so loading the dropdown
does not make Census requests. Unmatched stations, stations in a different
state than their Census match, and stations whose coordinates or state have
changed since the lookup was generated appear under "County unavailable".
Stations remain in latitude/longitude order within each county.

To refresh the lookup after NOAA station or Census geography updates, run:

```sh
./.venv/bin/python -m utilities.refresh_station_counties
```

The script fetches NOAA stations, submits their coordinates to the Census
batch geocoder, and maps its county codes using the 2020 and 2026 Census county
gazetteers. Batch codes can reflect 2020 boundaries, including historical
Connecticut counties. The gazetteers do not cover all U.S. Island Areas, so
some territories remain unmatched. Review warnings and commit the refreshed
lookup for deployment; the app loads it once per process.

Forecast requests use the selected NOAA station's coordinates and station ID.
Existing `/forecast/get_forecast` clients may continue sending `city`, `state`,
and `date`; if a station name is ambiguous within the state, also provide the
`station_id` returned by `/api/cities`. The station's weather.gov grid response
supplies its timezone.

Forecast responses retain the existing fields and add the selected `station`,
seven dated `daily_forecasts`, `weather_forecast` periods and NOAA tide
`predictions`, plus a `nearshore` object with NWS marine-grid wave, swell, and
wind interval arrays and an hourly `waves` array derived from those intervals.
`precipitation_forecast` contains NWS weather intervals with precipitation.
The first chance shown for a day is the start of its first overlapping interval,
including 00:00 for an interval already in progress; it is not an exact onset.
If there is no precipitation interval, the time is unavailable.
Nearshore search is limited to 10 km from the station; `nearshore.grid.inferred`
is true only when the chosen grid cell is more than 2.5 km away. `nearshore` is
null when no suitable marine grid cell is found within the search limit.
The nearshore chart plots total wave height and available primary and secondary
swell heights separately; it does not add the swell heights to the total.
Hover, focus, or tap a point on the wave or tide chart to see its details below
the chart. Tide points represent NOAA high and low predictions.

The forecast response also includes the station's IANA `timezone` (supplied by
the NWS for the station's coordinates, never hard-coded), local `sunrise`,
`sunset`, `moonrise` and `moonset` in each daily forecast (USNO), and `alerts`:
active NWS alerts for the station point, its nearest marine grid cell, and its
county. Alerts for adjacent marine zones and surf-zone forecast text are not
included, and an unavailable alert service is reported in `alerts.error`
rather than failing the forecast. The AI prompt states the selected date,
today's date and the station time zone, lists the supplied data and its time
and unit formats, and instructs the agent not to search the web or look up
information that is already supplied.

The forecast table has seven date tabs labeled with the weekday and day of the
month. Dates less than three days away start
the tab row; later dates appear in the middle. The initial request fetches the
entire displayed week, and tab changes use that response without another
forecast or AI request. The AI recommendation is labeled with the date used
to generate it; choosing another tab does not update it. A dialog explains how
to generate a recommendation for the newly selected date and can be suppressed
until the browser tab closes or the user signs in or out. Independent weather and station data requests run
concurrently. When nearshore intervals are available, the AI receives those intervals rather than
the redundant hourly waves derived from them; the full response still includes
both. The browser receives partial recommendation text over an authenticated
stream and displays it as it arrives. Partial text is not the final result and
may change; the stream starts showing text when the agent produces its answer.
Until then, the agent's reasoning summary and commentary are shown as live
activity under the progress indicator. Each run logs the elapsed time at which
each agent stage first appeared (`AI evaluation timing in seconds`). Each reasoning
step and commentary message is also appended, with elapsed time, to
`fishintime_ai_reasoning.log` in the system temporary directory (owner-readable
only) so prompts can be refined; final answers are not written to it.
NWS forecast availability may cover less than
the displayed week.
Pressure and water temperature are NOAA CO-OPS observations, not forecasts.
For each product, the app checks up to five nearby stations with active sensors
in order of distance and uses the first with data from the past 72 hours, within 50 miles for
pressure and 25 miles for water temperature. The source station and distance
are shown; data freshness and environmental similarity are not guaranteed.
Nearby conditions may differ from the selected location. The latest pressure
and water observations are shown on every tab; the pressure observation time
is displayed and does not represent a forecast for the selected date. When
recent pressure data lacks the three-hour comparison reading, the app requests
that time window separately; the trend remains unavailable if it cannot be found.
Some locations have no nearby observations.
Each successful request overwrites
`forecast.json` in the application's working directory.

## Frontend backend URL

The frontend reads `window.FISHINTIME_API_BASE_URL` from `config.js` and uses it
for all API requests. Leave it empty to use the current origin, which keeps the
website's same-origin behavior. For a mobile app build, set it to the HTTPS
origin serving the API (for example, `https://api.example.com`, without a path).
Do not use the current HTTP-only load balancer URL for a released mobile app;
configure HTTPS for the API first. This URL is public configuration, not a place
to store API keys or other secrets.

## OpenAI agent and AWS Secrets Manager setup

Install the project dependencies with `pip install -r requirements.txt`. Store
the OpenAI API key as JSON (`{"OPENAI_API_KEY":"..."}`) in
`FishinSecret_OpenAI` and the agent ID as JSON (`{"AGENT_ID":"..."}`) in
`FishinSecret_Agent_Id`. The application extracts those fields from the JSON.
The AWS region defaults to `us-east-2` and can be overridden with `AWS_REGION`.

The application reads the secret once during FastAPI startup and keeps it in
memory for that process. If AWS Secrets Manager cannot return a valid secret,
startup fails rather than allowing forecast requests to fail later. Restart or
redeploy the app after rotating the secret so the new value is loaded.

When running on AWS, grant the application's IAM role
`secretsmanager:GetSecretValue` for this secret. For local development,
configure the `fishintime-757` AWS CLI profile with access to the application
secrets. Use a non-root IAM principal with least-privilege permissions;
the resource ARNs are listed in
`infra/iam/fishintime-task-secrets-policy.json`.

```sh
aws configure --profile fishintime-757  # only if this profile is not configured
set -a
. ./.env
set +a
./.venv/bin/python run.py
```

Local runs use the live Stripe account by default. To run against the retained
Stripe sandbox instead:

```sh
./.venv/bin/python run.py --sandbox
```

In VS Code, choose **Run API (live)** or **Run API (sandbox)**. Sandbox mode
uses the existing `FishinSecret_Stripe_API_Key` and `fishintime-billing`
resources; live mode uses `FishinSecret_Stripe_API` and a separate
`fishintime-billing-live` table. Apply the Terraform changes before using live
mode locally. Sandbox and live customer IDs, subscriptions, and webhook
signatures are isolated.

Verify the profile points to account `757266935832` before running Terraform or
the app:

```sh
aws sts get-caller-identity --profile fishintime-757
```

The application calls Secrets Manager directly in both local development and
AWS deployments. boto3 uses the `fishintime-757` profile locally and
the task's IAM role on AWS. `.env` supplies local region and Cognito/billing
configuration, but never stores secret values.
Check the local credentials with `aws sts get-caller-identity
--profile fishintime-757`. Do not commit AWS credentials or secret values; `.env`
is excluded from Git.

## Stripe subscriptions and AI recommendations

The monthly and annual prices are Terraform variables measured in USD cents:
`stripe_monthly_amount_cents` defaults to `99`, and
`stripe_annual_amount_cents` defaults to `999`. For example, override either
value in your Terraform variables file or with `-var` when applying Terraform.
Checkout creates recurring Stripe prices from these amounts, so no Stripe
Price IDs need to be created or copied into the application. Remove any older
`stripe_price_monthly` / `stripe_price_annual` Price ID entries from
`terraform.tfvars`; use the new `stripe_monthly_amount_cents` /
`stripe_annual_amount_cents` values instead.
Checkout classifies the AI fishing recommendation subscription with Stripe
Tax code `txcd_10105001` (AIaaS, cloud-based, personal use) to support Stripe
Managed Payments. This assumes the service is sold to individual recreational
anglers; review the tax classification if the intended customer base changes.

The `FishinSecret_Stripe_API` secret contains the live restricted Stripe API
key, either as plain text or in a JSON object under the
`FishinSecret_Stripe_API_Key` field. Sandbox mode uses the retained
`FishinSecret_Stripe_API_Key` secret, whose JSON property is
`FishinSecret_Stripe_API`. The secrets have different names and property names.
Stripe API keys start with `sk_live_` or `rk_live_` in live mode and
`sk_test_` or `rk_test_` in a sandbox; `prod_` is a Stripe Product ID prefix,
not an API key prefix.

Configure separate Stripe webhook endpoints for live and sandbox, both pointed
at
`https://api.tidalfishintime.com/api/billing/webhook` for
`customer.subscription.created`, `customer.subscription.updated`, and
`customer.subscription.deleted`. Store the sandbox endpoint's signing secret
in `FishinTime_Stripe_Webhook_Secret` and the live endpoint's in
`FishinTime_Stripe_Webhook_Secret_Live`. The application selects the key,
webhook secret, and billing table for its Stripe mode.

The Cognito callback and logout allow-lists must contain the exact forecast
URL `${app_base_url}/` (by default, `https://tidalfishintime.com/`). The
`api.tidalfishintime.com` hostname remains an API compatibility alias. The
account page URL `${app_base_url}/billing/account` can remain in these lists
for compatibility. The plans are shown at
`/billing/subscribe`; sign-in and account self-service are at `/billing/account`.
The account page supports email changes with confirmation, password changes,
and subscription management through the Stripe billing portal. With email as
the user-pool sign-in attribute, changing the email also changes the address
used to sign in. The subscription page uses Cognito's authorization-code flow
with PKCE. Users can access forecast and environmental data without signing in;
any signed-in user can request AI fishing evaluations. Subscription status
remains available for billing and account management. Stripe API and webhook
secrets are read from Secrets Manager, and subscription status is updated only
after Stripe webhook events update the billing table.
