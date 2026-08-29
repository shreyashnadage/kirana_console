app_name = "kirana_console"
app_title = "Kirana Console"
app_publisher = "Kirana App"
app_description = "Simplified stockist admin console and legacy ERP sync engine"
app_email = "admin@example.com"
app_license = "Proprietary"
required_apps = ["frappe", "erpnext", "webshop"]

# Fixtures: exporting these means `bench install-app kirana_console` on a
# brand new stockist site provisions the whole admin console automatically -
# no manual re-clicking through the API like we did for the first site.
fixtures = [
	{"dt": "Module Profile", "filters": [["name", "=", "Stockist Admin"]]},
	{"dt": "Server Script", "filters": [["name", "like", "Stockist %"]]},
	{"dt": "Custom HTML Block", "filters": [["name", "like", "Stockist %"]]},
	{"dt": "Workspace", "filters": [["name", "in", [
		"Stockist Dashboard", "Customer Access", "Products Manager", "Marketing",
	]]]},
	{"dt": "Custom Field", "filters": [["name", "in", [
		"Customer-legacy_due_amount", "Item-admin_overridden",
	]]]},
	{"dt": "Role", "filters": [["name", "in", ["Customer"]]]},
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
