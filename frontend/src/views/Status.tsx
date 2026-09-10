export function Status({ loading, error }: { loading: boolean; error: string | null }) {
  if (error !== null) {
    return <p className="status error">Could not load: {error}</p>;
  }
  if (loading) {
    return <p className="status">Loading…</p>;
  }
  return null;
}

export function Tags({ tags }: { tags: string[] }) {
  return (
    <span className="tags">
      {tags.map((tag) => (
        <span className="tag" key={tag}>
          {tag}
        </span>
      ))}
    </span>
  );
}
