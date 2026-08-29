import frappe
from webshop.webshop.shopping_cart.cart import get_party


@frappe.whitelist()
def get_offer_nudge():
	if frappe.session.user == "Guest":
		return None

	party = get_party()
	if not party:
		return None

	cart = frappe.db.get_value(
		"Quotation",
		{"party_name": party.name, "docstatus": 0, "quotation_to": "Customer"},
		["name", "total", "grand_total"],
		order_by="creation desc",
		as_dict=True,
	)
	cart_total = cart.total if cart else 0

	offers = frappe.get_all("Stockist Offer", filters={"active": 1}, fields=["name", "audience"])

	all_tiers = []
	for offer in offers:
		if offer.audience == "Selected Customers":
			is_selected = frappe.db.exists(
				"Stockist Offer Customer", {"parent": offer.name, "customer": party.name}
			)
			if not is_selected:
				continue

		doc = frappe.get_cached_doc("Stockist Offer", offer.name)
		for tier in doc.tiers:
			if tier.active:
				all_tiers.append({
					"offer_name": doc.offer_name,
					"min_amount": tier.min_amount,
					"discount_percentage": tier.discount_percentage,
				})

	if not all_tiers:
		return None

	all_tiers.sort(key=lambda t: t["min_amount"])

	unlocked = [t for t in all_tiers if cart_total >= t["min_amount"]]
	next_tiers = [t for t in all_tiers if cart_total < t["min_amount"]]

	current = unlocked[-1] if unlocked else None
	nxt = next_tiers[0] if next_tiers else None

	if not nxt:
		if current:
			return {
				"state": "max_unlocked",
				"offer_name": current["offer_name"],
				"discount_percentage": current["discount_percentage"],
			}
		return None

	progress_from = current["min_amount"] if current else 0
	progress_pct = 0
	if nxt["min_amount"] > progress_from:
		progress_pct = min(
			100,
			round(100 * (cart_total - progress_from) / (nxt["min_amount"] - progress_from)),
		)

	return {
		"state": "in_progress",
		"cart_total": cart_total,
		"amount_needed": round(nxt["min_amount"] - cart_total, 2),
		"next_discount_percentage": nxt["discount_percentage"],
		"next_offer_name": nxt["offer_name"],
		"progress_percentage": max(0, progress_pct),
		"current_discount_percentage": current["discount_percentage"] if current else 0,
	}
