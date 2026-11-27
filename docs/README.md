# Documentation

| Document | For whom | What it covers |
|---|---|---|
| [user-guide.md](user-guide.md) | everyone using the web app | what each role does, step by step |
| [architecture.md](architecture.md) | developers | the parts of the platform and how a request flows through them |
| [api.md](api.md) | developers, integrations | logging in, roles, conventions, every endpoint ([openapi.json](openapi.json)) |
| [database.md](database.md) | developers | design rules, a diagram per area, every table and column |
| [ml.md](ml.md) | data scientists, examiners | the six use cases: data, baselines, networks, results, use in the app |
| [security.md](security.md) | developers, reviewers | the security review, rule by rule, with the tests that check it |
| [performance.md](performance.md) | developers | the speed check on the full dataset and its fixes |
| [demo-scenario.md](demo-scenario.md) | presenters | a 12–15 minute walkthrough through the four roles, and how to prepare it |

The endpoint list in api.md, the table reference in database.md and openapi.json are
generated from the code (`python scripts/generate_docs.py`); the backend tests fail when
they are out of date. The project overview, setup and commands are in the main
[README](../README.md).
