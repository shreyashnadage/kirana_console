import frappe


@frappe.whitelist()
def set_language(lang):
	# Only ever touches the calling user's own record - never an
	# arbitrary user - so ignore_permissions here doesn't open anything
	# beyond what the user could already do to themselves.
	if lang not in ("en", "mr"):
		frappe.throw("Unsupported language")

	if frappe.session.user == "Guest":
		frappe.local.cookie_manager.set_cookie("preferred_language", lang)
		return {"status": "ok", "mode": "cookie"}

	frappe.db.set_value("User", frappe.session.user, "language", lang)
	frappe.db.commit()
	return {"status": "ok", "mode": "user"}
