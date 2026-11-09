# Ozon Smart Agent

**A local dashboard for analyzing unit economics and supporting pricing decisions for Ozon sellers.** The application brings together SKU calculations, competitor price observations, margin-protection rules, and catalog management in a single Streamlit interface.

> **Project status:** prototype / MVP. This is an independent project intended for local use and demonstration of engineering skills. It is not an official Ozon product, does not connect to the official Seller API, and does not change prices in the seller's account.

[Русская версия](README.ru.md)

---

## 1. What Is Ozon Smart Agent?

Before changing a price, a seller needs to consider several indicators at once: product cost, marketplace commission, logistics expenses, taxes, minimum margin, stock levels, and competitor prices. When this data is spread across different spreadsheets, it becomes harder to review and compare it regularly.

**Ozon Smart Agent** is a small local application that helps bring the key product metrics together in one dashboard. It stores an SKU catalog, calculates simplified unit economics, attempts to retrieve a competitor's price from a public Ozon page, and highlights signals that may require attention.

It is a **decision-support tool**, not an automatic repricer:

- calculations and recommendations are displayed for the user to review;
- each competitor price has a source status;
- simulated and unavailable prices are not used to generate pricing recommendations;
- the decision to change a price, and the actual price change, remain the seller's responsibility.

In its current version, the application runs locally, uses a JSON file for the catalog, and is designed for a single user.

## 2. Key Features

### Portfolio Analysis

The **Portfolio** section shows the main catalog metrics:

- the number of SKUs added;
- the number of SKUs with negative calculated profit per unit;
- the number of SKUs added to the action queue;
- the number of products for which a price could be parsed from a response returned by Ozon's public endpoint.

Products are added to the action queue when they have negative profit, a price below the calculated minimum, a triggered margin-protection rule, critically low stock, or missing or simulated competitor data.

> Profit is calculated **per product unit**. The application does not yet forecast sales or calculate expected profit for the entire stock balance or for a specific period.

### Unit Economics

The following metrics are calculated for each SKU:

- profit per unit;
- margin relative to the current selling price;
- ROI relative to product cost, provided that the cost is greater than zero;
- the minimum price required to maintain the specified margin.

The application uses a simplified model:

```text
Profit per unit = selling price
                  - product cost
                  - FBO logistics
                  - selling price × Ozon commission
                  - selling price × tax rate

Margin = profit per unit / selling price

ROI = profit per unit / product cost

Minimum price = (product cost + FBO logistics)
                / (1 - commission - tax rate - target margin)
```

Percentage rates are specified as fractions: `0.15` means 15%, and `0.06` means 6%. The shared `core/pricing.py` module uses `Decimal` for monetary calculations, and monetary values are rounded to two decimal places.

