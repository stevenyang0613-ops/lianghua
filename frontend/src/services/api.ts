import type { ConvertibleQuote } from '../types'

const BASE = '/api/v1'

async function fetchJSON<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

export async function fetchAllQuotes(): Promise<{ total: number; bonds: ConvertibleQuote[]; updated_at: string }> {
  return fetchJSON(`${BASE}/market/quotes`)
}

export async function fetchQuote(code: string): Promise<ConvertibleQuote> {
  return fetchJSON(`${BASE}/market/quotes/${code}`)
}

export async function healthCheck(): Promise<{ status: string; app: string }> {
  return fetchJSON('/health')
}
