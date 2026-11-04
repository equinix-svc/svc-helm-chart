#!/usr/bin/env bash
# validate.sh - build ai-gateway.yaml, then render every HelmChart in it with `helm template` (Docker only).
# Output: rendered manifests in build/rendered/<name>.yaml. Fails on any chart or values error.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT/scripts/build.py"
OUT="$ROOT/build/rendered"; mkdir -p "$OUT"
python3 -I - "$ROOT" <<'PY'
import sys, yaml, pathlib
root = pathlib.Path(sys.argv[1]); out = root / "build/rendered"
for d in yaml.safe_load_all((root / "ai-gateway.yaml").read_text()):
    if d and d["kind"] == "HelmChart":
        s = d["spec"]; n = d["metadata"]["name"]
        (out / f"{n}.values.yaml").write_text(s.get("valuesContent", ""))
        (out / f"{n}.meta").write_text(f"{n}|{s.get('repo','')}|{s['chart']}|{s['version']}|{s['targetNamespace']}\n")
PY
for meta in "$OUT"/*.meta; do
  IFS='|' read -r name repo chart version ns < "$meta"
  echo "==> helm template $name ($chart $version)"
  if [ -n "$repo" ]; then SRC=(--repo "$repo" "$chart"); else SRC=("$chart"); fi
  docker run --rm -v "$OUT:/w" -w /w alpine/helm:latest template "$name" "${SRC[@]}" --version "$version" \
    --namespace "$ns" -f "/w/$name.values.yaml" --api-versions clickhouse.com/v1alpha1/ClickHouseCluster \
    > "$OUT/$name.yaml"
  echo "    $(grep -c '^kind:' "$OUT/$name.yaml") objects"
done
echo "OK"
