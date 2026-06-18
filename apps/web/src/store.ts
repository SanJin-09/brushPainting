import { create } from "zustand";
import type { BatchRead, ImageRead, JobRead } from "./lib/types";

type AppState = {
  batch: BatchRead | null;
  selectedImage: ImageRead | null;
  busy: boolean;
  lastJob: JobRead | null;
  error: string | null;
  setBatch: (batch: BatchRead | null) => void;
  setSelectedImage: (image: ImageRead | null) => void;
  setBusy: (busy: boolean) => void;
  setLastJob: (job: JobRead | null) => void;
  setError: (error: string | null) => void;
};

export const useAppStore = create<AppState>()((set) => ({
  batch: null,
  selectedImage: null,
  busy: false,
  lastJob: null,
  error: null,
  setBatch: (batch) => set({ batch }),
  setSelectedImage: (image) => set({ selectedImage: image }),
  setBusy: (busy) => set({ busy }),
  setLastJob: (lastJob) => set({ lastJob }),
  setError: (error) => set({ error })
}));
