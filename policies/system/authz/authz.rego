# METADATA
# title: Protect OPA's own API
# description: |
#   Only rag-api (holding OPA_API_TOKEN) may ask for decisions, and nobody may upload or change
#   policies or data over the API: policies change only through Git and a redeploy.
package system.authz

default allow := false

# The health endpoint is open (no secrets in it) so probes can use it.
allow if {
	input.method == "GET"
	input.path == ["health"]
}

# Metrics: GET /metrics, with Prometheus's own token (Step 20). It can read numbers, nothing else.
allow if {
	input.identity == opa.runtime().env.OPA_METRICS_TOKEN
	input.method == "GET"
	input.path == ["metrics"]
}

# Decisions: POST to /v1/data/rag/authz/..., with the shared token.
allow if {
	input.identity == opa.runtime().env.OPA_API_TOKEN
	input.method == "POST"
	array.slice(input.path, 0, 4) == ["v1", "data", "rag", "authz"]
}
