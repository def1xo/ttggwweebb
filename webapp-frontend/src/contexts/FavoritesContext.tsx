import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import api, { getFavoriteIds, addFavorite, removeFavorite } from "../services/api";

type FavoritesCtx = {
  loaded: boolean;
  ids: Set<number>;
  isFavorite: (id: number) => boolean;
  toggle: (id: number) => Promise<void>;
  refresh: () => Promise<void>;
};

const FavoritesContext = createContext<FavoritesCtx>({
  loaded: false,
  ids: new Set<number>(),
  isFavorite: () => false,
  toggle: async () => {},
  refresh: async () => {},
});

export function FavoritesProvider({ children }: { children: React.ReactNode }) {
  const [loaded, setLoaded] = useState(false);
  const [ids, setIds] = useState<Set<number>>(new Set());

  async function refresh() {
    try {
      const res: any = await getFavoriteIds();
      const items = Array.isArray(res?.items) ? res.items : Array.isArray(res) ? res : [];
      const next = new Set<number>();
      for (const x of items) {
        const n = Number(x);
        if (!Number.isNaN(n)) next.add(n);
      }
      setIds(next);
      setLoaded(true);
    } catch {
      setLoaded(true);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  function isFavorite(id: number) {
    return ids.has(Number(id));
  }

  async function toggle(id: number) {
    const pid = Number(id);
    if (Number.isNaN(pid)) return;

    // optimistic UI
    const was = ids.has(pid);
    setIds((prev) => {
      const next = new Set(prev);
      if (was) next.delete(pid);
      else next.add(pid);
      return next;
    });

    try {
      if (was) await removeFavorite(pid);
      else await addFavorite(pid);
    } catch {
      // rollback if failed
      setIds((prev) => {
        const next = new Set(prev);
        if (was) next.add(pid);
        else next.delete(pid);
        return next;
      });
    }
  }

  const value = useMemo(
    () => ({ loaded, ids, isFavorite, toggle, refresh }),
    [loaded, ids]
  );

  return <FavoritesContext.Provider value={value}>{children}</FavoritesContext.Provider>;
}

export function useFavorites() {
  return useContext(FavoritesContext);
}
