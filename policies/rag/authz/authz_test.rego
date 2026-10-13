package rag.authz_test

import data.rag.authz

# ------------------------------------------------------------------ test people

alice := {"username": "alice", "groups": ["all-staff", "engineering"], "roles": ["rag-user"]}

bob := {"username": "bob", "groups": ["all-staff", "hr"], "roles": ["rag-user"]}

carol := {"username": "carol", "groups": ["all-staff", "executives"], "roles": ["rag-user"]}

dave := {"username": "dave", "groups": ["all-staff", "platform-admins"], "roles": ["rag-user", "rag-admin"]}

worker := {"username": "service-account-ingestion-worker", "groups": [], "roles": ["rag-ingest"]}

contractor := {"username": "zoe", "groups": ["all-staff", "executives", "contractors"], "roles": ["rag-user"]}

# ------------------------------------------------------------------ test documents (Step 11)

remote_work := {"id": 1, "classification": "internal", "acl_groups": ["all-staff"]}

salary_bands := {"id": 3, "classification": "confidential", "acl_groups": ["hr"]}

exec_offsite := {"id": 4, "classification": "restricted", "acl_groups": ["executives"]}

press_release := {"id": 5, "classification": "public", "acl_groups": []}

all_docs := [remote_work, salary_bands, exec_offsite, press_release]

# ------------------------------------------------------------------ actions

test_user_may_search if authz.allow with input as {"principal": alice, "action": "search"}

test_user_may_not_use_admin if {
	not authz.allow with input as {"principal": alice, "action": "admin:ping"}
	authz.reasons == {"action admin:ping requires role rag-admin"} with input as {
		"principal": alice,
		"action": "admin:ping",
	}
}

test_admin_role_comes_through if authz.allow with input as {"principal": dave, "action": "admin:ping"}

test_machine_may_ingest_but_not_search if {
	authz.allow with input as {"principal": worker, "action": "documents:ingest"}
	not authz.allow with input as {"principal": worker, "action": "search"}
}

# Step 33: answers and feedback, for people with rag-user; answers use the search filter
test_user_may_answer_and_rate if {
	authz.allow with input as {"principal": alice, "action": "answer"}
	authz.allow with input as {"principal": alice, "action": "feedback"}
}

test_machine_may_not_answer if not authz.allow with input as {"principal": worker, "action": "answer"}

test_answer_uses_the_search_filter if {
	expected := {"groups": ["all-staff", "engineering"], "classifications": ["internal", "public"]}
	authz.decision.filter == expected with input as {"principal": alice, "action": "answer"}
}

test_unknown_action_denied if not authz.allow with input as {"principal": dave, "action": "delete-everything"}

test_missing_action_denied if not authz.allow with input as {"principal": dave}

test_missing_principal_denied if not authz.allow with input as {"action": "search"}

# ------------------------------------------------------------------ search filter

test_filter_for_alice if {
	expected := {"groups": ["all-staff", "engineering"], "classifications": ["internal", "public"]}
	authz.decision.filter == expected with input as {"principal": alice, "action": "search"}
}

test_clearance_follows_groups if {
	authz.classifications == ["confidential", "internal", "public"] with input as {"principal": bob}
	authz.classifications == ["confidential", "internal", "public", "restricted"] with input as {"principal": carol}
}

test_cap_beats_grant if {
	authz.classifications == ["internal", "public"] with input as {"principal": contractor}
}

test_no_groups_means_nothing if {
	authz.classifications == [] with input as {"principal": worker}
}

# ------------------------------------------------------------------ per-document checks

test_alice_reads if {
	authz.readable_ids == {1, 5} with input as {"principal": alice, "documents": all_docs}
}

test_bob_reads_hr_but_not_exec if {
	authz.readable_ids == {1, 3, 5} with input as {"principal": bob, "documents": all_docs}
}

test_carol_reads_exec if {
	authz.readable_ids == {1, 4, 5} with input as {"principal": carol, "documents": all_docs}
}

test_contractor_in_executives_still_blocked if {
	authz.readable_ids == {1, 5} with input as {"principal": contractor, "documents": all_docs}
}

test_group_match_is_not_enough_without_clearance if {
	# a confidential document shared with all-staff: alice is in the group, but lacks the clearance
	doc := {"id": 9, "classification": "confidential", "acl_groups": ["all-staff"]}
	authz.readable_ids == set() with input as {"principal": alice, "documents": [doc]}
}
