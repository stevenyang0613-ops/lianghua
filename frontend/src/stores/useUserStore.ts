import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface User {
  id: string
  name: string
  avatar?: string
  createdAt: number
  lastActiveAt: number
}

interface UserState {
  users: User[]
  currentUserId: string | null
  currentUser: User | null
  settings: Record<string, unknown>

  createUser: (name: string, avatar?: string) => User
  deleteUser: (id: string) => void
  switchUser: (id: string) => void
  updateSettings: (key: string, value: unknown) => void
  getSettings: <T>(key: string, defaultValue: T) => T
}

function generateId(): string {
  return `user_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`
}

export const useUserStore = create<UserState>()(
  persist(
    (set, get) => ({
      users: [],
      currentUserId: null,
      currentUser: null,
      settings: {},

      createUser: (name, avatar) => {
        const user: User = {
          id: generateId(),
          name,
          avatar,
          createdAt: Date.now(),
          lastActiveAt: Date.now(),
        }
        set((state) => ({
          users: [...state.users, user],
          currentUserId: user.id,
          currentUser: user,
        }))
        return user
      },

      deleteUser: (id) => set((state) => {
        const users = state.users.filter((u) => u.id !== id)
        const currentUserId = state.currentUserId === id ? (users[0]?.id || null) : state.currentUserId
        const currentUser = currentUserId ? users.find((u) => u.id === currentUserId) || null : null
        return { users, currentUserId, currentUser }
      }),

      switchUser: (id) => set((state) => {
        const user = state.users.find((u) => u.id === id)
        if (user) {
          const updated = { ...user, lastActiveAt: Date.now() }
          return {
            currentUserId: id,
            currentUser: updated,
            users: state.users.map((u) => u.id === id ? updated : u),
          }
        }
        return state
      }),

      updateSettings: (key, value) => set((state) => ({
        settings: { ...state.settings, [key]: value },
      })),

      getSettings: <T,>(key: string, defaultValue: T): T => {
        const state = get()
        return (state.settings[key] as T) ?? defaultValue
      },
    }),
    {
      name: 'lianghua-users',
    }
  )
)

export function initDefaultUser(): void {
  const state = useUserStore.getState()
  if (state.users.length === 0) {
    state.createUser('默认用户')
  } else if (!state.currentUserId) {
    state.switchUser(state.users[0].id)
  }
}
