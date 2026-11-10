"""Identity & tenancy module.

Owns: users, workspaces, workspace memberships, authentication/session
issuance, and the `require_workspace_member` / `require_workspace_owner`
FastAPI dependencies that every other module's router relies on for
server-side workspace isolation (docs/SECURITY.md §3).

Status: NOT STARTED.
"""
