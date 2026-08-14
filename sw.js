const CACHE_NAME = 'erp-vendas-v2';

// Lista das páginas principais para pré-carregar
const URLS_TO_CACHE = [
  '/',
  '/login',
  '/dashboard',
  '/pdv',
  '/products',
  '/customers',
  '/receivables',
  '/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(URLS_TO_CACHE).catch((err) => console.log('Erro ao pré-armazenar cache:', err));
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

// Estratégia Network First com Fallback para Cache:
// Tenta pegar da internet para manter os dados atualizados; se estiver sem conexão, serve do cache do celular!
self.addEventListener('fetch', (event) => {
  if (event.request.method === 'GET') {
    event.respondWith(
      fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(event.request, responseClone);
            });
          }
          return networkResponse;
        })
        .catch(async () => {
          // Se estiver SEM internet, busca a página salva no cache do celular
          const cachedResponse = await caches.match(event.request);
          if (cachedResponse) {
            return cachedResponse;
          }
          // Se for uma navegação de página nova, abre o PDV ou Dashboard do cache
          if (event.request.mode === 'navigate') {
            return (await caches.match('/pdv')) || (await caches.match('/dashboard')) || (await caches.match('/'));
          }
          return new Response('Sem conexão com a internet', { status: 503, statusText: 'Offline' });
        })
    );
  }
});