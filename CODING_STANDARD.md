# General Rules

- Always start new designs with an interface
  - Interfaces should be generic enough to swap providers without breaking changes
  - All inter-layer communication must happen via interfaces (including DB layer)
- Reuse before creating: check utils or existing functions first
  - Prefer slight modification with different params over writing a new function
- Preferred stack: Go (backend), Next.js (frontend), Postgres (primary DB), MySQL Lite (secondary)
- Complex features need a flow diagram artifact
  - Should cover all states and data flow sequences
- Multi-module deployments need a deployment plan
  - Define service order, risk of mid-deployment failure
- If a feature touches existing flows, require a feature flag for gradual rollout

# API Server Rules

- Strict layer separation: handler, service, and database layers
- ORM or schema manager (e.g., Goose) must live inside the codebase
- Always add observability checks so metrics stream to the observability platform
- Paginate all APIs that could return large record sets; avoid single unbounded GET
- Enforce RBAC: define who gets access to each API
- No experimental package features for security
- Tests required for every handler and service
  - Tests must fail if the feature is reverted

# Endpoint-Specific Rules

- Minimize memory and CPU usage at the endpoint level
- Third-party packages must be widely adopted in the community; avoid low-traction libraries
- Prefer non-CGO packages over CGO packages
- Security: restrict file/folder permissions to the minimum required (package-readable only, no root needed by others)
- Each feature must have tests that fail if the feature breaks
- Produce logs using the existing log framework to aid debugging
- Prefer CLI-first approach for endpoint-level features
- Cross-platform compatibility required: macOS (Darwin), Linux, Windows
  - Any new package introduced must support all three platforms

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