This is a simplified model. Its assumptions and limitations are listed in the [Limitations](#9-limitations) section.

### Competitor Price Monitoring

The **Competitor Prices** section displays the competitor SKU, the retrieved price (if available), the data source and status, the minimum acceptable price, and the result of the pricing rule.

Observations have three source statuses:

- `real` – a price was found and parsed from the expected widget in the response returned by Ozon's public page;
- `simulated` – the application generated a demonstration price locally for a `COMP-*` placeholder SKU when demo mode is enabled;
- `unavailable` – a price suitable for calculations could not be retrieved.

The `real` status means that the application extracted a numeric price from the endpoint response. It **does not mean** that the price has been independently verified, is guaranteed to be up to date, or was obtained through the official Seller API.

### Pricing Recommendations and Margin Protection

A recommendation is calculated only when the observation has a `real` source status and contains a valid price.

The current rule proposes a target **10 RUB below the competitor's price**:

1. If this price is not below the calculated minimum, it is displayed as a possible option.
2. If it is below the minimum, the application displays the minimum acceptable price and indicates that margin protection has been triggered.
3. If the competitor price is simulated or unavailable, no competitor-based recommendation is generated.

The recommendation is advisory only. The application does not send it to Ozon or change the product price.

### Catalog Management

The **Catalog** section allows users to add, edit, and delete products. The data is validated before it is saved.

Each SKU stores a product name, stock quantity, product cost, current price, Ozon commission, FBO logistics expenses, target margin, competitor SKU, and an optional link to the Ozon product. The competitor SKU is used for the price request. The link is stored in the catalog for reference and is not currently used in the HTTP request.

### Settings

The **Settings** section allows users to change the global tax rate. It also displays environment parameters, demo mode, HTTP timeout, retry count, and the cache retention period for observations.

---

## 3. Dashboard Preview

The dashboard has four main sections:

1. **Portfolio** – key metrics, the action queue, and the unit economics table.
2. **Competitor Prices** – observations, source statuses, and pricing strategies.
3. **Catalog** – adding, editing, and deleting SKUs with data validation.
4. **Settings** – the tax rate and integration parameters.

| Page | Screenshot |
|---|---|
| Main portfolio dashboard | `docs/images/portfolio.png` |
| Competitor price monitoring | `docs/images/competitor-prices.png` |
| Catalog editor | `docs/images/catalogue.png` |
| Settings | `docs/images/settings.png` |

## 4. Project Architecture

The current MVP uses a simple single-application architecture: Streamlit handles the interface, the `core` package handles calculations and observations, and the `domain` package handles catalog validation and business constraints.

```text
ozon_smart_agent/
├── app.py                     # Streamlit interface, navigation, action queue, JSON writing
├── core/
│   ├── __init__.py
│   ├── analytics.py           # Requests to Ozon's public page, caching, retries, SKU analysis
│   └── pricing.py             # Shared financial calculations using Decimal
├── domain/
│   ├── __init__.py
│   └── validation.py          # Catalog and product data validation
├── tests/
│   ├── test_analytics.py      # Tests for observations, HTTP, and analytics
│   ├── test_domain_rules.py   # Tests for business rules and recommendations
│   ├── test_pricing.py        # Tests for financial calculations and edge cases
│   └── test_validation.py     # Tests for input validation
├── data/
│   └── portfolio_ozon.json   # Local catalog; created and stored on the computer
├── .gitignore
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.in
├── requirements.txt
├── requirements-dev.txt
├── requirements.lock
├── README.md
└── README.ru.md
```

The repository includes a sample catalog with demonstration product data. It can be used as a starting point for testing the application. Do not store real commercial data or confidential business information in the tracked sample file.

### How Data Flows Through the Application

```text
Seller catalog (JSON)
        |
        v
Data validation in domain  --->  Catalog forms in Streamlit
        |
        v
Financial calculations in core/pricing.py (Decimal)
        |
        +---- price, product cost, commission, tax, FBO logistics
        |
        v
Competitor price observation service
        |
        +---- public Ozon page endpoint
        +---- in-memory cache and HTTP retries
        +---- real / simulated / unavailable statuses
        |
        v
Unit economics table and pricing rule
        |
        v
Portfolio dashboard and action queue
```

This diagram represents the current application. The project does not yet include separate backend services, message queues, background workers, or persistent storage for observation history.

## 5. Technology Stack

| Technology | Purpose |
|---|---|
| Python 3.11+ | Main application language and business logic |
| Streamlit 1.50.0 | Local web dashboard and forms |
| Pandas 2.3.3 | Tables and SKU analytics |
| NumPy 2.3.4 | Variation of demonstration prices in demo mode |
| Requests 2.32.5 | HTTP requests to Ozon's public page |
| Cachetools 6.2.1 | Temporary in-memory TTL cache for price observations |
| urllib3 Retry | Retries for selected temporary HTTP errors |
| Decimal | Monetary calculations in the shared pricing module |
| Pytest 8.4.2 | Automated tests |
| Docker / Docker Compose | Running the application in a container |

The versions of the main dependencies are pinned in `requirements.txt`. The `requirements-dev.txt` file additionally installs Pytest. `requirements.lock` currently contains only pinned direct dependencies; it is not yet a complete lock file containing all transitive packages and hashes.

## 6. Data Sources & Reliability

It is important for this project to distinguish between an observation retrieved from an external source, a demonstration value, and a situation where a price could not be retrieved.

### What the Statuses Mean

| Source | How it is generated | Used for a pricing recommendation? | Important considerations |
|---|---|---:|---|
| `real` | The application sends a request to the public Ozon page endpoint using the competitor SKU and extracts the price from the expected `webPrice` widget. | Yes | This is a parsed response from an unofficial public endpoint. The price is not independently verified and is not guaranteed to be current or stable. |
| `simulated` | When `DEMO_MODE=true`, a demonstration value is generated locally for a `COMP-*` placeholder SKU. | **No** | These are synthetic data used only to demonstrate the interface. They must not be treated as the price of a real competitor. |
| `unavailable` | No SKU is specified, the request fails, the response does not contain a suitable price, or demo mode is disabled for a placeholder SKU. | **No** | There is no usable competitor price observation for this product. |

### Public Ozon Endpoint

For a regular competitor SKU, the application sends a GET request to the public Composer endpoint of an Ozon page and attempts to extract a value from the `webPrice` widget. This is **not the official Seller API** and is not a documented integration contract for seller operations.

The endpoint URL, response format, access rules, and availability may change without notice. Therefore, the `real` status in the application means only that a value was successfully parsed from the response. It does not mean that the price has been independently verified or is guaranteed to reflect the current marketplace offer. The application also does not verify product availability, the seller, promotional terms, delivery region, or whether the offer is fully comparable to the user's product.

### Demonstration Prices

When demo mode is enabled, the application may generate a sample price for records with competitor SKUs in the `COMP-*` format if no real observation is available. The price is calculated from the product's current price with a random variation, marked as `simulated`, and excluded from recommendation generation.

To disable simulation, set the following environment variable:

```env
DEMO_MODE=false
```

In this case, placeholder SKUs will have the `unavailable` status instead of a random price.

### HTTP Request Reliability Mechanisms

The current client provides:

- connection and read timeouts (4 seconds each by default);
- retries for GET requests on selected temporary errors (`429`, `500`, `502`, `503`, `504`), as well as on network errors;
- a delay between retries and support for the `Retry-After` header;
- an in-memory TTL cache (120 seconds by default), including temporary caching of an `unavailable` result.

The cache is stored in the memory of the agent object retained in the current Streamlit session. This is temporary storage: the cache is cleared when the session is reset or the application is restarted. The latest observations and the last update time are also stored in Streamlit session state. Persistent price and recommendation history is not yet available.

### Where Data Is Stored and What Is Sent Externally

The product catalog, including product costs and pricing parameters, is stored locally in `data/portfolio_ozon.json`. When running through Docker, the `data/` directory on the user's computer is mounted into the container. When prices are refreshed, the application sends the specified competitor SKU to Ozon's public endpoint.

The example settings may include empty `OZON_CLIENT_ID` and `OZON_API_KEY` variables for future use. **In the current version, they are not used for authentication and do not provide a connection to the Seller API.** Do not add real keys or the `.env` file to Git.

## 7. Installation & Launch

### Requirements

- Python 3.11 or later for local execution;
- Docker Engine and the Docker Compose plugin for container execution;
- macOS, Linux, or Windows with Python/Docker installed.

### Option A – Local Launch

Open a terminal in the project root and run the following commands (example for Python 3.12; Python 3.11 and later are supported):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

If environment variables are not set, the application uses the default values. To change them on macOS/Linux, you can run the following commands before launching the application:

```bash
export APP_ENV=local
export DEMO_MODE=true
export OZON_REQUEST_TIMEOUT=4
export OZON_RETRY_TOTAL=2
export PRICE_CACHE_TTL_SECONDS=120
```

The application does not load the `.env` file automatically. If you store settings in such a file, pass them to the current shell before launching by running `set -a; source .env; set +a`.

Launch the application:

```bash
python -m streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

In Windows PowerShell, activate the virtual environment using `.venv\Scripts\Activate.ps1`. Set environment variables using PowerShell or in the terminal settings before launching Streamlit.

### Option B – Docker Compose

Run the following command from the project root:

```bash
docker compose up --build -d
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501).

