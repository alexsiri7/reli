import { paths, type TreeLevel } from "../api";
import { useJson } from "../useJson";
import { Status } from "./Status";
import { TreeNode } from "./TreeNode";

/** The `ChildOf` hierarchy, one level per request. The top level is what nothing claims as a child. */
export function Tree() {
  const { data, error, loading } = useJson<TreeLevel>(paths.treeLevel());

  return (
    <section>
      <h1>Tree</h1>
      <Status loading={loading} error={error} />
      {data !== null &&
        (data.things.length === 0 ? (
          <p className="status">Nothing here yet.</p>
        ) : (
          <ul className="tree">
            {data.things.map((thing) => (
              <TreeNode key={thing.id} thing={thing} />
            ))}
          </ul>
        ))}
    </section>
  );
}
