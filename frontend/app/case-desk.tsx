import Link from "next/link";

import type { CaseState, CaseSummary, DemoCase, WorkspaceSnapshot } from "./workspace";

const currency = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const utcDateTime = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});
const statusLabels: Record<CaseState, string> = {
  investigating: "Investigating",
  awaiting_information: "Awaiting information",
  awaiting_review: "Awaiting review",
  escalated: "Escalated for review",
};
const runStatusLabels: Record<DemoCase["history"][number]["status"], string> = {
  ok: "Succeeded",
  paused: "Paused",
  error: "Error",
};

function UtcTime({ value }: { value: string }) {
  return <time dateTime={value}>{utcDateTime.format(new Date(value))} UTC</time>;
}

function CaseStatus({ state }: { state: CaseState }) {
  return <span className={`status ${state}`}>{statusLabels[state]}</span>;
}

export function DeskHeader({ persona }: { persona?: WorkspaceSnapshot["persona"] }) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand"><span className="brand-icon" aria-hidden="true" />CasePilot</div>
        <div className="topbar-meta">
          {persona ? <span className="persona">{persona.display_name} <span>· {persona.customer_id}</span></span> : null}
          <span className="mode">Demo · Replay</span>
        </div>
      </div>
    </header>
  );
}

function Inbox({ cases, selectedId }: { cases: CaseSummary[]; selectedId: string }) {
  return (
    <nav className="panel inbox" aria-labelledby="inbox-heading">
      <h2 id="inbox-heading">Case inbox</h2>
      <p className="inbox-hint">Select a case to replay its investigation.</p>
      <ul className="case-list">
        {cases.map((item) => (
          <li key={item.case_id}>
            <Link
              className="case-link"
              href={`/?case=${encodeURIComponent(item.case_id)}#case-workspace`}
              aria-current={item.case_id === selectedId ? "page" : undefined}
              prefetch={false}
            >
              <span className="case-reference">{item.scenario_id} · {item.case_id}</span>
              <span className="case-title">{item.title}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function CaseWorkspace({ item }: { item: DemoCase }) {
  const { order } = item;
  return (
    <section className="panel case-workspace" id="case-workspace" aria-labelledby="case-title" tabIndex={-1}>
      <div className="case-header">
        <div>
          <p className="case-reference">{item.scenario_id} · {item.case_id}</p>
          <h2 id="case-title">{item.title}</h2>
        </div>
        <CaseStatus state={item.state} />
      </div>

      <div className="request">
        <h3>Customer request</h3>
        <blockquote>{item.request}</blockquote>
      </div>

      <h3>Order facts</h3>
      {order ? (
        <dl className="facts">
          <div><dt>Order</dt><dd>{order.order_id}</dd></div>
          <div><dt>Order version</dt><dd>{order.version}</dd></div>
          <div><dt>Paid total</dt><dd>{currency.format(order.paid_cents / 100)} {order.currency}</dd></div>
          {order.facts.map(({ label, value }) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
      ) : <p className="muted">Order facts are unavailable for this run.</p>}

      {item.missing_information.length ? (
        <div className="missing-info">
          <h3>Missing information</h3>
          <ul>{item.missing_information.map((detail) => <li key={detail}>{detail}</li>)}</ul>
        </div>
      ) : null}
    </section>
  );
}

function evidenceAnchor(sourceId: string, version: number) {
  return `evidence-${sourceId}-v${version}`;
}

function Evidence({ passages, status }: { passages: DemoCase["evidence"]; status: DemoCase["evidence_status"] }) {
  const statusMessage = {
    available: null,
    missing: "This case is missing current approved policy evidence.",
    conflicting: "Current approved passages disagree. The relevant excerpts are shown for human review.",
    not_checked: "Policy retrieval is pending.",
  }[status];

  return (
    <section className="panel" aria-labelledby="evidence-heading">
      <h2 id="evidence-heading">Policy evidence</h2>
      {statusMessage ? <p className="muted">{statusMessage}</p> : null}
      {passages.length ? (
        <ul className="evidence-list">
          {passages.map((passage) => {
            const anchor = evidenceAnchor(passage.source_id, passage.version);
            return (
              <li className="evidence-item" id={anchor} key={anchor} tabIndex={-1}>
                <h3>{passage.title}</h3>
                <p className="evidence-meta">{passage.source_id} · v{passage.version} · Effective <time dateTime={passage.effective_date}>{passage.effective_date}</time> · {passage.approval_status}</p>
                <blockquote>{passage.excerpt}</blockquote>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

function ActionPreview({ item }: { item: DemoCase }) {
  const { proposal } = item;
  return (
    <section className="panel action-panel" aria-labelledby="action-heading">
      <h2 id="action-heading">Exact action preview</h2>
      {proposal ? (
        <>
          <div className="action-summary">
            <p>{proposal.remedy === "full_refund" ? "Full refund" : "Partial refund"}</p>
            <div className="action-value">{currency.format(proposal.amount_cents / 100)} <span>{proposal.currency}</span></div>
          </div>
          <dl className="action-facts">
            <div><dt>Customer</dt><dd>{proposal.customer_id}</dd></div>
            <div><dt>Order</dt><dd>{proposal.order_id} · v{proposal.order_version}</dd></div>
            {proposal.line_id ? <div><dt>Line item</dt><dd>{proposal.line_id}</dd></div> : null}
            <div><dt>Proposal</dt><dd>Revision {proposal.revision}</dd></div>
            <div><dt>Evidence</dt><dd className="citations">{proposal.policy_versions.map((policy) => {
              const anchor = evidenceAnchor(policy.source_id, policy.version);
              return <a key={anchor} href={`#${anchor}`}>{policy.source_id} v{policy.version}</a>;
            })}</dd></div>
          </dl>
          <p className="action-explanation">{proposal.validation_summary}</p>
          <p className="preview-note">Replay proposal. Reviewer approval is required for a sandbox write.</p>
        </>
      ) : (
        <>
          <p className="muted">{item.decision_summary}</p>
          {item.draft ? (
            <div className="response-draft">
              <h3>Customer update draft</h3>
              <blockquote>{item.draft}</blockquote>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function History({ events }: { events: DemoCase["history"] }) {
  return (
    <section className="panel" aria-labelledby="history-heading">
      <h2 id="history-heading">Run history</h2>
      {events.length ? (
        <ol className="timeline">
          {events.map((event) => (
            <li key={`${event.at_utc}-${event.operation}-${event.attempt}-${event.title}`} data-status={event.status}>
              <h3>{event.title}</h3>
              <div className="timeline-meta">
                <span>{runStatusLabels[event.status]}</span>
                {event.attempt > 1 ? <span>Attempt {event.attempt}</span> : null}
                {event.latency_ms !== null ? <span>{event.latency_ms} ms</span> : null}
                <UtcTime value={event.at_utc} />
              </div>
              <p>{event.detail}</p>
            </li>
          ))}
        </ol>
      ) : <p className="muted">Run history is empty.</p>}
    </section>
  );
}

export function CaseDesk({ workspace, selectedCase, investigation }: {
  workspace: WorkspaceSnapshot;
  selectedCase: CaseSummary | undefined;
  investigation: DemoCase | null;
}) {
  return (
    <>
      <DeskHeader persona={workspace.persona} />
      <main className="page-shell" id="main-content" tabIndex={-1}>
        <div className="desk-heading">
          <h1>Support desk</h1>
          <p>Fixture clock <UtcTime value={workspace.clock_utc} /></p>
        </div>
        {selectedCase ? (
          <div className="desk-grid">
            <Inbox cases={workspace.cases} selectedId={selectedCase.case_id} />
            {investigation ? (
              <>
                <div className="case-column">
                  <CaseWorkspace item={investigation} />
                  <Evidence passages={investigation.evidence} status={investigation.evidence_status} />
                </div>
                <div className="case-column action-column">
                  <ActionPreview item={investigation} />
                  <History events={investigation.history} />
                </div>
              </>
            ) : (
              <section className="panel case-workspace" id="case-workspace" tabIndex={-1}>
                <h2>Investigation unavailable</h2>
                <p className="muted">Reload the page to retry this case or select another case from the inbox.</p>
              </section>
            )}
          </div>
        ) : <p className="panel">No cases are available in this demo workspace.</p>}
      </main>
    </>
  );
}
