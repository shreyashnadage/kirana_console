import frappe
from frappe.model.document import Document


class StorefrontAnnouncement(Document):
	pass


@frappe.whitelist(allow_guest=True)
def get_active_announcements():
	"""Public endpoint the storefront calls to render current banners/stickers.
	No permission check - this is meant to be visible to every visitor,
	same as any other storefront content."""
	today = frappe.utils.today()
	rows = frappe.db.sql(
		"""
		select title, announcement_type, message, link_url, image
		from `tabStorefront Announcement`
		where is_active = 1
			and (start_date is null or start_date <= %(today)s)
			and (end_date is null or end_date >= %(today)s)
		order by modified desc
		""",
		{"today": today},
		as_dict=True,
	)
	return rows