Docker Compose binds the port on the host computer to `127.0.0.1` and mounts the local `./data` directory into the container. The `.env` connection in the Compose file is optional: create the file only if you need to change the default settings. The container runs the application as an unprivileged user and has a healthcheck.

Useful commands:

```bash
# Check the container status
docker compose ps

# Follow application logs
docker compose logs -f ozon-agent

# Stop and remove the container
# The local data/ directory is preserved
docker compose down
```

### Environment Variables

| Variable | Default value | Purpose |
|---|---:|---|
| `APP_ENV` | `local` | Environment name displayed in Settings |
| `DEMO_MODE` | `true` | Enables demonstration observations for `COMP-*` SKUs |
| `OZON_REQUEST_TIMEOUT` | `4` | Connection and read timeout, in seconds |
| `OZON_RETRY_TOTAL` | `2` | Number of retries for specified temporary GET failures |
| `PRICE_CACHE_TTL_SECONDS` | `120` | How long an observation is kept in the in-memory cache |

`OZON_CLIENT_ID` and `OZON_API_KEY` are placeholders for a possible future integration. In this version, they are not working Seller API settings.

## 8. Testing

Install the development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run the tests from the project root:

```bash
python -m pytest -q
```

Using `python -m pytest` is recommended: it runs Pytest through the interpreter of the active virtual environment.

