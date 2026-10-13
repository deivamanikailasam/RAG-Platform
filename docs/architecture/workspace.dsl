/*
 * C4 model of the RAG platform (Step 36), as code: Structurizr DSL.
 * Render: docker run --rm -p 8080:8080 -v "$PWD/docs/architecture:/usr/local/structurizr" structurizr/lite
 * (or paste into https://structurizr.com/dsl). The guide's C4 figures are drawn from this model.
 */
workspace "RAG platform" "Project 0: the shared foundation for RAG projects" {

    model {
        employee = person "Employee" "Asks questions in a chat client or tool"
        owner = person "Document owner" "Publishes documents and decides their access"
        operator = person "Platform operator" "Runs, monitors and audits the platform"

        idp = softwareSystem "Identity provider" "Keycloak (or the company IdP): sign-in, groups" "External"
        sources = softwareSystem "Document sources" "Wikis, file shares, ticketing: where documents live" "External"
        providers = softwareSystem "Model providers" "Local MLX/TEI models, or hosted APIs through the gateway" "External"

        rag = softwareSystem "RAG platform" "Answers questions from permitted documents, with citations" {
            api = container "rag-api" "Search, answers, feedback; token, policy and audit checks" "Python, FastAPI, rag-core"
            worker = container "ingestion-worker" "Parse, redact, chunk, enrich, embed, index" "Python, rag-core"
            gateway = container "LLM gateway" "Model routing, budgets, fallbacks, logs" "LiteLLM"
            opa = container "Policy engine" "Who may do and see what" "OPA"
            bao = container "Secrets" "Dynamic database logins, keys" "OpenBao"
            pg = container "Postgres" "Documents, chunks (pgvector + full text, RLS), manifest, audit log" "PostgreSQL 16"
            engines = container "Search engines (optional)" "Vector and keyword engines" "Qdrant, OpenSearch"
            valkey = container "Valkey" "Job queue, conversation memory, answer cache" "Valkey"
            s3 = container "Object storage" "Original documents (versioned), audit anchors, backups" "S3 (SeaweedFS)"
            obs = container "Observability" "Traces, metrics, logs, LLM traces" "OTel, Prometheus, Grafana, Tempo, Loki, Langfuse"
        }

        employee -> api "Asks; reads cited answers" "HTTPS + bearer token"
        owner -> sources "Publishes, sets access"
        operator -> obs "Watches, investigates"
        api -> idp "Verifies tokens (JWKS)"
        api -> opa "Decides and post-checks"
        api -> pg "Searches (as the tenant), writes audit events"
        api -> engines "Searches (optional)"
        api -> valkey "Memory, cache"
        api -> gateway "Embeds, reranks, generates"
        api -> bao "Reads short-lived credentials (agent sidecar)"
        worker -> sources "Pulls changed documents"
        worker -> s3 "Stores originals"
        worker -> pg "Indexes chunks, manifest"
        worker -> valkey "Takes jobs"
        worker -> gateway "Embeds, enriches"
        gateway -> providers "Calls models"
        api -> obs "Spans, metrics" "OTLP"
        worker -> obs "Spans, metrics" "OTLP"
    }

    views {
        systemContext rag "Context" {
            include *
            autoLayout lr
        }
        container rag "Containers" {
            include *
            autoLayout lr
        }
        styles {
            element "Person" {
                shape person
            }
            element "External" {
                background #94a3b8
            }
        }
    }
}
