# Step 3 decisions
- Runtime: OrbStack (personal use; fast, low idle memory, built-in Kubernetes). Fallback: Colima.
- VM cap: 24 GB RAM, 8 CPUs, because unified memory is shared with the models.
- Architecture: models run natively on macOS (need the Metal GPU); all services run in containers
  and reach models via host.docker.internal.
- Rules: publish ports on 127.0.0.1 only; named volumes for data; log rotation 10m x 3.
