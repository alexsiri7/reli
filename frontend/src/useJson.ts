import { useEffect, useState } from "react";

import { getJson } from "./api";

/**
 * Load one JSON document, reloading when *url* changes.
 *
 * `setData` is for the one case that changes server state: the user-model view swaps in the
 * preference the reject endpoint returned rather than refetching the whole model.
 */
export function useJson<T>(url: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);
    getJson<T>(url)
      .then((value) => {
        if (current) setData(value);
      })
      .catch((reason: unknown) => {
        if (current) setError(String(reason));
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [url]);

  return { data, error, loading, setData };
}
