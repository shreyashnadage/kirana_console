app_name = "kirana_console"
app_title = "Kirana Console"
app_publisher = "Kirana App"
app_description = "Simplified stockist admin console and legacy ERP sync engine"
app_email = "admin@example.com"
app_license = "Proprietary"
required_apps = ["frappe", "erpnext", "webshop"]

# The ?v= query string is a manual cache-buster - this file gets live-patched
# in place (no content-hashed filename), so browsers/CDNs will happily keep
# serving stale bytes under the same URL forever otherwise. Bump it on every
# deploy of hide_nav.js.
app_include_js = ["/assets/kirana_console/js/hide_nav.js?v=7"]

# doctype_js loads only on that doctype's own form, unlike app_include_js
# above which loads everywhere - appropriate here since the Connect
# WhatsApp button only makes sense on the Settings form itself. Unlike
# app_include_js, this is NOT a URL - Frappe resolves it as a literal
# filesystem path (frappe.get_app_path + frappe.read_file) and inlines the
# file's content into the DocType meta's __js field server-side, so a
# ?v= cache-buster suffix here breaks the path lookup entirely rather than
# busting a cache. Cache invalidation for this hook is bench clear-cache,
# not a query string.
doctype_js = {
	"Kirana Console Settings": "public/js/whatsapp_connect.js",
	"WhatsApp Video Drop": "public/js/whatsapp_video_drop.js",
	"Stockist Offer": "public/js/stockist_offer.js",
}

# Fixtures: exporting these means `bench install-app kirana_console` on a
# brand new stockist site provisions the whole admin console automatically -
# no manual re-clicking through the API like we did for the first site.
fixtures = [
	{"dt": "Module Profile", "filters": [["name", "=", "Stockist Admin"]]},
	{"dt": "Server Script", "filters": [["name", "like", "Stockist %"]]},
	{"dt": "Custom HTML Block", "filters": [["name", "like", "Stockist %"]]},
	{"dt": "Workspace", "filters": [["name", "in", [
		"Stockist Dashboard", "Customer Access", "Products Manager", "Marketing",
		"Order Management",
	]]]},
	{"dt": "Custom Field", "filters": [["name", "in", [
		"Customer-legacy_due_amount", "Item-admin_overridden",
	]]]},
	{"dt": "Role", "filters": [["name", "in", ["Customer"]]]},
	# Custom DocPerm additions layered on top of stock ERPNext doctypes -
	# both the Customer-role grants (portal storefront needs) and the
	# Desk-role grants for Amol's roles that would otherwise be silently
	# dropped the moment ANY Custom DocPerm row exists for a doctype (see
	# sync/fix_*_permission_for_customer.py and
	# sync/fix_sales_order_permission_for_customer.py for the full story).
	{"dt": "Custom DocPerm", "filters": [["parent", "in", [
		"Item", "Account", "Sales Order", "Website Item", "Kirana Console Settings",
	]]]},
	# Marathi (and future language) translations for the storefront chrome -
	# see kirana_console.i18n and sync/seed_marathi_translations*.py.
	{"dt": "Translation", "filters": [["language", "=", "mr"]]},
]

# Scheduled sync - runs the legacy ERP pull automatically as a safety net,
# in addition to the manual "Sync Now" button.
scheduler_events = {
	"cron": {
		"0 */6 * * *": [
			"kirana_console.sync.scheduled_sync"
		]
	}
}