The current suite contains **42 tests**. In a local run performed by the project developer, all 42 tests passed. The tests cover:

- profit, margin, ROI, and minimum price calculations using `Decimal`;
- rejection of invalid numbers and impossible combinations of commission, tax, and target margin;
- validation of the catalog and individual SKUs;
- prevention of recommendations based on simulated or unavailable prices;
- parsing a price from a string containing a currency symbol;
- temporary cache behavior and HTTP retry configuration.

These are automated tests of individual modules. They do not guarantee that Ozon's public endpoint will remain available, that its response format will remain unchanged, or that a recommendation is commercially optimal. They also do not replace end-to-end browser testing of the interface or integration testing with the official API.

## 9. Limitations

Ozon Smart Agent is still a local prototype. The following features are **not available** in the current version.

### Marketplace Integration

- There is no connection to the official Ozon Seller API and no authentication to the seller account.
- There is no operation to create, change, or publish a price on Ozon.
- There is no synchronization of orders, sales, promotions, commission rates, or warehouse stock levels.
- Retrieving a price from a public page depends on an unofficial endpoint and an expected response format. Either may change or become unavailable.

### Financial Model and Recommendations

- The model is simplified and depends on parameters entered by the user.
- Commission and tax are calculated as fractions of the selling price; product cost and FBO logistics are fixed expenses per unit.
- Discounts, coupons, promotions, returns, cancellations, acquiring fees, storage, the full range of FBO/FBS tariffs, VAT and tax-regime specifics, and individual Ozon seller tariff terms are not accounted for separately.
- The pricing rule uses a fixed difference of RUB 10 relative to the competitor. This is not dynamic repricing: price increments, demand elasticity, competitor stock availability, sales dynamics, and offer comparability are not taken into account.
- The dashboard calculates profit per unit, not actual or forecast profit for the entire portfolio. There is no demand or sales forecasting.

### Data Storage and Operations

- The catalog is stored in a local JSON file. There is no database, schema migration system, or mechanism for concurrent editing by multiple users.
- Observation and recommendation history is not saved. The TTL cache is stored in the memory of the current Streamlit session and is not persistent.
- There is no catalog change log, scheduled background monitoring, or notification delivery.
- There is no authentication, role management, access control, or separation of user data. The dashboard is intended for local use. Do not expose it to a public or shared network without authentication and TLS.

### AI, Automation, and Development Process

- No LLM is connected. The SEO text helper in the core is a local static template, not AI-generated content or a complete content-generation workflow.
- The current project snapshot does not include a GitHub Actions CI pipeline.
- `requirements.lock` pins only direct dependencies and is not yet a complete lock file with transitive packages and hashes.
- The 42-test suite is a useful baseline check, but it does not demonstrate production-ready quality.

## 10. Roadmap

Further development is planned primarily to improve data reliability and decision transparency:

1. **Observation history** – store competitor prices with date and time, SKU, source, and status.
2. **Recommendation history** – store calculation inputs, the rule that was triggered, and the resulting recommendation.
3. **Audit log** – record product additions, edits, and deletions.
4. **Event correlation** – add identifiers for refresh runs, observations, recommendations, and audit events.
5. **Reliability checks** – expand tests for timeouts, invalid responses, missing widgets, cache expiration, and external endpoint errors.
6. **Continuous integration** – add GitHub Actions to run checks and tests automatically on push and Pull Request events.
7. **Database layer** – consider SQLite for history in a single-user scenario, or PostgreSQL when there is a real need for multiple users and concurrent changes.
8. **Official Seller API** – consider authenticated operations only after designing the data model, secret storage, access permissions, auditing, and safety checks.

---

## Important Notice

Ozon Smart Agent is an independent project. It is not affiliated with Ozon, has not been endorsed by Ozon, and is not an official Ozon product. All financial calculations and pricing recommendations must be checked against the seller's current terms, actual expenses, and the specifics of their business.