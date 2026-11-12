Source: the stand config of run TP1-12586 (testproject1-dev-010 test-harness, qa-factory/config.json, working copy, 28.10.2026), reduced
the same way as ../run-12586-stand-config (the long note keys, profiles, adapters and integration blocks dropped; two secret patterns;
env_file points at testproject1_test_harness/env.fixture; no value of the real .env is copied).

config.before.json  the file as the story found it: environment.user_key AUTH_USERNAME, secret_keys [AUTH_PASSWORD], one environments[]
                    entry with no frontend_url.
config.drifted.json the file after the by-hand changes of the run (the 12:38 swap of t-1497 and the flat field):
                    environment.user_key QA_SECOND_USER_EMAIL, secret_keys [QA_SECOND_USER_PASSWORD], environments[0].frontend_url
                    http://localhost:5173 (an invented address).
Everything else is byte for byte the same in the two files; the test builds the other worlds (a recorded write, a runtime probe entry)
on top of them.
