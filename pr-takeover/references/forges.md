# Forge command reference

These are starting points, not a contract. CLIs and APIs drift, so check `--help` or the forge's API docs when a command fails or a flag looks unfamiliar. Paginate every list call; PRs with long review histories span several pages.

Contents:
- GitHub (`gh`)
- GitLab (`glab`)
- Bitbucket Cloud (REST)
- Gitea / Forgejo (`tea` or REST)
- Azure DevOps (`az`)
- No forge access

---

## GitHub (`gh`)

Auth: `gh auth status`. If not logged in: `! gh auth login`.

**PR metadata**
```sh
gh pr view <N> --json number,title,body,state,isDraft,author,url,baseRefName,headRefName,headRefOid,isCrossRepository,headRepositoryOwner,headRepository,maintainerCanModify,mergeable,reviewDecision,statusCheckRollup
```

**General comments and review summaries**
```sh
gh pr view <N> --json comments,reviews
```

**Inline review threads, with resolved/outdated state.** REST `pulls/<N>/comments` lacks resolution state, so use GraphQL:
```sh
gh api graphql --paginate -F owner=<owner> -F repo=<repo> -F n=<N> -f query='
query($owner:String!,$repo:String!,$n:Int!,$endCursor:String){
  repository(owner:$owner,name:$repo){ pullRequest(number:$n){
    reviewThreads(first:50, after:$endCursor){
      pageInfo{ hasNextPage endCursor }
      nodes{ id isResolved isOutdated path line originalLine
        comments(first:100){ nodes{ databaseId author{login} body url createdAt } } } } } } }'
```

**Check out into a worktree**
```sh
git worktree add --detach ../<repo>-pr<N> && cd ../<repo>-pr<N> && gh pr checkout <N>
```
`gh pr checkout` sets up the fork remote and upstream, so a plain `git push` goes to the right place.

**CI**
```sh
gh pr checks <N>                  # status; add --watch to wait
gh run view <run-id> --log-failed # failing job logs
gh run rerun <run-id> --failed    # rerun only to prove a flake
```

**Replies and resolution** (only after user approval)
```sh
gh api repos/<owner>/<repo>/pulls/<N>/comments/<comment-databaseId>/replies -f body=@reply.md
gh api graphql -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -F id=<thread-node-id>
gh pr comment <N> --body-file summary.md
gh pr edit <N> --body-file body.md
```

---

## GitLab (`glab`)

Auth: `glab auth status`. If not logged in: `! glab auth login`. For self-hosted GitLab, pass `--hostname`. `glab api` expands `:id` and `:fullpath` to the current project.

**MR metadata.** Fields to read: `source_branch`, `target_branch`, `sha`, `diff_refs.base_sha`, `source_project_id`, `target_project_id` (they differ for a fork), `allow_collaboration` (maintainers may push), `draft`, `detailed_merge_status`, `head_pipeline`.
```sh
glab api projects/:id/merge_requests/<N>
```

**All discussions: general notes and inline threads in one endpoint.** Each discussion has `notes[]`. Inline notes carry `position.new_path` / `position.new_line`, plus `resolvable` and `resolved`. Skip notes with `system: true`; they're events, not feedback. Approvals are separate:
```sh
glab api --paginate projects/:id/merge_requests/<N>/discussions
glab api projects/:id/merge_requests/<N>/approvals
```

**Check out into a worktree**
```sh
git worktree add --detach ../<repo>-mr<N> && cd ../<repo>-mr<N> && glab mr checkout <N>
```

**CI**
```sh
glab api projects/:id/merge_requests/<N>/pipelines   # latest first
glab api projects/:id/pipelines/<pipeline-id>/jobs   # find failed jobs
glab ci trace <job-id>                               # job log
```

**Replies and resolution** (only after user approval)
```sh
glab api -X POST projects/:id/merge_requests/<N>/discussions/<discussion-id>/notes -f body="$(cat reply.md)"
glab api -X PUT  projects/:id/merge_requests/<N>/discussions/<discussion-id> -f resolved=true
glab mr note <N> -m "$(cat summary.md)"
glab mr update <N> --description "$(cat body.md)"
```

---

## Bitbucket Cloud (REST)

There's no official CLI. Use `curl` with an API token or app password from the environment, and never echo it. Base URL: `https://api.bitbucket.org/2.0/repositories/<workspace>/<repo>`.

- **PR:** `GET /pullrequests/<N>`. Read `source.branch.name`, `source.commit.hash`, `source.repository.full_name` (a fork if it differs) and `destination.branch.name`.
- **Comments, general and inline:** `GET /pullrequests/<N>/comments`, following `next` links. An inline comment has `inline.path` and `inline.to`; replies have `parent.id`; check `deleted` and the resolution fields.
- **Tasks are separate:** `GET /pullrequests/<N>/tasks`.
- **CI:** `GET /commit/<sha>/statuses`.
- **Reply:** `POST /pullrequests/<N>/comments` with `{"content":{"raw":"…"},"parent":{"id":<id>}}`.
- **Check out:** `git fetch origin <source-branch>`, then a worktree on it. For forks, add the fork as a remote.

Verify field names against the current Bitbucket API docs before relying on resolution state.

---

## Gitea / Forgejo (`tea` or REST)

`tea` covers listing and checkout. For review threads, use the REST API: `https://<host>/api/v1/repos/<owner>/<repo>`, authenticated with a token header.

- **PR:** `GET /pulls/<N>` (fields `head.ref`, `head.sha`, `head.repo`, `base.ref`, `mergeable`).
- **General comments:** `GET /issues/<N>/comments`.
- **Reviews:** `GET /pulls/<N>/reviews`, then `GET /pulls/<N>/reviews/<review-id>/comments` for each review's inline comments (`path`, `position`, `resolver`).
- **Check out:** `tea pr checkout <N>` in a worktree, or `git fetch origin pull/<N>/head`.
- **CI:** commit statuses, `GET /repos/<owner>/<repo>/commits/<sha>/status` (Gitea Actions or an external CI).

---

## Azure DevOps (`az`)

Requires `az extension add --name azure-devops` and `az devops configure --defaults organization=<url> project=<name>`.

- **PR:** `az repos pr show --id <N>` (`sourceRefName`, `targetRefName`, `lastMergeSourceCommit`).
- **Threads, general and inline:** REST `GET {org}/{project}/_apis/git/repositories/{repo}/pullRequests/<N>/threads?api-version=7.1`, via `az devops invoke` or `curl` with a PAT. A thread has `status` (`active`, `fixed`, `closed`, …), `threadContext.filePath` / `rightFileStart.line`, and `comments[]`. Skip threads whose `properties` mark them as system events.
- **Reply:** `POST …/threads/<thread-id>/comments`. **Resolve:** `PATCH …/threads/<thread-id>` with `{"status":"fixed"}`.
- **CI:** `az pipelines runs list --branch <source-branch>`, then `az pipelines runs show --id <run>`.

---

## No forge access

When there's no CLI, no token, or an unknown host:

1. Ask the user to paste the review comments, or export them.
2. Work from the branch: `git fetch origin <branch>` plus a worktree.
3. Run CI-equivalent checks locally: the test suite, linters, and the build for each shipped target.
4. Hand back the reply drafts for the user to post.
