# Garmin MCP Server

This Model Context Protocol (MCP) server connects to Garmin Connect and exposes your fitness and health data to OpenWebUI, Claude or any other MCP-compatible clients via Streamable HTTP transport.

Credits: https://github.com/Taxuspt/garmin_mcp

## Features

- **78+ MCP Tools** covering:
  - Activity management (list, get details, splits, weather, gear)
  - Health & wellness metrics (steps, heart rate, sleep, stress, body battery)
  - Training & performance data (VO2 Max, HRV, training effect, fitness age)
  - Device management
  - Gear tracking
  - Weight management
  - Challenges & badges
  - Workouts
  - Women's health data
  - Data management (add body composition, blood pressure, hydration)
  - Personalised training and diet recommedations

- **Streamable HTTP Transport** - Network-accessible MCP server for Kubernetes/container deployments
- **Token Persistence** - OAuth tokens cached to avoid repeated MFA prompts
- **Non-interactive MFA** - Supports containerised deployments with environment-based MFA codes
- **API Key Authentication** - Secure HTTP/SSE endpoints with Bearer token or header verification (while keeping `/healthz` endpoints public)
- **Hybrid Memory & Disk Caching** - 5-minute memory TTL for recent/dynamic queries, and permanent disk caching for historical/static data (queries >7 days old)
- **High Concurrency & Parallelism** - Automatically offloads blocking third-party Garmin API calls to background worker threads to keep the event loop highly responsive

## Prerequisites

- Python 3.10+ (3.12 recommended)
- Garmin Connect account credentials
- For Kubernetes: kubectl access to your cluster

## Deployment Options

### 1. Standalone (Local Development)

#### Installation

```bash
# Clone the repository
git clone <repository-url>
cd garmin_mcp

# Install dependencies
uv sync
```

#### Running

**With stdio transport (for MCP clients like Claude Desktop):**

```bash
export GARMIN_EMAIL="your-email@example.com"
export GARMIN_PASSWORD="your-password"
export GARMIN_MCP_TRANSPORT="stdio"

uv run garmin-mcp
```

**With Streamable HTTP transport (for network access):**

```bash
export GARMIN_EMAIL="your-email@example.com"
export GARMIN_PASSWORD="your-password"
export GARMIN_MCP_TRANSPORT="streamable-http"
export GARMIN_MCP_HOST="0.0.0.0"
export GARMIN_MCP_PORT="8000"

uv run garmin-mcp
```

The server will be accessible at `http://localhost:8000/mcp`

#### First-Time Setup (MFA - Only if enabled on Garmin Connect)

If you have MFA enabled on your Garmin Connect account, you'll need to provide the 2FA code on first run. You have two options:

**Option A: Interactive (for local development)**
- The server will prompt for the MFA code in the terminal

**Option B: Non-interactive (for automation)**
```bash
export GARMIN_MFA_CODE="123456"  # Code from email/SMS
export GARMIN_MFA_WAIT_SECONDS="180"  # Optional: wait up to 180s for code to appear
```

**Note:** If MFA is not enabled on your Garmin Connect account, you can skip these environment variables.

After successful login, OAuth tokens are saved to `~/.garminconnect` and future runs won't require MFA until tokens expire.

#### Configuration with Claude Desktop

