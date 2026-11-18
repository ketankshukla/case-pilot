import Link from "next/link";

import type { CaseState, DemoCase, WorkspaceSnapshot } from "./workspace";

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
          <span className="mode">Demo · Fixtures</span>
        </div>
      </div>
    </header>
  );
}

function Inbox({ cases, selectedId }: { cases: DemoCase[]; selectedId: string }) {
  return (
    <nav className="panel inbox" aria-labelledby="inbox-heading">
      <h2 id="inbox-heading">Case inbox</h2>
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
              <CaseStatus state={item.state} />
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
      ) : <p className="muted">Order details are pending an order ID.</p>}

      {item.missing_information.length ? (
        <div className="missing-info">
          <h3>Missing information</h3>
          <ul>{item.missing_information.map((detail) => <li key={detail}>{detail}</li>)}</ul>
        </div>
      ) : null}
    </section>
  );
}

function Evidence({ passages }: { passages: DemoCase["evidence"] }) {
  return (
    <section className="panel" aria-labelledby="evidence-heading">
      <h2 id="evidence-heading">Policy evidence</h2>
      {passages.length ? (
        <ul className="evidence-list">
          {passages.map((passage) => (
            <li className="evidence-item" id={`evidence-${passage.source_id}`} key={passage.source_id} tabIndex={-1}>
              <h3>{passage.title}</h3>
              <p className="evidence-meta">{passage.source_id} · v{passage.version} · Effective <time dateTime={passage.effective_date}>{passage.effective_date}</time></p>
              <blockquote>{passage.excerpt}</blockquote>
            </li>
          ))}
        </ul>
      ) : <p className="muted">No policy excerpts are shown for this case.</p>}
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
            <p>Full refund</p>
            <div className="action-value">{currency.format(proposal.amount_cents / 100)} <span>{proposal.currency}</span></div>
          </div>
          <dl className="action-facts">
            <div><dt>Order</dt><dd>{item.order?.order_id} · v{proposal.order_version}</dd></div>
            <div><dt>Proposal</dt><dd>Revision {proposal.revision}</dd></div>
            <div><dt>Evidence</dt><dd className="citations">{proposal.policy_ids.map((source) => (
              <a key={source} href={`#evidence-${source}`}>{source}</a>
            ))}</dd></div>
          </dl>
          <p className="action-explanation">{proposal.validation_summary}</p>
          <p className="preview-note">Fixture proposal. No action was taken.</p>
        </>
      ) : <p className="muted">No action is proposed.</p>}
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
            <li key={`${event.at_utc}-${event.title}`}>
              <h3>{event.title}</h3>
              <UtcTime value={event.at_utc} />
              <p>{event.detail}</p>
            </li>
          ))}
        </ol>
      ) : <p className="muted">No fixture events to display.</p>}
    </section>
  );
}

export function CaseDesk({ workspace, currentCase }: {
  workspace: WorkspaceSnapshot;
  currentCase: DemoCase | undefined;
}) {
  return (
    <>
      <DeskHeader persona={workspace.persona} />
      <main className="page-shell" id="main-content" tabIndex={-1}>
        <div className="desk-heading">
          <h1>Support desk</h1>
          <p>Fixture clock <UtcTime value={workspace.clock_utc} /></p>
        </div>
        {currentCase ? (
          <div className="desk-grid">
            <Inbox cases={workspace.cases} selectedId={currentCase.case_id} />
            <div className="case-column">
              <CaseWorkspace item={currentCase} />
              <Evidence passages={currentCase.evidence} />
            </div>
            <div className="case-column action-column">
              <ActionPreview item={currentCase} />
              <History events={currentCase.history} />
            </div>
          </div>
        ) : <p className="panel">No cases are available in this demo workspace.</p>}
      </main>
    </>
  );
}
