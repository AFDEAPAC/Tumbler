# Tumbler — POC extras (merged container toolkit)

Companion POC delivered 2026-05-28. **Updated: the originally separate
`tumbler-container-runtime` + `tumbler-mempool-agent` repos have been
merged into a single monorepo.**

- [`AFDEAPAC/tumbler-container-runtime`](https://github.com/AFDEAPAC/tumbler-container-runtime) (originally drafted as `tumbler-container-toolkit`; renamed to keep the Tumbler product line consistent) —
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
- Source: [`AFDEAPAC/tumbler-container-runtime`](https://github.com/AFDEAPAC/tumbler-container-runtime) (pushed 2026-05-28; HEAD at the stale-gauge fix commit)

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

## Runtime support boundary (added 2026-05-28)

Mapped the toolkit against 13 alibabaHang memory/pin/cgroup/evict
reproducers. Headline: the toolkit covers ~3/13 directly and gives
observability on 10/13; the other ~77% are kernel D-state paths
that need V17.5 amdgpu modparams. Toolkit and kernel patches are
**complementary, not substitutes**.

### A/B verification on 8×MI250X (5 safe reproducers)

| Reproducer | Result |
|---|---|
| `startup_smoke` | Plan hypothesis "toolkit firewall-defaults regression" **falsified** on ROCm 7.0 — 15/15 PASS across {sanity, full-table, L2-min, toolkit-only, toolkit+full} × {32G, 64G, unbounded} memcg |
| `mr_burn_dmabuf` | Toolkit registered 4 GiB HSA reservation correctly; binary failed at `ibv_reg_mr ERRNO=14` (PeerMem absent on ROCm 7.0). DMABUF cap is enforced kernel-side regardless of toolkit. |
| `multistream_combo` | Small-scale 4×128 MB×40 iters: A & B both ~2.8 s. Transient kworker D-state cleared. Agent VRAM gauge tracked workload working set. |
| `dmabuf_validate_hang` | `fake_importer.ko` unbuildable on stock 6.14 (DMA_BUF namespace API moved). Both A (1610 ms) and B (1653 ms) fail at same upstream point. Agent gauges correctly stay flat for host RAM pressure. |
| `cross_cgroup_evict` | 3 containers registered concurrently; per-GPU aggregation gauge correctly partitions `{gpu="0"}` vs `{gpu="1"}`. Pinner failed at `ibv_reg_mr` upstream. |

### Paper analysis (8 D-state-risky reproducers, kernel-only territory)

| Reproducer | Required V17.5 modparam |
|---|---|
| `fixk1_stress` | `bo_sync_wait_max_ms=30000` |
| `rdma_dereg_hang` | `sdma_fence_watchdog_ms=30000` |
| `death_a1_svm_quiesce` | `kfd_wait_max_ms_per_wall=5000` |
| `svm_quiesce_hang` | `kfd_wait_max_ms_per_wall=5000` + `bo_sync_wait_max_ms=30000` |
| `death_a2_bo_sync_wait` | `sdma_fence_watchdog_ms=30000 suballoc_timeout_ms=4000` |
| `stuck_fence_proof` | `bo_sync_wait_max_ms=30000` |
| `sdma_suballoc_hang` | `suballoc_timeout_ms=4000` + `ROCR_SDMA_WRITE_ADDR_FAIL_MS=500` |
| `kfd_wait_events_hang` | `kfd_wait_max_ms_per_wall=5000` |

### Headline conclusion

The Tumbler container toolkit occupies a real and useful niche
(per-container VRAM reservation, evict-warning event fan-out,
Prometheus observability) but is **not** a replacement for the V17.5
amdgpu kernel patches. Production deployment should ship **both**:
install the V17.5 DKMS to bound the kernel D-state paths, then run
`tumbler-runtime` + `tumbler-mempool-agent` to give containers
per-tenant fairness, scoped evict warnings, and observability.

Full mapping table + A/B run logs:
[`s3://home/chun-wan/tumbler-poc-report/index.html`](https://github.com/AFDEAPAC/Tumbler)
section *Runtime support boundary*; raw artefacts under
`s3://home/chun-wan/tumbler-poc-report/runtime-boundary/`.

## Memory Guard core (added 2026-05-28, after upstream-design pivot)

Following customer feedback that destructive kernel patches are not
upstream-friendly, we re-positioned the toolkit as a **non-invasive
container-level memory guard**. Four core mechanisms ship on by default
and require no changes to CLR / ROCr / amdgpu:

1. **fdinfo per-process pin observer** — agent walks
   `/proc/<pid>/fdinfo/<fd>` for every registered container and
   exports per-(container, gpu) gauges. Closes the
   "RDMA pin path was invisible from outside" gap without touching
   the workload.
2. **Admission gate (prestart)** — refuses to register a container
   whose reservation would push a GPU past
   `total × (1 - headroom_ratio)` (default 0.85 threshold).
   `docker create` aborts at the prestart hook with a clear OCI error
   before runc starts the workload, so the kernel never enters the
   eviction path.
3. **Priority preempt picker** — when watermark crosses high, the
   `evict_high` JSON event is routed to the lowest-priority subscriber
   on that GPU (read from spec annotation `tumbler.priority=low|normal|high`)
   instead of broadcasting. High-priority workloads are shielded.
4. **cgroup memory.max + auto K-5 link** — already shipping; prestart
   hook sets `memory.max` from `--memory` and writes
   `amdgpu.pin_max_bytes = memcg.max × 0.75` when K-5 kernel patches
   are present (graceful fallback when not).

The aggressive features (LD_PRELOAD bounded-wait shim, stuck-syscall
SIGKILL watchdog, in-process budget intercept) are downgraded to
**off-by-default opt-in flags** in `internal/config.OptionalConfig`.
See [`docs/GUARD_AND_OPTIONAL.md`](https://github.com/AFDEAPAC/tumbler-container-runtime/blob/main/docs/GUARD_AND_OPTIONAL.md)
for the full design rationale.

### Real-machine validation on 8×MI250X

| Scenario | Result |
|---|---|
| Admission gate refuses 3rd over-commit | PASS — `docker create` returned `tumbler admission gate refused container ...: admission rejected: gpu=0 would exceed admission threshold: effective=32568848384 want=16106127360 threshold=34351349760 (total=68702699520, headroom=50%)` |
| Priority picker shields HIGH | PASS — HIGH subscriber received 0 evict_high events; LOW received 1 evict_high JSON + 1 SIGUSR1 |
| fdinfo observes any registered PID | PASS — host-side vram-stress PID exposed `tumbler_container_gtt_requested_bytes{container="host-fdinfo",gpu="0..7"} 2.17e+06` for all 8 GPUs without workload cooperation |

### New Prometheus metrics

- `tumbler_container_vram_requested_bytes{container, gpu}`
- `tumbler_container_vram_evicted_bytes{container, gpu}`
- `tumbler_container_gtt_requested_bytes{container, gpu}`
- `tumbler_admission_rejects_total{gpu, reason}`

Source commit: `1b778e3..34dc6cb` on
[`AFDEAPAC/tumbler-container-runtime`](https://github.com/AFDEAPAC/tumbler-container-runtime).
Demo logs: [`s3://home/chun-wan/tumbler-poc-report/runtime-boundary/e_guard.tgz`](https://github.com/AFDEAPAC/Tumbler).
