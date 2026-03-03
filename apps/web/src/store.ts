import { create } from "zustand";
import type { Job, SessionDetail } from "./lib/types";

type AppState = {
  session: SessionDetail | null;
  busy: boolean;
  lastJob: Job | null;
  error: string | null;
  setSession: (session: SessionDetail | null) => void;
  setBusy: (busy: boolean) => void;
  setLastJob: (job: Job | null) => void;
  setError: (error: string | null) => void;
};

export const useAppStore = create<AppState>((set) => ({
  session: null,
  busy: false,
  lastJob: null,
  error: null,
  setSession: (session) => set({ session }),
  setBusy: (busy) => set({ busy }),
  setLastJob: (lastJob) => set({ lastJob }),
  setError: (error) => set({ error })
}));
