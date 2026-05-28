# Tumbler — POC extras (merged container toolkit)

Companion POC delivered 2026-05-28. **Updated: the originally separate
`tumbler-container-runtime` + `tumbler-mempool-agent` repos have been
merged into a single monorepo.**

- [`AFDEAPAC/tumbler-container-toolkit`](https://github.com/AFDEAPAC/tumbler-container-toolkit) —
  one Go module shipping seven binaries:
  - `tumbler-runtime` — OCI shim wrapping `runc`
  - `tumbler-runtime-hook` — prestart + poststop OCI hook
  - `tumbler-container-cli` — low-level injector (mirrors `nvidia-container-cli`)
  - `tumbler-ctk` — config + CDI + partition + `pool ls`
  - `tumbler-mempool-agent` — per-node daemon (HSA reserved pool, KFD SMI
    subscriber, container registry, Prometheus exporter, IPC broker)
  - `tumbler-shim` — in-container event subscriber
  - `tumbler-vram-stress` — host-side test stressor (HSA cgo)

## Why merge

NVIDIA splits `nvidia-container-toolkit` / `libnvidia-container` /
`nvidia-container-runtime` across multiple distro packages, but the
user-facing model is one tool. Tumbler keeps the binary split (different
processes for systemd / lifetime reasons) but ships them together so:

- **`docker run --runtime=tumbler` is enough** — the prestart hook contacts
  the local agent at `/run/tumbler/agent.sock`, asks for a budget
  (`TUMBLER_RESERVE_BYTES`), and the agent reserves it via HSA cgo before
  the workload starts.
- **EvictWarn events are scoped to the right container.** The agent's
  `internal/registry` knows which GPU each container holds (from
  registration) and only fans out events on those GPUs.
- **Single `go.mod`, single `Makefile`, single CI matrix.**
- **One Helm chart.** The DaemonSet ships everything in one Pod.

## Strategic differentiator (unchanged)

NVIDIA signals VRAM pressure at the unified-memory page-fault level
inside the application. ROCm's KFD evicts entire queues with no
application-visible warning, so a single greedy tenant can stall
co-tenants for tens of seconds before any workload notices. By moving
the early-warning into a privileged userspace daemon (no kernel patch
required — `AMDKFD_IOC_SMI_EVENTS` exists since 2020), Tumbler lets
containers **opt-in to graceful degradation**:

```
Tumbler agent SMI sub  →  EvictWarn JSON  →  /run/tumbler/<cid>.sock  →  tumbler-shim  →  workload drop+retry
```

## Headline results (8×MI250X · ROCm 6.14.14 · kernel 6.14)

- All 8 MI250X GCDs discovered correctly via the ROCm/k8s-device-plugin
  topology parser (ported into `internal/discover/sysfs.go`).
- `docker run --runtime=tumbler ...` triggers the OCI shim; the spec
  rewrite injected `/dev/kfd`, all 8 `/dev/dri/renderD128..D135`, library
  bind-mounts, capabilities, and the prestart + poststop hooks.
- Sparse `AMD_VISIBLE_DEVICES=0,3,7` correctly produced exactly three
  render minors (D128, D131, D135).
- `tumbler-vram-stress` reserved 50 GiB on GPU 0 in **334 µs**; the agent's
  watermark poller crossed the high threshold on the next 50 ms tick and
  broadcast an `evict_high` JSON event to the registered shim subscriber.
- **Auto-register end-to-end**: `docker run --runtime=tumbler
  -e TUMBLER_RESERVE_BYTES=2147483648 -e AMD_VISIBLE_DEVICES=0` →
  `tumbler-ctk pool ls` showed the container with reserved 2 GiB on GPU 0;
  Prom metric `tumbler_pool_container_reserved_bytes{gpu="0"} = 2.147e9`;
  `/run/tumbler/<cid>.sock` opened. On container exit the poststop hook
  unregistered cleanly and the metric returned to zero.

## Linkage to existing Tumbler firewall

| Existing tumbler patch | POC integration |
|---|---|
| K-5 cgroup-aware pin budget (amdgpu) | `internal/cgroup/AMDGPUCgroup.SetPinBudget` writes `amdgpu.pin_max_bytes` from prestart hook; gracefully no-ops on stock kernel |
| ROCr `ROCR_SIGNAL_WAIT_MAX_MS`, `ROCR_SERVICE_SURVIVAL` | `internal/modifier/EnvMod` injects `TumblerFirewallDefaults` into every container by default |
| CLR `HIP_MAX_SIGNAL_WAIT` | Same default injection |
| Reproducers in alibabaHang | Phase 4 demo grew from `vram_overcommit/` style stress |

## Deliverables snapshot

- Single-file dark-theme HTML report (per the user's review-format
  preference): `s3://home/chun-wan/tumbler-poc-report/index.html`
- Demo logs (4 files): `s3://home/chun-wan/tumbler-poc-report/logs/`
- Merged repo bundle + push script:
  `s3://home/chun-wan/tumbler-poc-report/bundles/tumbler-container-toolkit.bundle`
- Source: `git@github.com:AFDEAPAC/tumbler-container-toolkit.git`
  (creation pending — `push_to_afdeapac.ps1` ready to run once the empty
  repo exists in the AFDEAPAC org)

## Phase status

All 11 phases (7 POC + 4 merge) are green. Phase 3 fell back to
`memory.max` only because the test host runs stock kernel 6.14 without
the K-5 patch — the fallback is detected and logged at runtime; no source
change required when the K-5 kernel is rolled out.

## Future work

1. CRI-O / containerd runtime plug (currently only Docker is `tumbler-ctk
   runtime configure`-able).
2. Replace the 100 ms watermark poll with KFD `mem_info_vram_used`
   *uevent* once upstream lands a notifier.
3. Prefer-MIG-style spatial partitioning on MI300X (CPX/QPX) — driven by
   the existing `tumbler-ctk partition set`.
4. GPU Operator analogue: bundle `tumbler-mempool-agent` + the existing
   `ROCm/k8s-device-plugin` into a single Helm chart.
5. Auto-tune the `evict_high` watermark per workload via the agent's
   metrics history (Tumbler-meets-AI follow-up).
