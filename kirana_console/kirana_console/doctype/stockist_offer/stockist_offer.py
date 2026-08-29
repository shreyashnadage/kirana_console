# Copyright (c) 2026, Kirana App and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class StockistOffer(Document):
	def validate(self):
		if not self.tiers:
			frappe.throw("Add at least one spend-and-save tier")
		for tier in self.tiers:
			if tier.discount_percentage <= 0 or tier.discount_percentage > 100:
				frappe.throw("Discount % must be between 0 and 100 (tier: spend Rs {0})".format(tier.min_amount))

	def on_update(self):
		self.sync_promotional_scheme()

	def on_trash(self):
		if self.linked_scheme and frappe.db.exists("Promotional Scheme", self.linked_scheme):
			frappe.delete_doc("Promotional Scheme", self.linked_scheme, ignore_permissions=True, force=True)

	def sync_promotional_scheme(self):
		scheme_name = self.linked_scheme
		if scheme_name and frappe.db.exists("Promotional Scheme", scheme_name):
			scheme = frappe.get_doc("Promotional Scheme", scheme_name)
		else:
			scheme = frappe.new_doc("Promotional Scheme")
			scheme.name = "Stockist Offer - " + self.offer_name
			scheme.title = self.offer_name

		scheme.apply_on = "Transaction"
		scheme.price_or_product_discount = "Price"
		scheme.selling = 1
		scheme.disable = 0 if self.active else 1
		scheme.valid_upto = self.valid_upto

		if self.audience == "Selected Customers":
			scheme.applicable_for = "Customer"
			scheme.set("customer", [{"customer": row.customer} for row in self.customers])
		else:
			scheme.applicable_for = None
			scheme.set("customer", [])

		scheme.set("price_discount_slabs", [])
		for tier in self.tiers:
			scheme.append("price_discount_slabs", {
				"rule_description": "Spend Rs {0}+, get {1}% off".format(tier.min_amount, tier.discount_percentage),
				"min_amount": tier.min_amount,
				"rate_or_discount": "Discount Percentage",
				"discount_percentage": tier.discount_percentage,
				"disable": 0 if tier.active else 1,
			})

		scheme.flags.ignore_permissions = True
		scheme.save(ignore_permissions=True)

		if self.linked_scheme != scheme.name:
			frappe.db.set_value("Stockist Offer", self.name, "linked_scheme", scheme.name, update_modified=False)
