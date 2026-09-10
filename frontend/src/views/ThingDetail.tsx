import Markdown from "react-markdown";
import { Link, useParams } from "react-router-dom";

import {
  paths,
  type Direction,
  type History,
  type Relationship,
  type RelationshipType,
  type Thing,
  type ThingDetail,
} from "../api";
import { useJson } from "../useJson";
import { Status, Tags } from "./Status";

/**
 * What each relationship type means read from the requested Thing outwards.
 *
 * Direction carries a different reading per type — see `RelationshipType` in backend/db_models.py —
 * so the label is a lookup rather than a rule, and the raw enum is never shown.
 */
const EDGE_LABELS: Record<RelationshipType, Record<Direction, string>> = {
  ChildOf: { outgoing: "Children", incoming: "Parent" },
  Blocks: { outgoing: "Blocked by", incoming: "Blocks" },
  EvidenceFor: { outgoing: "Evidence for", incoming: "Evidence" },
  RelatedTo: { outgoing: "Related to", incoming: "Related from" },
  References: { outgoing: "References", incoming: "Referenced by" },
};

function groupByLabel(relationships: Relationship[]): [string, Relationship[]][] {
  const grouped = new Map<string, Relationship[]>();
  for (const edge of relationships) {
    const label = EDGE_LABELS[edge.relationship_type][edge.direction];
    grouped.set(label, [...(grouped.get(label) ?? []), edge]);
  }
  return [...grouped.entries()];
}

function Fields({ thing }: { thing: Thing }) {
  return (
    <dl className="fields">
      <dt>Priority</dt>
      <dd>{thing.priority}</dd>
      <dt>Check-in</dt>
      <dd>{thing.checkin_date ?? "—"}</dd>
      <dt>State</dt>
      <dd>{thing.active ? "Active" : "Archived"}</dd>
      {Object.entries(thing.urls).map(([name, url]) => (
        <div className="url" key={name}>
          <dt>{name}</dt>
          <dd>
            <a href={url}>{url}</a>
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Notes({ notes }: { notes: Record<string, string> }) {
  const entries = Object.entries(notes);
  if (entries.length === 0) return null;
  return (
    <section className="notes">
      <h2>Notes</h2>
      {entries.map(([slug, markdown]) => (
        <article key={slug}>
          <h3>{slug}</h3>
          {/* No rehype-raw: a note is markdown, and raw HTML in one stays inert. */}
          <Markdown>{markdown}</Markdown>
        </article>
      ))}
    </section>
  );
}

function Relationships({ relationships }: { relationships: Relationship[] }) {
  if (relationships.length === 0) return null;
  return (
    <section className="relationships">
      <h2>Relationships</h2>
      {groupByLabel(relationships).map(([label, edges]) => (
        <div className="edge-group" key={label}>
          <h3>{label}</h3>
          <ul>
            {edges.map((edge) => (
              <li key={edge.id}>
                <Link to={`/things/${edge.other.id}`}>{edge.other.title}</Link>
                <Tags tags={edge.other.tags} />
                {edge.context !== null && <span className="context">{edge.context}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

/** The journal, which is how "how did this get here" gets answered — including who did it. */
function HistoryTable({ history }: { history: History }) {
  return (
    <section className="history">
      <h2>History</h2>
      {history.truncated && (
        <p className="status">
          Showing the newest {history.entries.length} of {history.total} entries.
        </p>
      )}
      <table>
        <thead>
          <tr>
            <th>When</th>
            <th>Actor</th>
            <th>Operation</th>
            <th>Change</th>
          </tr>
        </thead>
        <tbody>
          {history.entries.map((entry) => (
            <tr key={entry.id}>
              <td>{entry.occurred_at}</td>
              <td>
                <span className={`actor actor-${entry.actor}`}>{entry.actor}</span>
              </td>
              <td>{entry.operation}</td>
              <td>
                <details>
                  <summary>before / after</summary>
                  <pre>{JSON.stringify({ before: entry.before, after: entry.after }, null, 2)}</pre>
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function ThingDetailView() {
  const { id = "" } = useParams();
  const detail = useJson<ThingDetail>(paths.thing(id));
  const history = useJson<History>(paths.history(id));

  return (
    <section className="detail">
      <Status loading={detail.loading} error={detail.error} />
      {detail.data !== null && (
        <>
          <h1>{detail.data.thing.title}</h1>
          <Tags tags={detail.data.thing.tags} />
          {detail.data.thing.description !== null && <p className="description">{detail.data.thing.description}</p>}
          <Fields thing={detail.data.thing} />
          <Notes notes={detail.data.thing.notes} />
          <Relationships relationships={detail.data.relationships} />
        </>
      )}
      <Status loading={history.loading} error={history.error} />
      {history.data !== null && <HistoryTable history={history.data} />}
    </section>
  );
}
