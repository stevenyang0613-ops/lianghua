/**
 * Service Worker for PWA
 * 提供离线缓存和后台同步功能
 */

const CACHE_NAME = 'lianghua-v2'
const STATIC_CACHE = 'lianghua-static-v2'
const DYNAMIC_CACHE = 'lianghua-dynamic-v2'
const API_CACHE = 'lianghua-api-v2'

// 需要缓存的静态资源
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
]

// API 缓存配置
const API_CACHE_CONFIG = {
  '/api/v1/quotes': { ttl: 5000, strategy: 'network-first' },      // 行情数据 5秒
  '/api/v1/bonds': { ttl: 60000, strategy: 'stale-while-revalidate' }, // 债券列表 1分钟
  '/api/v1/signals': { ttl: 30000, strategy: 'network-first' },    // 交易信号 30秒
  '/api/v1/strategies': { ttl: 300000, strategy: 'cache-first' },  // 策略列表 5分钟
}

// 安装事件
self.addEventListener('install', (event) => {
  console.log('[SW] Installing...')
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      console.log('[SW] Caching static assets')
      return cache.addAll(STATIC_ASSETS)
    })
  )
  self.skipWaiting()
})

// 激活事件
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating...')
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => !name.includes('v2'))
          .map((name) => caches.delete(name))
      )
    })
  )
  self.clients.claim()
})

// 请求拦截 - 智能缓存策略
self.addEventListener('fetch', (event) => {
  const { request } = event
  const url = new URL(request.url)

  // 只处理同源请求
  if (url.origin !== location.origin) return

  // API 请求 - 智能策略
  if (url.pathname.startsWith('/api/')) {
    const config = Object.entries(API_CACHE_CONFIG).find(([path]) => url.pathname.startsWith(path))

    if (config) {
      const [, { strategy }] = config
      event.respondWith(handleApiRequest(request, strategy))
    } else {
      event.respondWith(networkFirst(request, API_CACHE))
    }
    return
  }

  // WebSocket 请求不缓存
  if (url.protocol === 'ws:' || url.protocol === 'wss:') {
    return
  }

  // 静态资源使用缓存优先
  if (request.destination === 'style' || request.destination === 'script' || request.destination === 'image' || request.destination === 'font') {
    event.respondWith(staleWhileRevalidate(request, STATIC_CACHE))
    return
  }

  // 导航请求（HTML页面）
  if (request.mode === 'navigate') {
    event.respondWith(
      caches.match('/index.html').then(cached => {
        return cached || fetch(request).catch(() => caches.match('/index.html'))
      })
    )
    return
  }

  // 其他请求使用 Stale-While-Revalidate
  event.respondWith(staleWhileRevalidate(request, DYNAMIC_CACHE))
})

// 处理 API 请求
async function handleApiRequest(request, strategy) {
  switch (strategy) {
    case 'cache-first':
      return cacheFirst(request, API_CACHE)
    case 'network-first':
      return networkFirst(request, API_CACHE)
    case 'stale-while-revalidate':
      return staleWhileRevalidate(request, API_CACHE)
    default:
      return networkFirst(request, API_CACHE)
  }
}

// 网络优先策略
async function networkFirst(request, cacheName = DYNAMIC_CACHE) {
  const cache = await caches.open(cacheName)

  try {
    const networkResponse = await fetch(request)
    if (networkResponse.ok) {
      cache.put(request, networkResponse.clone())
    }
    return networkResponse
  } catch {
    console.log('[SW] Network failed, using cache:', request.url)
    const cachedResponse = await cache.match(request)
    return cachedResponse || new Response(JSON.stringify({ error: 'Offline' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' }
    })
  }
}

// 缓存优先策略
async function cacheFirst(request, cacheName = STATIC_CACHE) {
  const cachedResponse = await caches.match(request)
  if (cachedResponse) {
    return cachedResponse
  }

  try {
    const networkResponse = await fetch(request)
    const cache = await caches.open(cacheName)
    cache.put(request, networkResponse.clone())
    return networkResponse
  } catch {
    console.log('[SW] Fetch failed:', request.url)
    return new Response('Offline', { status: 503 })
  }
}

// Stale-While-Revalidate 策略
async function staleWhileRevalidate(request, cacheName = DYNAMIC_CACHE) {
  const cache = await caches.open(cacheName)
  const cachedResponse = await cache.match(request)

  // 后台更新缓存
  const fetchPromise = fetch(request).then((networkResponse) => {
    if (networkResponse.ok) {
      cache.put(request, networkResponse.clone())
    }
    return networkResponse
  }).catch(() => null)

  // 返回缓存或等待网络响应
  return cachedResponse || fetchPromise
}

// 后台同步
self.addEventListener('sync', (event) => {
  console.log('[SW] Background sync:', event.tag)

  if (event.tag === 'sync-data') {
    event.waitUntil(syncData())
  }
})

async function syncData() {
  console.log('[SW] Syncing data...')
  // 从IndexedDB读取待同步数据并同步
}

// 推送通知
self.addEventListener('push', (event) => {
  console.log('[SW] Push received:', event)

  const data = event.data?.json() || {}
  const options = {
    body: data.body || '有新的更新',
    icon: '/icon-192.png',
    badge: '/badge-72.png',
    vibrate: [100, 50, 100],
    data: data.data || {},
    actions: data.actions || [],
  }

  event.waitUntil(self.registration.showNotification(data.title || 'LiangHua', options))
})

// 通知点击
self.addEventListener('notificationclick', (event) => {
  console.log('[SW] Notification clicked:', event)

  event.notification.close()

  event.waitUntil(
    clients.matchAll({ type: 'window' }).then((clientList) => {
      for (const client of clientList) {
        if (client.url === '/' && 'focus' in client) {
          return client.focus()
        }
      }
      if (clients.openWindow) {
        return clients.openWindow('/')
      }
    })
  )
})

// 清理过期缓存
async function cleanupExpiredCache() {
  const cache = await caches.open(API_CACHE)
  const requests = await cache.keys()

  for (const request of requests) {
    const response = await cache.match(request)
    if (response) {
      const date = response.headers.get('date')
      if (date) {
        const age = Date.now() - new Date(date).getTime()
        if (age > 300000) { // 5分钟
          await cache.delete(request)
        }
      }
    }
  }
}

// 定期清理
self.addEventListener('message', (event) => {
  if (event.data === 'cleanup') {
    event.waitUntil(cleanupExpiredCache())
  }
})

console.log('[SW] Service Worker loaded')
