# Autonomous AI Management & Dynamic Repricing Agent for Ozon

A professional modular system for business process automation and financial risk control on the Ozon marketplace (institutional grade). The platform calculates end-to-end unit economics in real time, conducts competitive intelligence (OSINT module), strictly enforces margin limits, and generates search engine optimization (SEO) copy for product cards using built-in AI algorithms.

Read this in other languages: [Русский (Russian)](README.ru.md)

## Core Architectural Modules

1. **Unit Economics Core (Quant Core)**: Continuous calculation of net profit, margin, and return on investment (ROI) for each SKU. It factoring in cost price, marketplace commissions, multi-level logistics (FBO rates), and tax rates on the fly.
2. **OSINT Monitoring & Dynamic Repricing**: Simulates high-frequency scanning of competitor prices. It automatically triggers a price-matching protocol (`MATCH_COMPETITOR_LOWER`) to keep the product card in the top search results. If competitors drop prices below a critical threshold, the protective `HOLD_MIN_MARGIN_LIMIT` algorithm triggers, locking the price to safeguard the minimum profit margin.
3. **AI Executive Director (Executive Decision Engine)**: Analyzes inventory turnover and financial performance, generating operational strategic directives for the business owner regarding procurement, warehouse supply chain tracking, and marketing budget allocation.
4. **AI Content Factory (SEO Copywriting Factory)**: Automatically generates marketplace search-algorithm-optimized product descriptions and relevant metadata search tags.

## Mathematical Apparatus

The unit economics computational engine utilizes the following objective function to calculate net profit:

$$\text{Net Profit} = P_{current} \cdot (1 - \tau) - C_{cost} - (P_{current} \cdot \mu_{ozon}) - L_{fbo}$$

Where:
- $P_{current}$: Current retail price of the SKU on the marketplace.
- $\tau$: Tax rate (default: $0.06$ for the "Income" simplified tax system).
- $C_{cost}$: Base cost price per unit.
- $\mu_{ozon}$: Dynamic Ozon commission coefficient for the specific product category.
- $L_{fbo}$: Fixed operational expenses for FBO fulfillment, sorting, and trunk logistics.

The lower bound of the safe price ($P_{min}$), guaranteeing the protection of the target profit margin, is calculated as:

$$P_{min} = \frac{C_{cost} + L_{fbo}}{1 - \mu_{ozon} - \tau - \text{Margin}_{min}}$$

## Deployment & Initialization

### System Requirements
- Installed Docker and Docker Compose.

### Quick Start (Build and Run in Background)
Simply copy and paste this command into your terminal within the project directory:

```bash
docker compose up --build -d
```

After a successful build, the interactive dashboard web interface will be accessible in your browser at: http://localhost:8501.

## Project Structure

## Project Structure

```text
ozon_smart_agent/
├── core/
│   └── analytics.py       # Computational core, OSINT simulator, and AI engine
├── data/
│   └── portfolio_ozon.json # Central SKU registry, cost matrix, and margin limits
├── app.py                 # Control dashboard powered by Streamlit
├── requirements.txt       # Python dependency manifest
├── Dockerfile             # Docker container build configuration
└── docker-compose.yml     # Local infrastructure virtualization orchestrator
```

## Useful Container Management Commands

- Check container status:

```bash
docker compose ps
```

- View real-time application logs:

```bash
docker compose logs -f ozon-agent
```

- Stop and remove containers:

```bash
docker compose down
```

## Business Rules Configuration

[portfolio_ozon.json](portfolio_ozon.json)

You can modify product parameters, cost structures, competitor IDs, and margin safety limits directly in the configuration JSON file:

```JSON
{
  "currency": "RUB",
  "tax_rate": 0.06,
  "products": {
    "SKU-IDENTIFIER": {
      "name": "Product Name",
      "stock": 50,
      "cost_price": 500.0,
      "current_price": 1500.0,
      "ozon_commission_pct": 0.15,
      "logistics_fbo": 100.0,
      "min_margin_pct": 0.20,
      "target_competitor_sku": "COMP-ID-01"
    }
  }
}
```