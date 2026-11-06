"""Which status a ticket should have for an MR's state, and when to leave it alone. No I/O."""

MANAGED = ("to-do", "in-progress", "in-review")


def target_for(state: str, draft: bool, valid_issues: bool, merged_into: str | None,
               default_branch: str, relation: str) -> str | None:
    """The status the MR's state implies: in-progress, in-review, done, or None (no move)."""
    if state == "open":
        return "in-progress" if draft or valid_issues else "in-review"
    if state == "merged":
        return "done" if merged_into == default_branch and relation == "fixes" else None
    if state == "closed":
        return None
    raise ValueError(f"unknown MR state {state!r}")


def plan_move(current: str, columns: list[dict], target: str | None) -> tuple[str | None, str]:
    """(column slug to move to, or None) and why, with the guards that protect people's choices."""
    slugs = [c["slug"] for c in columns]
    final = next((c["slug"] for c in columns if c.get("is_final")), None)
    if final is not None and current == final:
        return None, "already done; never moved out of done"
    if current not in MANAGED:
        return None, f"left in {current} (set by a person)"
    if target is None:
        return None, "no status change for this MR state"
    want = final if target == "done" else target
    if want is None or want not in slugs:
        return None, f"project has no {target} column"
    if want == current:
        return None, f"already {current}"
    return want, f"{current} → {want}"


def mr_state_key(state: str, draft: bool, merged_into: str | None) -> str:
    """A stable label for the MR's state, so one state is commented on once."""
    if state == "open":
        return "open-draft" if draft else "open-ready"
    if state == "merged":
        return f"merged:{merged_into}"
    return state


def comment_for(state: str, draft: bool, merged_into: str | None, default_branch: str,
                mr_ref: str, mr_url: str, sha: str | None, reasons: list[str]) -> str:
    """The ticket comment for this MR state."""
    if state == "open" and draft:
        text = f"{mr_ref} open (Draft): {mr_url}"
        return text + "".join(f"\n- {r}" for r in reasons)
    if state == "open":
        return f"{mr_ref} ready for review: {mr_url}"
    if state == "merged" and merged_into == default_branch:
        short = f" ({sha[:9]})" if sha else ""
        return f"Merged to {default_branch} in {mr_ref}{short}: {mr_url}"
    if state == "merged":
        return f"Merged into {merged_into} in {mr_ref}"
    return f"{mr_ref} closed without merging: {mr_url}"
