import { useState } from "react";
import { Link } from "react-router-dom";

import { getJson, paths, type ThingSummary, type TreeLevel } from "../api";
import { Tags } from "./Status";

/**
 * One row of the tree, which fetches its children the first time it is expanded and keeps them.
 *
 * The chevron appears only when `has_children`, which the API answers per row, so expanding never
 * opens onto nothing and a leaf costs no request. Collapsing keeps what was fetched.
 */
export function TreeNode({ thing }: { thing: ThingSummary }) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<ThingSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function toggle() {
    setExpanded(!expanded);
    if (expanded || children !== null) return;
    getJson<TreeLevel>(paths.treeLevel(thing.id))
      .then((level) => setChildren(level.things))
      .catch((reason: unknown) => setError(String(reason)));
  }

  return (
    <li className="tree-node">
      <div className="tree-row">
        {thing.has_children ? (
          <button className="chevron" onClick={toggle} aria-expanded={expanded} aria-label="Expand">
            {expanded ? "▾" : "▸"}
          </button>
        ) : (
          <span className="chevron chevron-leaf" aria-hidden="true" />
        )}
        <Link className="tree-title" to={`/things/${thing.id}`}>
          {thing.title}
        </Link>
        <Tags tags={thing.tags} />
      </div>
      {expanded &&
        (error !== null ? (
          <p className="status error">Could not load children: {error}</p>
        ) : children === null ? (
          <p className="status">Loading…</p>
        ) : (
          <ul className="tree">
            {children.map((child) => (
              <TreeNode key={child.id} thing={child} />
            ))}
          </ul>
        ))}
    </li>
  );
}
