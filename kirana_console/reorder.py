import frappe
from frappe import _
from webshop.webshop.shopping_cart.cart import get_party, update_cart


@frappe.whitelist()
def reorder(sales_order):
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in to reorder"), frappe.PermissionError)

	so = frappe.get_doc("Sales Order", sales_order)
	party = get_party()
	if not party or so.customer != party.name:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	added = 0
	skipped = []
	for item in so.items:
		is_published = frappe.db.get_value("Website Item", {"item_code": item.item_code}, "published")
		if not is_published:
			skipped.append(item.item_code)
			continue
		update_cart(item.item_code, item.qty)
		added += 1

	return {"added": added, "skipped": skipped}
