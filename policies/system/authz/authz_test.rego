package system.authz_test

import data.system.authz

token_env := {"env": {"OPA_API_TOKEN": "s3cret", "OPA_METRICS_TOKEN": "m3trics"}}

decision_call := {"identity": "s3cret", "method": "POST", "path": ["v1", "data", "rag", "authz", "decision"]}

test_rag_api_may_ask_for_decisions if {
	authz.allow with input as decision_call with opa.runtime as token_env
}

test_wrong_token_refused if {
	wrong := object.union(decision_call, {"identity": "guess"})
	not authz.allow with input as wrong with opa.runtime as token_env
}

test_no_policy_uploads if {
	upload := {"identity": "s3cret", "method": "PUT", "path": ["v1", "policies", "rag"]}
	not authz.allow with input as upload with opa.runtime as token_env
}

test_other_data_hidden if {
	everything := object.union(decision_call, {"path": ["v1", "data"]})
	not authz.allow with input as everything with opa.runtime as token_env
}

test_health_is_open if authz.allow with input as {"method": "GET", "path": ["health"]}

test_prometheus_may_read_metrics if {
	scrape := {"identity": "m3trics", "method": "GET", "path": ["metrics"]}
	authz.allow with input as scrape with opa.runtime as token_env
}

test_metrics_token_cannot_ask_for_decisions if {
	ask := object.union(decision_call, {"identity": "m3trics"})
	not authz.allow with input as ask with opa.runtime as token_env
}

test_api_token_cannot_read_metrics if {
	scrape := {"identity": "s3cret", "method": "GET", "path": ["metrics"]}
	not authz.allow with input as scrape with opa.runtime as token_env
}
