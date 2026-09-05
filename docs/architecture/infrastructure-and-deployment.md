# Infrastructure and Deployment

## Infrastructure as Code

- **Tool:** Docker + docker-compose 2.24.0
- **Location:** `./docker/`
- **Approach:** Containerized deployment for consistency across environments, with local development and VPS deployment configurations

## Deployment Strategy

- **Strategy:** Blue-Green deployment with health checks before cutover
- **CI/CD Platform:** GitHub Actions (for automated testing) + manual deployment scripts
- **Pipeline Configuration:** `.github/workflows/ci.yml` and `./scripts/deploy.sh`

## Environments

- **Development:** Local Windows/Linux machine - Direct Python execution with live code reload
- **Staging:** Docker container on local machine - Mimics production with test broker account
- **Production:** VPS (Ubuntu 22.04 LTS) - Docker container with supervisor for process management

## VPS Resource Requirements

### Minimum Production Specifications

- **CPU:** 2 vCPUs (AMD EPYC or Intel Xeon)
- **RAM:** 4GB (2GB application + 2GB buffer)
- **Storage:** 20GB SSD (10GB OS + 5GB app + 5GB logs/data)
- **Network:** 100 Mbps minimum, <50ms latency to Telegram DCs
- **OS:** Ubuntu 22.04 LTS

### Scaling Triggers

- **CPU >80% sustained:** Add 1 vCPU
- **RAM >75% used:** Add 2GB RAM
- **Disk >70% full:** Rotate logs more aggressively
- **Network latency >100ms:** Consider different region

### Recommended Providers

- **Europe:** Hetzner CX21 (€4.90/month, 2 vCPU, 4GB RAM)
- **Global:** DigitalOcean Basic Droplet ($24/month)
- **High-end:** AWS t3.medium with reserved pricing

## Environment Promotion Flow

```text
Development (Local)
    ├── Run tests locally (pytest)
    ├── Manual testing with demo account
    └── Git commit to feature branch
            ↓
Staging (Docker Local)
    ├── Build Docker image
    ├── Run integration tests
    ├── 24-hour soak test with paper trading
    └── Tag release version
            ↓
Production (VPS)
    ├── Pull tagged image
    ├── Run health checks
    ├── Blue-Green swap
    └── Monitor for 1 hour
```

## Rollback Strategy

- **Primary Method:** Docker container version rollback - keep last 3 versions
- **Trigger Conditions:** Health check failures, >5% error rate, MT5 connection loss >5 minutes
- **Recovery Time Objective:** <2 minutes for container swap