Edit your Claude Desktop configuration:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uv",
      "args": ["run", "garmin-mcp"],
      "env": {
        "GARMIN_EMAIL": "your-email@example.com",
        "GARMIN_PASSWORD": "your-password",
        "GARMIN_MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

**Note:** If you have MFA enabled on your Garmin Connect account, add `"GARMIN_MFA_CODE": "123456"` to the `env` section for the first run.

Restart Claude Desktop after making changes.

### 2. Docker Deployment

#### Build the Image

```bash
docker build -t garmin-mcp:latest .
```

#### Run the Container

**Basic run (stdio transport):**

```bash
docker run --rm -it \
  -e GARMIN_EMAIL="your-email@example.com" \
  -e GARMIN_PASSWORD="your-password" \
  -e GARMIN_MCP_TRANSPORT="stdio" \
  -v garmin_tokens:/root/.garminconnect \
  garmin-mcp:latest
```

**Network-accessible (Streamable HTTP):**

```bash
docker run --rm -it \
  -e GARMIN_EMAIL="your-email@example.com" \
  -e GARMIN_PASSWORD="your-password" \
  -e GARMIN_MCP_TRANSPORT="streamable-http" \
  -e GARMIN_MCP_HOST="0.0.0.0" \
  -e GARMIN_MCP_PORT="8000" \
  -e GARMIN_MFA_CODE="123456" \
  -e GARMIN_MFA_WAIT_SECONDS="180" \
  -p 8000:8000 \
  -v garmin_tokens:/root/.garminconnect \
  garmin-mcp:latest
```

**Note:** Only include `GARMIN_MFA_CODE` and `GARMIN_MFA_WAIT_SECONDS` if you have MFA enabled on your Garmin Connect account.

The server will be accessible at `http://localhost:8000/mcp`

**Using Docker Compose:**

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  garmin-mcp:
    build: .
    image: garmin-mcp:latest
    container_name: garmin-mcp
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - GARMIN_EMAIL=${GARMIN_EMAIL}
      - GARMIN_PASSWORD=${GARMIN_PASSWORD}
      - GARMIN_MCP_TRANSPORT=streamable-http
      - GARMIN_MCP_HOST=0.0.0.0
      - GARMIN_MCP_PORT=8000
      # Only include MFA variables if MFA is enabled on your Garmin Connect account
      - GARMIN_MFA_CODE=${GARMIN_MFA_CODE}
      - GARMIN_MFA_WAIT_SECONDS=180
    volumes:
      - garmin_tokens:/root/.garminconnect

volumes:
  garmin_tokens:
```

Run with:

```bash
docker-compose up -d
```

### 3. Kubernetes Deployment

#### Prerequisites

- Kubernetes cluster with kubectl configured
- PersistentVolume support (for token storage)

#### Step 1: Create Secrets

Create a Kubernetes Secret with your Garmin credentials:

```bash
kubectl create namespace mcpo  # or your preferred namespace

kubectl create secret generic garmin-secrets \
  --from-literal=email='your-email@example.com' \
  --from-literal=password='your-password' \
  --from-literal=mfa='123456' \
  -n mcpo
```

**Note:** The `mfa` key is only needed if you have MFA enabled on your Garmin Connect account. If MFA is not enabled, omit the `--from-literal=mfa` line. The `mfa` key is only needed for the first run or when tokens expire. You can remove it after tokens are established.

#### Step 2: Create PersistentVolumeClaim

Create `pvc.yaml`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: garmin-tokens
  namespace: mcpo
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

Apply it:

```bash
kubectl apply -f pvc.yaml
```

#### Step 3: Deploy the Application

Create `deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: garmin-mcp
  namespace: mcpo
spec:
  replicas: 1
  selector:
    matchLabels:
      app: garmin-mcp
  template:
    metadata:
      labels:
        app: garmin-mcp
    spec:
      containers:
        - name: garmin-mcp
          image: garmin-mcp:latest  # Replace with your image registry
          imagePullPolicy: Always
          ports:
            - containerPort: 8000
              name: http
          env:
            - name: GARMIN_EMAIL
              valueFrom:
                secretKeyRef:
                  name: garmin-secrets
                  key: email
            - name: GARMIN_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: garmin-secrets
                  key: password
            - name: GARMIN_MCP_TRANSPORT
              value: "streamable-http"
            - name: GARMIN_MCP_HOST
              value: "0.0.0.0"
            - name: GARMIN_MCP_PORT
              value: "8000"
            # Only include MFA variables if MFA is enabled on your Garmin Connect account
            - name: GARMIN_MFA_CODE
              valueFrom:
                secretKeyRef:
                  name: garmin-secrets
                  key: mfa
            - name: GARMIN_MFA_WAIT_SECONDS
              value: "180"
          volumeMounts:
            - name: tokens
              mountPath: /root/.garminconnect
          readinessProbe:
            tcpSocket:
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
          livenessProbe:
            tcpSocket:
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
      volumes:
        - name: tokens
          persistentVolumeClaim:
            claimName: garmin-tokens
```

Apply it:

```bash
kubectl apply -f deployment.yaml
```

#### Step 4: Create Service

Create `service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: garmin-mcp
  namespace: mcpo
spec:
  selector:
    app: garmin-mcp
  ports:
    - name: http
      port: 80
      targetPort: 8000
  type: ClusterIP
```

Apply it:

```bash
kubectl apply -f service.yaml
```

#### Step 5: (Optional) Create Istio HTTPRoute

If using Istio, create `httproute.yaml`:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: garmin-mcp
  namespace: mcpo
spec:
  parentRefs:
    - name: your-gateway
      namespace: istio-system
  hostnames:
    - garmin-mcp.example.com
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /mcp
      backendRefs:
        - name: garmin-mcp
          port: 80
```

Apply it:

```bash
kubectl apply -f httproute.yaml
```

## Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `GARMIN_EMAIL` | Garmin Connect email address | - | Yes |
| `GARMIN_PASSWORD` | Garmin Connect password | - | Yes |
| `GARMIN_MFA_CODE` | 2FA code (only if MFA is enabled) | - | No* |
| `GARMIN_MFA_WAIT_SECONDS` | Seconds to wait for MFA code | `0` | No |
| `GARMINTOKENS` | Path to token storage directory | `~/.garminconnect` | No |
| `GARMIN_MCP_TRANSPORT` | Transport type: `stdio` or `streamable-http` | `http` | No |
| `GARMIN_MCP_HOST` | Bind host for HTTP transport | `0.0.0.0` | No |
| `GARMIN_MCP_PORT` | Port for HTTP transport | `8000` | No |
| `GARMIN_MCP_API_KEY` | Optional API key to secure SSE/HTTP server | - | No |

*Required only if MFA is enabled on your Garmin Connect account, and only on first run or when tokens expire

## Token Management

OAuth tokens are automatically saved to `~/.garminconnect` (or path specified by `GARMINTOKENS`) after successful login. These tokens persist across restarts, eliminating the need for MFA on subsequent runs until they expire.

**For Kubernetes:** Tokens are stored in the PersistentVolumeClaim, so they persist across pod restarts and deployments.

## Authentication

When using the HTTP or SSE transports, the server can be secured by setting the `GARMIN_MCP_API_KEY` environment variable. If set:
- Clients must authenticate by sending the key in either:
  - An `Authorization` header: `Authorization: Bearer <your-api-key>`
  - An `X-API-Key` header: `X-API-Key: <your-api-key>`
  - A query parameter: `?api_key=<your-api-key>`
- Kubernetes health probes (`/healthz` and `/readyz`) and the root path (`/`) remain public and return `200 OK` (returning `{"status": "ok", "service": "garmin-mcp"}`) without authentication.

## Caching & Performance

To optimize responsiveness and prevent hitting Garmin Connect API rate limits, the server utilizes a hybrid caching system:
- **In-Memory Cache**: Active queries and recent data (less than 7 days old) are cached in memory with a 5-minute Time-To-Live (TTL).
- **Disk Cache**: Historical queries (with dates older than 7 days) and completed activities (using `activity_id` or `activityId`) are permanently cached on disk (at `~/.garminconnect/cache/perm/`).
- **Mutation Bypass**: Write and modification operations (e.g. adding weigh-ins, setting blood pressure, uploading workouts) automatically bypass the cache.

Additionally, all Garmin Connect API requests are offloaded to background worker threads. This guarantees that multiple parallel requests from the MCP client are processed efficiently without blocking the main async event loop.

## Troubleshooting

### Login Issues

1. **Invalid credentials**: Verify your email and password are correct
2. **MFA required**: If you have MFA enabled, ensure `GARMIN_MFA_CODE` is set for first run
3. **Token expired**: Delete the token directory and re-authenticate

### Network Issues

1. **Can't connect to server**: Verify the server is binding to `0.0.0.0` (not `127.0.0.1`)
2. **Connection refused**: Check firewall rules and port exposure
3. **404 errors**: Ensure you're using the correct transport type (Streamable HTTP for network access)

### Kubernetes Issues

1. **Pod crash loops**: Check logs with `kubectl logs -n mcpo deployment/garmin-mcp`
2. **Service not accessible**: Verify Service selector matches Deployment labels
3. **Token persistence**: Ensure PVC is properly mounted and has storage available

### Viewing Logs

**Docker:**
```bash
docker logs <container-id>
```

**Kubernetes:**
```bash
kubectl logs -n mcpo deployment/garmin-mcp -f
```

## Available Tools

This server provides 78+ MCP tools. See [TOOLS.md](TOOLS.md) for a complete list organised by category.

## Example Queries

Once connected to the MCP server, you can query your Garmin fitness data using natural language. Here are some example queries you can make:

### Activity Queries

- **"Show me my recent activities"**
  - Uses: `list_activities`
  
- **"What running activities did I do between September 1st and November 6th?"**
  - Uses: `get_activities_by_date` with activity_type="running"
  
- **"Get details for activity ID 204592654"**
  - Uses: `get_activity`
  
- **"Show me the splits for my last run"**
  - Uses: `get_activity_splits`
  
- **"What was the weather during my activity 204592654?"**
  - Uses: `get_activity_weather`

### Health & Wellness Queries

- **"How many steps did I take on November 6th?"**
  - Uses: `get_steps_data`
  
- **"Show me my sleep data for November 5th"**
  - Uses: `get_sleep_data`
  
- **"What was my heart rate on November 6th?"**
  - Uses: `get_heart_rates`
  
- **"Get my body battery data from November 1st to November 6th"**
  - Uses: `get_body_battery`
  
- **"What was my stress level on November 5th?"**
  - Uses: `get_stress_data` or `get_all_day_stress`
  
- **"Show me my resting heart rate for November 6th"**
  - Uses: `get_rhr_day`
  
- **"Get my body composition data for November 6th"**
  - Uses: `get_body_composition`
  
- **"What was my training readiness on November 6th?"**
  - Uses: `get_training_readiness`
  
- **"Show me my hydration data for November 6th"**
  - Uses: `get_hydration_data`
  
- **"Get my SpO2 (blood oxygen) data for November 6th"**
  - Uses: `get_spo2_data`
  
- **"What was my respiration rate on November 6th?"**
  - Uses: `get_respiration_data`

### Training & Performance Queries

- **"What's my VO2 Max and fitness age for November 6th?"**
  - Uses: `get_max_metrics`
  
- **"Get my HRV (Heart Rate Variability) data for November 6th"**
  - Uses: `get_hrv_data`
  
- **"Show me my fitness age data for November 6th"**
  - Uses: `get_fitnessage_data`
  
- **"What was my training effect for activity 204592654?"**
  - Uses: `get_training_effect`
  
- **"Get my hill score from September 1st to November 6th"**
  - Uses: `get_hill_score`
  
- **"Show me my endurance score between September 1st and November 6th"**
  - Uses: `get_endurance_score`

### Device & Gear Queries

- **"List all my Garmin devices"**
  - Uses: `get_devices`
  
- **"What's my primary training device?"**
  - Uses: `get_primary_training_device`
  
- **"Show me the gear I used for activity 204592654"**
  - Uses: `get_activity_gear`

### Challenges & Goals Queries

- **"What are my active goals?"**
  - Uses: `get_goals` with goal_type="active"
  
- **"Show me my personal records"**
  - Uses: `get_personal_record`
  
- **"What badges have I earned?"**
  - Uses: `get_earned_badges`
  
- **"Get my race predictions"**
  - Uses: `get_race_predictions`

### User Profile Queries

- **"What's my full name?"**
  - Uses: `get_full_name`
  
- **"What unit system do I use?"**
  - Uses: `get_unit_system`
  
- **"Show me my user profile"**
  - Uses: `get_user_profile`

### Data Management Queries

- **"Add a weight measurement: 75.5 kg"**
  - Uses: `add_weigh_in`
  
- **"Get my weight measurements from November 1st to November 6th"**
  - Uses: `get_weigh_ins`
  
- **"Add body composition data for November 6th"**
  - Uses: `add_body_composition`

### Training and Diet Recommedations

- **"Prepare me for a marathon with training and diet recommendations"**
  - Uses: `get_training_and_diet_recommendations`
  
- **"I want to improve my running performance, give me training and diet recommendations"**
  - Uses: `get_training_and_diet_recommendations`
  
- **"I want to lose weight - what should I do?"**
  - Uses: `get_training_and_diet_recommendations`

### Complex Queries

The MCP server can handle complex, multi-step queries:

- **"Analyze my training week: show me my activities, sleep quality, and body battery from November 1st to November 6th"**
  - Combines: `get_activities_by_date`, `get_sleep_data`, `get_body_battery`
  
- **"Compare my running performance: get my activities, training effect, and heart rate zones for my last 5 runs"**
  - Combines: `list_activities`, `get_training_effect`, `get_activity_hr_in_timezones`
  
- **"Give me a complete health summary for November 6th: steps, sleep, stress, heart rate, and body battery"**
  - Combines: `get_steps_data`, `get_sleep_data`, `get_stress_data`, `get_heart_rates`, `get_body_battery`

### One‑Pane Summaries and Insights

- **"Show my weekly single-pane summary for last week"**
  - Uses: `get_period_summary` with period="weekly", anchor_date="last week"
  
- **"Fetch a monthly dashboard summary including activities and readiness"**
  - Uses: `get_period_summary` with period="monthly"
  
- **"What are my trends over the last 4 weeks?"**
  - Uses: `get_trends` with start_date, end_date, include=["rhr","hrv","sleep","steps","body_battery"]
  
- **"Detect any recovery red flags this week"**
  - Uses: `detect_anomalies` with heuristic thresholds (defaults sensible)
  
- **"Give me a readiness breakdown for today"**
  - Uses: `get_readiness_breakdown`
  
- **"How complete is my data this month?"**
  - Uses: `get_data_completeness`
  
- **"Hydration target for a 60‑minute run at 28°C, weight 75 kg"**
  - Uses: `get_hydration_guidance` with weight_kg=75, training_minutes=60, temperature_c=28
  
- **"Coach cues for this week"**
  - Uses: `get_coach_cues` with period="weekly"

> Tip: These tools accept natural timeframe phrases like `today`, `yesterday`, `last week`, `this week`, `last month`, `last 28 days`. Ranges automatically clamp to today so mid-week requests never reach into the future.

### Accessing the Server

When deployed with Streamable HTTP transport, the MCP server is accessible at:

- **Local**: `http://localhost:8000/mcp`
- **Kubernetes with Istio**: `https://garmin-mcp.example.com/mcp`
- **Docker**: `http://<container-ip>:8000/mcp`

Configure your MCP client (OpenWebUI, Claude, etc.) to connect to the `/mcp` endpoint for Streamable HTTP transport.

## Security Notes

- **Never commit credentials**: Use environment variables or Kubernetes Secrets
- **Token storage**: Tokens are stored locally/on PVC - ensure proper access controls
- **Network security**: For production, use TLS/HTTPS (terminate at Ingress/Gateway)
- **Secret rotation**: Rotate Garmin password regularly and update secrets accordingly

## License

See [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
