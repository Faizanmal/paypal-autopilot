"""Start with python -m app.workers.render_reports (or Render's local CLI)."""

from render import Retry, TaskContext, Workflows

from app.modules.finance.reports import build_cash_report

app = Workflows(default_retry=Retry(max_retries=2, wait_duration_ms=1000), default_timeout=120)


@app.task(name="cash-risk-report")
def cash_risk_report(ctx: TaskContext, snapshot: dict) -> dict:
    # Input contains a server-built snapshot, never credentials or payment commands.
    return build_cash_report(snapshot)


if __name__ == "__main__":
    app.start()
