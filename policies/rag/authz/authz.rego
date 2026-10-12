# METADATA
# title: RAG platform authorisation
# description: |
#   Who may DO what (actions) and who may SEE which documents (groups + classification).
#   Mappings live in data.json next to this file, so access changes don't need code changes.
package rag.authz

# Classification levels, lowest to highest (same values as the documents table, Step 11).
levels := {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}

# Missing fields become empty values, never "undefined": an undefined value can silently skip a
# deny rule, and a skipped deny rule means ALLOW. (A test caught exactly this bug.)
principal := object.get(input, "principal", {})

roles := object.get(principal, "roles", [])

groups := object.get(principal, "groups", [])

# ---------------------------------------------------------------- actions: what may you DO?

# Every reason to refuse. The request is allowed only if this set is empty (deny by default).
reasons contains msg if {
	action := object.get(input, "action", "<missing>")
	not data.rag.authz.action_roles[action]
	msg := $"unknown action: {action}"
}

reasons contains msg if {
	required := data.rag.authz.action_roles[input.action]
	not required in roles
	msg := $"action {input.action} requires role {required}"
}

default allow := false

allow if {
	data.rag.authz.action_roles[input.action] # a known action, AND
	count(reasons) == 0 # no reason to refuse
}

# ---------------------------------------------------------------- documents: what may you SEE?

# Highest level any of your groups grants. No known groups: -1, so nothing at all (fail closed).
default clearance := -1

clearance := max({lvl |
	some g in groups
	lvl := levels[data.rag.authz.group_clearance[g]]
})

# Some groups CAP clearance whatever else you belong to (a contractor in "executives" still
# only reaches "internal"). Caps always win over grants.
effective_clearance := min({clearance} | caps) if {
	caps := {lvl |
		some g in groups
		lvl := levels[data.rag.authz.capped_groups[g]]
	}
	count(caps) > 0
} else := clearance

# Classifications you may read, e.g. ["internal", "public"].
classifications := sort([c | some c, lvl in levels; lvl <= effective_clearance])

# One document: allowed classification AND (public OR shares a group with you).
can_read(doc) if {
	doc.classification in classifications
	doc.classification == "public"
}

can_read(doc) if {
	doc.classification in classifications
	some g in doc.acl_groups
	g in groups
}

# ---------------------------------------------------------------- what services ask for

# METADATA
# description: Before searching. May this caller act, and which filter must the query apply?
# entrypoint: true
decision := {
	"allow": allow,
	"reasons": sort([r | some r in reasons]),
	"filter": {"groups": sort([g | some g in groups]), "classifications": classifications},
}

# METADATA
# description: After searching. Re-check each candidate with the full rule (defence in depth).
# entrypoint: true
readable_ids contains doc.id if {
	some doc in input.documents
	can_read(doc)
}
