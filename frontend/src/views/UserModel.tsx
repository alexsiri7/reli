import { useState } from "react";
import { Link } from "react-router-dom";

import { paths, rejectPreference, type Preference, type UserModel } from "../api";
import { useJson } from "../useJson";
import { Status, Tags } from "./Status";

/**
 * One preference, its scope, and the evidence behind it — inline, so following a preference back to
 * the Thing that produced it is one click.
 *
 * The reject button is the only thing in this app that writes. A rejected preference keeps rendering,
 * visually distinct and with no button: the point of the view is that a wrong preference is
 * spottable, which a hidden one is not.
 */
function PreferenceCard({ preference, onRejected }: { preference: Preference; onRejected: (p: Preference) => void }) {
  const [rejecting, setRejecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reject() {
    setRejecting(true);
    setError(null);
    rejectPreference(preference.thing.id)
      .then(onRejected)
      .catch((reason: unknown) => setError(String(reason)))
      .finally(() => setRejecting(false));
  }

  return (
    <li className={preference.rejected ? "preference rejected" : "preference"}>
      <div className="preference-head">
        <h2>
          <Link to={`/things/${preference.thing.id}`}>{preference.thing.title}</Link>
        </h2>
        {preference.rejected && <span className="badge">Rejected</span>}
      </div>
      <p className="scope">
        <span className="label">Scope</span> {preference.scope ?? "—"}
      </p>
      <p className="strength">
        {preference.evidence_count} {preference.evidence_count === 1 ? "piece" : "pieces"} of evidence
      </p>
      <ul className="evidence">
        {preference.evidence.map((evidence) => (
          <li key={evidence.id}>
            <Link to={`/things/${evidence.id}`}>{evidence.title}</Link>
            <Tags tags={evidence.tags} />
          </li>
        ))}
      </ul>
      {!preference.rejected && (
        <button className="reject" onClick={reject} disabled={rejecting}>
          {rejecting ? "Rejecting…" : "Reject this preference"}
        </button>
      )}
      {error !== null && <p className="status error">Could not reject: {error}</p>}
    </li>
  );
}

export function UserModelView() {
  const { data, error, loading, setData } = useJson<UserModel>(paths.userModel);

  function replace(updated: Preference) {
    if (data === null) return;
    setData({
      ...data,
      preferences: data.preferences.map((p) => (p.thing.id === updated.thing.id ? updated : p)),
    });
  }

  return (
    <section>
      <h1>User model</h1>
      <p className="lede">
        What Reli has inferred about you, and the evidence behind each one. Strength is the number of
        pieces of evidence — there is no confidence score.
      </p>
      <Status loading={loading} error={error} />
      {data !== null &&
        (data.preferences.length === 0 ? (
          <p className="status">No preferences recorded yet.</p>
        ) : (
          <ul className="preferences">
            {data.preferences.map((preference) => (
              <PreferenceCard key={preference.thing.id} preference={preference} onRejected={replace} />
            ))}
          </ul>
        ))}
    </section>
  );
}
