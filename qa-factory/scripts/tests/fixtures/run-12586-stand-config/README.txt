Source: the stand config of run TP1-12586 (testproject1-dev-010 test-harness, qa-factory/config.json, working copy, 28.10.2026),
reduced to what the frontend reader and the host allow-list read: the environment block, test_data.accounts_by_role, and the
single environments[] entry `local-docker` with the flat `frontend_url` the run added by hand (and no `environment.frontend` block).

Replacements: the long note keys, profiles, adapters and the 15 integration blocks are dropped (one integration kept, to show
that a declared key is not a hint candidate); secret_content_patterns reduced to two; env_file points at
testproject1_test_harness/env.fixture (the real file is the git-ignored .env, which this fixture never copies).
env.fixture holds INVENTED values only: http://localhost:5173, http://localhost:8080, qa-user@example.test, the password x.
