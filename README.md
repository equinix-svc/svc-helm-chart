# svc-helm-daihub

AI gateway stack for a single k3s node, as **one file**: [`ai-gateway.yaml`](ai-gateway.yaml). It runs on the plain `k3s-node` image of [svc-ne-byoi-builder](https://github.com/equinix-svc/svc-ne-byoi-builder) (Equinix Network Edge BYOI) and works on any k3s with Traefik and the local-path StorageClass. There are no custom container images and no registry to maintain. It has been validated statically (section 7) but **not yet deployed on a device**, so first-boot behaviour is untested.

## 1. Stack

| Area | Component | How it is deployed |
|---|---|---|
| Gateway | LiteLLM 1.108.0 | public OCI chart `ghcr.io/berriai/litellm-helm` (release `ai`, Service `ai-litellm:4000`) |
| Observability | Langfuse 4.75 (web, worker) | public chart `langfuse` 2.2.3 |
| Guardrails | Presidio analyzer + anonymizer | `mcr.microsoft.com/presidio-*`, plain Deployments |
| | LLM Guard: DeBERTa v3 prompt injection, secrets | `python:3.12-slim`, code in a ConfigMap, `llm-guard` on CPU-only PyTorch installed on first start |
| RAG | Qdrant 1.20 | public chart `qdrant` 1.20.0 |
| | rag-service: fastembed `bge-small-en-v1.5`, ingest from S3 | `python:3.12-slim`, code in a ConfigMap |
| Data | Postgres 16 (databases `litellm`, `langfuse`), Redis 7, ClickHouse 26.8 | official images, plain Deployments |
| S3 | SeaweedFS all-in-one (buckets `langfuse`, `rag-docs`) | shipped by the Langfuse chart; replaces MinIO, whose images are no longer published |

Only LiteLLM is exposed, on 80/443 through Traefik. Everything else stays inside the cluster. Langfuse's own Postgres, Redis and ClickHouse sub-charts are turned off (its ClickHouse needs an operator and a three-node Keeper, too heavy for one node), so Langfuse uses the shared Postgres, Redis and ClickHouse above.

## 2. Quick start

| Step | What |
|---|---|
| 1. VM image | Plain `k3s-node` image (`k3s-node.qcow2`) from [svc-ne-byoi-builder](https://github.com/equinix-svc/svc-ne-byoi-builder). Portal settings: `docs/portal-values.md` in that repo. |
| 2. Container images | None to build: all images are public. |
| 3. Day 0 file | [`day0/day0-ai-gateway-basic.yaml`](day0/day0-ai-gateway-basic.yaml) for a single node with two parameters, [`day0/day0-ai-gateway-advanced.yaml`](day0/day0-ai-gateway-advanced.yaml) to join a cluster or set credentials. |
| 4. Parameters | BASIC: `GROQ_API_KEY` and `GEMINI_API_KEY`, none strictly required (set them for the models to answer). Full list: [Day 0 templates](#3-day-0-templates). |

ACL: allow 22 and 80/443. First start takes about 10 minutes (see First start).

## 3. Day 0 templates

Both templates are the Equinix Network Edge Day 0 for the unchanged `k3s-node.qcow2` (portal settings in `docs/portal-values.md` of svc-ne-byoi-builder). They do what that image's own Day 0 does (hostname, static network, portal user, k3s), then on a `single` node or the first `server`, once k3s is Ready:

1. generate the two Secrets (see 4. How it works) with random values, except the keys you pass in, and write the ones you need to `/etc/ai-gateway/credentials.env` (root only);
2. download `ai-gateway.yaml` from this repo into `/var/lib/rancher/k3s/server/manifests/`, where k3s's Helm controller deploys it.

| Template | Use | Portal parameters |
|---|---|---|
| [`day0/day0-ai-gateway-basic.yaml`](day0/day0-ai-gateway-basic.yaml) | **BASIC**: single node, everything else fixed or generated | 2, both optional |
| [`day0/day0-ai-gateway-advanced.yaml`](day0/day0-ai-gateway-advanced.yaml) | **ADVANCED**: cluster join, chosen credentials, pinned repo version | 11, all optional |

Equinix predefined (both): `hostname` `userName` `publicKey` `adminPwd` `ipAddressWithCidr` `gateway`. Declare every other variable as a custom parameter in the portal. Render locally with `DAY0_FILE=<file> scripts/render-day0.sh`. Log: `/var/log/day0.log`.

### Parameters

The **BASIC** and **ADVANCED** columns show whether the parameter is required in that template: `yes`, `no`, or `-` (not used). **Default** is what the template uses when a parameter that is not required is left empty. BASIC fixes the unused ones to their default.

| Parameter | BASIC | ADVANCED | Default | Example (paste in the portal) | Meaning |
|---|---|---|---|---|---|
| `GROQ_API_KEY` | no (for Groq models) | no (for Groq models) | empty | `gsk_AbCdEf1234567890` | Groq API key. |
| `GEMINI_API_KEY` | no (for Gemini models) | no (for Gemini models) | empty | `AIzaSyAbCdEf1234567890` | Gemini API key. |
| `LITELLM_MASTER_KEY` | - | no | generated | `sk-lab-0123456789abcdef` | LiteLLM admin key. |
| `LANGFUSE_ADMIN_EMAIL` | - | no | `admin@ai-gateway.local` | `admin@example.com` | Langfuse first user. |
| `LANGFUSE_ADMIN_PASSWORD` | - | no | generated | `ChangeMe-2026` | Langfuse first user password. |
| `K3S_ROLE` | - | no | `single` | `single` | `single`: standalone node. `server`: control-plane node. `agent`: k3s worker node that joins an existing cluster; the stack is not installed on it. |
| `K3S_SERVER_URL` | - | no (agent only) | empty | `https://10.0.0.5:6443` | URL used by an agent to join the k3s cluster. Empty for `single` or the first `server`. |
| `K3S_TOKEN` | - | no (agent only) | empty | `K10abc123def456::server:789xyz` | Secret used to join the k3s cluster. |
| `K3S_TLS_SAN` | - | no | empty | `203.0.113.20` | Extra API certificate name or IP. |
| `STACK_REF` | - | no | `main` | `main` | Branch or tag of this repo to fetch. Pin a tag for repeatable boots. |
| `STACK_TOKEN` | - | no | empty | `github_pat_11ABCDEF0xxxxxxxx` | Read-only GitHub token, only for a private fork. |

ACL: allow 22 and 80/443. Langfuse, Qdrant and S3 are not exposed.

## 4. How it works

```
client -> Traefik :80/:443 -> LiteLLM (ai-litellm:4000)
            pre-call : rag-augment (opt-in) -> rag-service -> Qdrant + SeaweedFS
                       llm-guard -> llm-guard service (prompt injection blocks, secrets redacted)
                       presidio-pre-call -> Presidio (PII masked)
            model    : llm-pool = Groq + Gemini, usage-based routing
            post-call: llm-guard (secrets), presidio-post-call (PII)
            traces   : Langfuse (web -> Postgres, ClickHouse, Redis, SeaweedFS)
```

| Feature | Behaviour |
|---|---|
| Guardrails | LiteLLM loads two custom modules from a ConfigMap (`llm_guard_guardrail.py`, `rag_augment.py`) and uses its native Presidio integration. |
| Injection gate | DeBERTa must flag the text and explicit injection wording must be present before a request is blocked, to avoid false positives on ordinary instructions. |
| RAG | Opt-in per request with `"guardrails": ["rag-augment"]`. Documents (`.txt`, `.md`) go in bucket `rag-docs` and are ingested into Qdrant collection `knowledge-base`. |
| Secrets | None are in `ai-gateway.yaml`. Day 0 creates two Secrets in namespace `ai-gateway`: `ai-secrets` and `litellm-env`. The S3 password is generated by the Langfuse chart. |
| Config source | `ai-gateway.yaml` is generated from `ai-gateway.yaml.in` and `src/` by `scripts/build.py`. |

| Secret | Keys |
|---|---|
| `ai-secrets` | `POSTGRES_USER` `POSTGRES_PASSWORD` `REDIS_PASSWORD` `CLICKHOUSE_PASSWORD` `LANGFUSE_SALT` `LANGFUSE_ENCRYPTION_KEY` (64 hex) `LANGFUSE_NEXTAUTH_SECRET` `LANGFUSE_PUBLIC_KEY` `LANGFUSE_SECRET_KEY` `LANGFUSE_INIT_USER_EMAIL` `LANGFUSE_INIT_USER_PASSWORD` |
| `litellm-env` | `LITELLM_MASTER_KEY` `REDIS_PASSWORD` `GROQ_API_KEY` `GEMINI_API_KEY` `LANGFUSE_PUBLIC_KEY` `LANGFUSE_SECRET_KEY` (same values as in `ai-secrets`) |

## 5. First start

| Component | What happens |
|---|---|
| LLM Guard | Installs CPU PyTorch and `llm-guard` into its volume and downloads the DeBERTa weights: about 10 minutes and a few GB. Its startup probe allows 30 minutes. Later restarts reuse the volume. |
| rag-service | Installs its packages and downloads the embedding model the same way (smaller). |
| LiteLLM, Langfuse, databases | Wait for each other through probes and retries. Expect several restarts in the first minutes. |

## 6. Use

```bash
sudo cat /etc/ai-gateway/credentials.env            # master key, Langfuse login (when installed by Day 0)
curl -k https://<ip>/v1/chat/completions -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"llm-pool","messages":[{"role":"user","content":"hi"}]}'
# Langfuse UI: ssh -L 3000:localhost:3000 <ip>, then on the node: sudo k3s kubectl -n ai-gateway port-forward svc/langfuse-web 3000
# RAG: add .txt/.md files to bucket rag-docs, then ingest
sudo k3s kubectl -n ai-gateway exec deploy/rag-service -- python -c \
  "import httpx;print(httpx.post('http://localhost:8000/ingest',json={},timeout=600).json())"
```

## 7. What was tested

- The Qdrant (1.20.0), Langfuse (2.2.3) and LiteLLM (1.108.0) charts render with `helm template` using the values in this file, and every image they use exists (`scripts/validate.sh`).
- A throwaway k3s accepted all 28 resources, including the three `HelmChart`s, in a server-side dry run.
- The LiteLLM guardrail modules import under the real LiteLLM 1.108.0 image, and their hook signatures match.
- Both Day 0 templates (about 12 KB each) render and pass a shell syntax check.

## 8. Findings and limits

- **Fail open:** the LLM Guard and RAG modules let a request through unchanged (logged) if their service is unreachable, so injection blocking applies only while LLM Guard answers. How LiteLLM's native Presidio hooks behave when Presidio is down is untested.
- **Floating tags:** `presidio-*:latest`, `python:3.12-slim`, and the packages installed at first start (`llm-guard`, `torch`) can change between boots. Pin them once a deployment is validated.
- **Model names:** the Groq and Gemini names in `src/litellm/config.yaml` come from an earlier lab config and may be stale.
- **Day 0 size:** the Equinix portal limit is 20,000 characters; the template is about 12 KB.
- **Not provided:** TLS certificate beyond Traefik's default, volume backups, and authentication in front of LiteLLM's `/ui` other than its own login.
- **Internet:** the node needs outbound internet at first boot (GitHub, container registries, PyPI, Hugging Face).

## 9. Build and validate

Edit `ai-gateway.yaml.in` and the files under `src/`, then run `scripts/validate.sh`. It builds `ai-gateway.yaml` and renders every chart with `helm template` in Docker. Commit both the sources and the generated file.
