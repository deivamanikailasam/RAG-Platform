# ADR-0004: Run models natively on macOS and all other services in containers (OrbStack)

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** deivamanikailasam

## Context
Linux containers on macOS run inside a VM with no access to Apple's Metal GPU, which MLX
requires. The 128 GB of unified memory is shared by models, the VM and macOS.

## Decision
We will run model servers (mlx-lm, embedder, reranker) natively on macOS, and every other
service in containers on OrbStack. Containers reach models via host.docker.internal (with an
explicit host-gateway mapping for portability). The VM is capped at 24 GB RAM / 8 CPUs; ports are
published on 127.0.0.1 only; data uses named volumes; engine log rotation is 10 MB x 3.

## Alternatives considered
| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Docker Desktop | Vendor-supported | Heavier; licence above small-business limits | OrbStack is lighter for a personal lab |
| Colima | Open source, free | More manual setup | Kept as the fallback |
| Podman | Rootless, no daemon | Compose differences | Not needed for this lab |
| Models in containers | One deployment style | No Metal GPU; far slower | Unworkable for MLX |

## Consequences
+ Models get the full GPU; services stay reproducible and disposable.
+ Mirrors production, where model serving runs on separate GPU nodes behind HTTP.
- Two networks to reason about (host vs VM).
- OrbStack licence required if used commercially.

## Revisit when
A runtime offers Metal access inside containers, or memory pressure requires changing the VM cap.
