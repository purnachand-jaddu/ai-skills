# General Rules

- Layers and providers talk through narrow interfaces declared by the code that calls them; an interface exists only where something holds it
  - This includes the DB layer; keep an interface generic enough to swap a provider without breaking its callers
- Reuse before creating: check utils or existing functions first
  - Prefer slight modification with different params over writing a new function
- Preferred stack: Go (backend), Next.js (frontend), Postgres (primary DB), SQLite (secondary)
- Complex features need a flow diagram artifact
  - Should cover all states and data flow sequences
- Multi-module deployments need a deployment plan
  - Define service order, risk of mid-deployment failure
- If a feature touches existing flows, require a feature flag for gradual rollout
- Never commit `.env` files, and never echo a token into logs, chat or files

# API Server Rules

- Strict layer separation: handler, service, and database layers
- ORM or schema manager (e.g., Goose) must live inside the codebase
- Always add observability checks so metrics stream to the observability platform
- Paginate all APIs that could return large record sets; avoid single unbounded GET
- Enforce RBAC: define who gets access to each API
  - A route registry names the roles for each route, and a test sweeps every route for every role
- Row-level authorization lives in the service; the handler passes the caller and makes one call
- Every query filters by tenant in SQL, even after the service has checked access
- A write that spans tables is one repository method that owns the transaction
- Migrations run on boot under a lock; renaming or dropping a column others read is expand, then contract
- A new filter or sort path ships its index in the same MR, built concurrently
- Validate input at the boundary: a malformed id is a 400, and a client fault never surfaces as a database 500
- One error envelope; a credential failure is a uniform 401/403, but an outage behind it stays a 5xx
- Every request runs under a deadline
- Background jobs are safe with several replicas (`SKIP LOCKED`, an advisory lock)
- Store only hashes of tokens, consume single-use codes atomically, and seal secrets at rest
- The API contract (OpenAPI) changes in the same MR as the code
- No experimental package features for security
- Tests required for every handler and service
  - Tests must fail if the feature is reverted

# Endpoint-Specific Rules

- Minimize memory and CPU usage at the endpoint level
- Third-party packages must be widely adopted in the community; avoid low-traction libraries
- Prefer non-CGO packages over CGO packages
- Security: restrict file/folder permissions to the minimum required (package-readable only, no root needed by others)
  - Credentials are 0600; read a file a less-privileged user can write only after checking its owner, that it is not a symlink, and its size
  - Size-cap and chunk every read of an untrusted local file
- Local IPC binds to loopback, checks the Host header and allowlists clients; sensitive routes only on the permissioned socket
- Auto-update verifies a signature against a key built into the binary; macOS binaries are signed and notarized
- Vendor credentials never reach the endpoint; call vendors through a backend proxy
- Per-user actions run as the logged-in user through the platform's session mechanism, never from root's environment
- Save local sync state only after the server acknowledges it; on any doubt, resync in full
- Third-party calls: bounded retries with backoff, honour `Retry-After`, keep the last-known values on a soft failure
- An unattended install never blocks on a prompt or a browser
- Each feature must have tests that fail if the feature breaks
- Produce logs using the existing log framework to aid debugging
  - Log files are bounded by size and age, with one writer each
- Prefer CLI-first approach for endpoint-level features
- Cross-platform compatibility required: macOS (Darwin), Linux, Windows
  - Any new package introduced must support all three platforms

# Go Rules (API Server and Endpoint)

- Structured logs: a constant message, snake_case fields, and request, tenant and trace ids from the context
- Metric labels stay low-cardinality (a tenant id goes on spans); telemetry is a no-op when no exporter is set
- Every background loop recovers a panic on each iteration
- Platform code uses build constraints, not `runtime.GOOS`
- Generated code is committed, and CI fails when it is stale
- Integration tests run on a real database, one tenant per test, with `-race` and a virtual clock instead of sleeps

# Frontend Rules

- Stack: Next.js (App Router), TypeScript in strict mode, shadcn/ui + Radix + Tailwind, TanStack Query, pnpm
- Data fetching only through hooks, and API calls only through one shared HTTP client (auth headers, 401 handling)
  - Query keys carry every input; rolling windows ("last 7d") compute their dates inside the query function
- Reuse before creating: search shared components, hooks and helpers by behaviour
  - Extend a shared component rather than forking it; promote a private helper instead of copying it
- No magic strings or numbers: routes, identifiers, page sizes, limits and timeouts are named constants
  - One source of truth per domain type: a const map plus a descriptor map
  - Feature constants live in the feature folder; shared by two or more features, in the shared lib
- Thin pages: query-param mapping and filter-to-request translation live in feature modules, not in the page
- RBAC through shared helpers and a route guard, never ad-hoc role checks in components
- Design tokens only: no raw hex or arbitrary values when a token or scale step exists; ask before adding one
- State the user would share or come back to (selection, active tab, open panel) lives in the URL
- Lists: stable keys from domain ids, never the index; reset dependent state (selection, panel) when the list refetches
- Counts come from the API's total, never from the length of the current page
- Component APIs: composition and explicit variants over boolean props; never define a component inside another
  - Derive values during render, not with an effect plus setState; interaction logic goes in the event handler
- Accessibility (WCAG 2.2 AA): semantic elements before ARIA, labels on every control and icon-only button, full keyboard access, meaning never by colour alone
- Every interaction works at narrow (mobile) widths
- Guard all parsing with a defined fallback in one shared formatter
- Unit tests for pure functions (edge cases included) and component tests for behaviour, on Vitest + Testing Library
- Before calling a change done: typecheck, lint, format, tests, then exercise it in a real browser and read the console
