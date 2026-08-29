// Service worker for the Vadgaon Store storefront PWA.
// Strategy: cache-first for static assets (css/js/fonts/icons - safe to
// serve stale, they're content-hashed by the build), network-first for
// everything else (product/price/order data must never be served stale
// without at least trying the network first), with an offline fallback
// page for full-page navigations when there's no network and no cache.

const CACHE_VERSION = "v3";
const STATIC_CACHE = "vadgaon-static-" + CACHE_VERSION;
const RUNTIME_CACHE = "vadgaon-runtime-" + CACHE_VERSION;

const APP_SHELL = [
	"/welcome",
	"/all-products",
	"/offline",
	"/assets/kirana_console/icons/icon-192.png",
	"/assets/kirana_console/icons/icon-512.png",
];

self.addEventListener("install", function (event) {
	event.waitUntil(
		caches.open(STATIC_CACHE).then(function (cache) {
			return cache.addAll(APP_SHELL).catch(function () {
				// Don't fail install if one shell URL isn't reachable yet
				// (e.g. first deploy before the site is warm).
			});
		})
	);
	self.skipWaiting();
});

self.addEventListener("activate", function (event) {
	event.waitUntil(
		caches.keys().then(function (keys) {
			return Promise.all(
				keys
					.filter(function (key) {
						return key !== STATIC_CACHE && key !== RUNTIME_CACHE;
					})
					.map(function (key) {
						return caches.delete(key);
					})
			);
		})
	);
	self.clients.claim();
});

function isStaticAsset(url) {
	return (
		url.pathname.indexOf("/assets/") === 0 ||
		url.pathname.indexOf("/files/") === 0 ||
		/\.(css|js|png|jpg|jpeg|svg|woff2?|ttf)$/.test(url.pathname)
	);
}

self.addEventListener("fetch", function (event) {
	const req = event.request;
	if (req.method !== "GET") return;

	const url = new URL(req.url);
	if (url.origin !== self.location.origin) return;

	// Never intercept Desk/admin or API calls - they must always hit the
	// network live (auth state, stock, pricing, order status).
	if (url.pathname.indexOf("/app") === 0 || url.pathname.indexOf("/api/") === 0) {
		return;
	}

	if (isStaticAsset(url)) {
		event.respondWith(
			caches.match(req).then(function (cached) {
				const network = fetch(req)
					.then(function (res) {
						if (res && res.status === 200) {
							caches.open(STATIC_CACHE).then(function (cache) {
								cache.put(req, res.clone());
							});
						}
						return res;
					})
					.catch(function () {
						return cached;
					});
				return cached || network;
			})
		);
		return;
	}

	// Page navigations: network-first, cache fallback, offline page last.
	if (req.mode === "navigate") {
		event.respondWith(
			fetch(req)
				.then(function (res) {
					// Only a real, successful page gets cached - caching a 404
					// or 5xx here would mean a page that starts working again
					// (or never should have 404'd - a permission fix, a typo
					// fix) keeps serving the broken response from cache.
					if (res && res.ok) {
						caches.open(RUNTIME_CACHE).then(function (cache) {
							cache.put(req, res.clone());
						});
					}
					return res;
				})
				.catch(function () {
					return caches.match(req).then(function (cached) {
						return cached || caches.match("/offline");
					});
				})
		);
	}
});
