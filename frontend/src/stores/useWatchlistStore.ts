import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface WatchItem {
  code: string
  name: string
  addedAt: number
}

interface WatchlistState {
  watchlist: WatchItem[]
  addWatch: (item: WatchItem) => void
  removeWatch: (code: string) => void
  isInWatchlist: (code: string) => boolean
  clearWatchlist: () => void
}

export const useWatchlistStore = create<WatchlistState>()(
  persist(
    (set, get) => ({
      watchlist: [],

      addWatch: (item) => set((state) => {
        if (state.watchlist.some((w) => w.code === item.code)) return state
        return { watchlist: [...state.watchlist, item] }
      }),

      removeWatch: (code) => set((state) => ({
        watchlist: state.watchlist.filter((w) => w.code !== code),
      })),

      isInWatchlist: (code) => get().watchlist.some((w) => w.code === code),

      clearWatchlist: () => set({ watchlist: [] }),
    }),
    {
      name: 'lianghua-watchlist',
    }
  )
)
