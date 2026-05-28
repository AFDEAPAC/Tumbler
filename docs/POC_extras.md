# Tumbler — POC extras (container runtime + memory pool agent)

Companion POC delivered 2026-05-28. Two new AFDEAPAC repos extend the
original three-layer Tumbler firewall (CLR / ROCr / amdgpu) with the
container-platform tier:

- [`AFDEAPAC/tumbler-container-runtime`](https://github.com/AFDEAPAC/tumbler-container-runtime) —
  OCI runtime + CDI generator + cgroup + partition + experimental MPS-like.
  Mirrors the **full feature set** of NVIDIA's `nvidia-container-toolkit`
  (`nvidia-container-runtime` / `nvidia-container-cli` / `nvidia-ctk` /
  GPU-feature-discovery) for ROCm.
- [`AFDEAPAC/tumbler-mempool-agent`](https://github.com/AFDEAPAC/tumbler-mempool-agent) —
  per-node Go + cgo daemon. Pre-allocates an HSA reserved pool, polls
  sysfs VRAM watermarks, subscribes to KFD's `AMDKFD_IOC_SMI_EVENTS`
  ioctl, broadcasts JSON evict warnings to per-container Unix sockets,
  serves Prometheus metrics on `:9410`. **The evict-pre-warn channel has
  no NVIDIA equivalent** — KFD's whole-queue eviction is otherwise invisible
  to userspace until the queue restarts.

## Strategic differentiator

NVIDIA signals VRAM pressure at the unified-memory page-fault level inside
the application. ROCm's KFD evicts entire queues with no application-visible
warning, so a single greedy tenant can stall co-tenants for tens of
seconds before any workload notices. By moving the early-warning into a
privileged userspace daemon (no kernel patch required — `AMDKFD_IOC_SMI_EVENTS`
exists since 2020), Tumbler lets containers **opt-in to graceful
degradation**:

```
Tumbler agent SMI sub  →  EvictWarn JSON  →  /run/tumbler/<cid>.sock  →  tumbler-shim  →  workload drop+retry
```

## POC headline result (8×MI250X · ROCm 6.14.14 · kernel 6.14)

- All eight MI250X GCDs discovered correctly via the ROCm/k8s-device-plugin
  topology parser (ported into `internal/discover/sysfs.go`).
- `docker run --runtime=tumbler ...` triggers the OCI shim; the spec
  rewrite injected `/dev/kfd`, all 8 `/dev/dri/renderD128..D135`, library
  bind-mounts, capabilities, and the prestart hook.
- Sparse `AMD_VISIBLE_DEVICES=0,3,7` correctly produced exactly three
  render minors (D128, D131, D135).
- `tumbler-vram-stress` reserved 50 GiB on GPU 0 in **334 µs**; the agent's
  watermark poller crossed the high threshold on the next 50 ms tick and
  broadcast an `evict_high` JSON event to the registered shim subscriber
  before the kernel evicted any queue.
- Prometheus exporter (`tumbler_gpu_vram_used_bytes`,
  `tumbler_kfd_evict_total`, `tumbler_evict_warn_lead_time_ms` histogram,
  `tumbler_pool_reserved_bytes`, …) live on `:9410`.

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
- Demo logs at `s3://home/chun-wan/tumbler-poc-report/logs/`
- Source: `git@github.com:AFDEAPAC/tumbler-container-runtime.git`,
  `git@github.com:AFDEAPAC/tumbler-mempool-agent.git`

## Phase status

All seven plan phases are green. Phase 3 fell back to `memory.max` only
because the test host runs stock kernel 6.14 without the K-5 patch — the
fallback is detected and logged at runtime; no source change required when
the K-5 kernel is rolled out.

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
