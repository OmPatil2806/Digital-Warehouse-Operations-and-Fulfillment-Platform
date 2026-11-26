# Security

Review of the platform against the security architecture of the project document
(section 8.5), done in Phase 10. Each rule, how it is met, and the test that keeps it so.

## Checklist

| Rule (project document 8.5) | How it is met | Checked by |
|---|---|---|
| Passwords stored only as bcrypt hashes | `pwdlib` bcrypt, cost 12 (`BCRYPT_ROUNDS`); unknown emails take as long as wrong passwords, so login timing does not reveal accounts | `test_security.py`, `test_auth_service.py` |
| Short-lived access tokens with refresh tokens | 30-minute JWT in memory (never in `localStorage`); refresh token in an `httpOnly`, `SameSite=Lax` cookie limited to `/api/v1/auth`, `Secure` outside development; rotated on every use, and reuse of an old one logs the user out everywhere | `test_api_auth.py`, `apiClient.refresh.test.ts`, `frontend/tests/appFlows.test.tsx` |
| Role-based permission checks on every protected endpoint | Every endpoint except `GET /health` and `POST /auth/login`, `/refresh`, `/logout` requires a valid token; roles are checked per endpoint (manager, staff, admin, customer scope) | `test_security_hardening.py` (fails if a new endpoint has no login check), the role tests of each module, `backend/tests/integration/` |
| Input validation on client (Zod) and server (Pydantic) | Every request body and query is a Pydantic model with limits; forms use Zod schemas | API tests per module, form tests |
| CORS restricted to the frontend origin | Exact origins from `CORS_ORIGINS` only (`*` and malformed values are refused at start-up); only the methods and headers the web app uses | `test_security_hardening.py` |
| Secrets in environment variables, never committed | `.env` is git-ignored; the app refuses to start outside development/test with the default or a short `SECRET_KEY`; demo logins cannot be created outside development/test | `test_security_hardening.py`, `test_seed_database.py` |
| Audit logs for critical actions; no tokens or passwords in logs | Every change is recorded with who made it; logs name user ids, never passwords or tokens; refresh tokens are stored only as hashes | `test_audit.py`, code check with Ruff's security rules |

## Added in Phase 10

- **Failed-login limit**: 5 wrong passwords within 15 minutes lock the account for 15
  minutes (HTTP 429 with `Retry-After`; the login page shows "Try again in 15 minutes").
  A single client IP gets 20 tries across all accounts. Unknown emails are counted like
  real ones, so the lockout does not reveal which accounts exist. Settings:
  `LOGIN_MAX_FAILURES`, `LOGIN_WINDOW_MINUTES`, `LOGIN_LOCKOUT_MINUTES`.
- **Security headers** on every API response: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'none'; frame-ancestors
  'none'` (not on `/docs` and `/redoc`, which load their scripts from a CDN),
  `Referrer-Policy: no-referrer`, `Permissions-Policy`, `Cache-Control: no-store` on the
  auth endpoints, and `Strict-Transport-Security` when served over HTTPS.
- **Clean server errors**: an unexpected error returns
  `{"detail": "Something went wrong on the server. Please try again later (reference
  3f9c0a1b2d4e)"}`. The stack trace goes only to the server log, under the same
  reference.
- **Code checks**: Ruff's security rules (`S`, the checks of Bandit) run on the backend
  and the scripts in Backend CI. The few findings are documented where they are allowed
  (for example the development default key, which production refuses).
- **Dependency checks**: the Security workflow runs `pip-audit` on the backend and ML
  packages and `npm audit` on the frontend whenever dependencies change and every
  Monday. Results at the time of the review: no known vulnerabilities in Python packages
  or in the web app's production bundle; 9 moderate advisories in the lint tooling
  (`minimatch` via ESLint) were fixed by pinning `minimatch` 11.0.4.

## Limits and deployment notes

- The failed-login counters are kept in memory. That is right for the intended
  deployment (one process with SQLite); several workers or servers would share them
  through a store such as Redis.
- The web app's own Content-Security-Policy belongs on the web server that serves the
  built frontend (for example `default-src 'self'; connect-src 'self' <API origin>`);
  the development server needs inline scripts and cannot use a strict policy.
- The ML code runs offline on generated data and never receives user input; its SQL is
  built from fixed table names and dates. It is linted, but not with the security
  rules (which would only flag those fixed queries and the asserts in its tests).
