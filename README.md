# Ozon Smart Agent — AI Copilot & Dynamic Repricer for Sellers

**Ozon Smart Agent** is an intelligent automated management system designed for marketplace sellers on Ozon. It eliminates daily operational chaos by calculating end-to-end unit economics in real time, tracking competitor prices, dynamically updating product listing prices, and protecting your business margins from severe price wars.

Read this in other languages: [Русский (Russian)](README.ru.md)

## Key Platform Capabilities

* **Real-time Unit Economics** — instantly computes net profit per SKU by accounting for base costs, marketplace sales commissions, multi-tier FBO fulfillment fees, and regional tax obligations.
* **Competitive Intelligence (OSINT)** — scans competitor listings via product identifiers (SKUs) or direct Ozon URLs to detect undercut pricing strategies in real time.
* **Automated Margin Guard** — prevents selling at a loss. If a competitor drops their price too low, the protective algorithm locks your listing at your minimum safe price limit ($P_{\text{min}}$).
* **AI Executive Director Advice** — generates actionable strategic directives for the business owner regarding warehouse stock replenishments, overstock promotions, and ad budget optimization.
* **AI SEO Copywriting Engine** — generates search-engine-optimized product descriptions and tag metadata designed to boost search rankings on Ozon.

## Mathematical Apparatus

You no longer need to manage complex, prone-to-error Excel spreadsheets. The computational core handles all formula execution automatically:

### 1. Net Profit per Unit Function
$$\text{Net Profit} = P_{\text{current}} \cdot (1 - \tau) - C_{\text{cost}} - (P_{\text{current}} \cdot \mu_{\text{ozon}}) - L_{\text{fbo}}$$

* **$P_{\text{current}}$**: current retail listing price on Ozon.
* **$\tau$**: applicable tax rate (default: $0.06$ for Simplified Tax System).
* **$C_{\text{cost}}$**: unit procurement/production cost price.
* **$\mu_{\text{ozon}}$**: dynamic Ozon category commission coefficient (e.g., $0.15$ for 15%).
* **$L_{\text{fbo}}$**: fixed operational costs for FBO fulfillment, handling, and trunk logistics.

---

### 2. Minimum Safe Threshold Price ($P_{\text{min}}$)
$$P_{\text{min}} = \frac{C_{\text{cost}} + L_{\text{fbo}}}{1 - \mu_{\text{ozon}} - \tau - \text{Margin}_{\text{min}}}$$

* **$\text{Margin}_{\text{min}}$**: minimum required profit margin limit (e.g., $0.20$ for 20%).

---

## Quick Start

### Prerequisites
* Installed **Docker** and **Docker Compose**.

### One-Command Deployment
Run the following command in your terminal from the project root directory:

```bash
docker compose up --build -d
```

## Dashboard Interface Layout

1. **Analytics & Autopilot** — high-level portfolio financial metrics, executive advisory insights, and AI-powered SEO content generator.
2. **OSINT Monitoring** — real-time competitor pricing grid featuring visual status tags (🔴 Undercutting / 🟢 Above your price) and clickable direct links to Ozon product listings.
3. **SKU Management** — interactive catalogue configuration editor. Modify base cost prices, stock allocations, and target competitor links with immediate profit sensitivity visual charts.

## Repository Architecture

```text
ozon_smart_agent/
├── core/
│   └── analytics.py        # analytics computational core and OSINT engine
├── data/
│   └── portfolio_ozon.json  # central SKU configuration matrix and safety limits
├── app.py                  # web application dashboard powered by Streamlit
├── requirements.txt        # dependencies manifest
├── Dockerfile              # Docker container configuration
└── docker-compose.yml      # local Docker virtualization orchestrator
```

## Infrastructure Management Commands

- Check container status:

```bash
docker compose ps
```

- Stream container logs:

```bash
docker compose logs -f ozon-agent
```

- Stop service:

```bash
docker compose down
```

## Data Security & Privacy
All cost price matrices, tax settings, and financial records remain 100% confidential and localized within your local Docker container. No private business data is ever transmitted to external analytics third parties.