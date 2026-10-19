# ADR 0006: Start runs in the background and serialize them per project

- Status: accepted
- Date: 2026-10-19

## Context

The plan asks for an asynchronous start plus polling and for runs of one project to execute serially. A synchronous start holds the MCP call open for the whole suite, and two overlapping runs of one project would interleave their writes, their extracted `run.*` values and their cleanup, which is exactly how a test suite starts lying.

## Decision

1. **Preflight stays synchronous; execution moves to the background.** `execute_pinned_async` validates, authenticates, snapshots and creates the run row before returning, then submits the execution to `RunScheduler`. A caller that receives a run id can therefore trust that the configuration was accepted; a caller with a blocked case gets an error and no row.
2. **One lock per project.** The scheduler holds a per-project lock for the whole execution, so two runs of the same project queue instead of interleaving. Different projects run in parallel on a small pool (two workers by default).
3. **Polling is the contract; `wait` is a convenience.** `qa_api_run start` returns the `running` row by default, and `get` reads it back. `start` with `wait=true`, or `get` with `wait=true` and a timeout, blocks for callers that prefer one call.
4. **The scheduler is in-process.** A gateway restart abandons runs that were still `running`. The row keeps that status as evidence; nothing rewrites it to passed or failed, and the operator starts a new run.

## Consequences

- A long suite no longer holds the MCP call open, and a client can report progress from the run row.
- Two runs of one project are ordered, so extracted values and cleanup cannot collide; two projects still make progress together.
- A restart leaves `running` rows behind. That is visible and honest, but it means "running" is not proof that a process is alive; the operator decides whether to start again.
- Tests poll through `wait_for_run` with a timeout instead of sleeping, so a hang fails with a message rather than blocking the suite.

## Alternatives rejected

- **A durable queue with a separate worker.** Correct for a real deployment, but it needs a process, a lease and a recovery rule; the plan's first version does not ask for that, and an in-process scheduler is replaceable later behind `RunScheduler.submit`.
- **One thread per run.** Unbounded concurrency would let a burst of runs exhaust memory and the database write lock.
- **A single global lock.** Serializing every project would make one slow suite block unrelated work.
- **Returning a run id before preflight.** The caller would poll a run that can never pass, and the failure would arrive detached from the request that caused it.
