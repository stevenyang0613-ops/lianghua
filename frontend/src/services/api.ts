import type { ConvertibleQuote } from '../types'

const BASE = '/api/v1'

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function fetchJSON<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) {
    const text = await resp.text()
    try {
      const json = JSON.parse(text)
      throw new ApiError(resp.status, json.detail || `HTTP ${resp.status}`)
    } catch {
      throw new ApiError(resp.status, text || `HTTP ${resp.status}`)
    }
  }
  return resp.json()
}

export async function fetchAllQuotes(): Promise<{ total: number; bonds: ConvertibleQuote[]; updated_at: string }> {
  return fetchJSON(`${BASE}/market/quotes`)
}

export async function fetchQuote(code: string): Promise<ConvertibleQuote> {
  return fetchJSON(`${BASE}/market/quotes/${code}`)
}

export async function healthCheck(): Promise<{ status: string; app: string; market_running: boolean }> {
  return fetchJSON('/health')
}
