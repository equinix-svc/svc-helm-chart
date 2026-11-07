#!/usr/bin/env bash
# render-day0.sh [--base64] - render day0/$DAY0_FILE (default day0-ai-gateway-advanced.yaml; day0-ai-gateway-basic.yaml for BASIC) the way the Equinix portal does, for platforms
# that do not (VMware OVA). Values come from environment variables; unset ones render empty.
#   hostname userName publicKey adminPwd adminPassword ipAddressWithCidr gateway
#   K3S_ROLE K3S_SERVER_URL K3S_TOKEN K3S_TLS_SAN
# Example: userName=fred publicKey="$(cat ~/.ssh/id_rsa.pub)" K3S_ROLE=single scripts/render-day0.sh --base64
# --base64 prints a single line, ready for the OVA "user-data" property.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export hostname userName publicKey adminPwd adminPassword ipAddressWithCidr gateway K3S_ROLE K3S_SERVER_URL K3S_TOKEN K3S_TLS_SAN GROQ_API_KEY GEMINI_API_KEY LITELLM_MASTER_KEY LANGFUSE_ADMIN_EMAIL LANGFUSE_ADMIN_PASSWORD STACK_REF STACK_TOKEN
OUT="$(perl -pe 's/\[\(\$\{(\w+)\}\)\]/$ENV{$1} \/\/ ""/ge' < "$ROOT/day0/${DAY0_FILE:-day0-ai-gateway-advanced.yaml}")"
if grep -qE '\[\(|\[\[' <<<"$OUT"; then echo "unrendered placeholder left in the output" >&2; exit 1; fi
if [ "${1:-}" = "--base64" ]; then printf '%s\n' "$OUT" | base64 -w0; echo; else printf '%s\n' "$OUT"; fi
