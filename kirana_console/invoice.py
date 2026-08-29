import frappe
from frappe import _
from frappe.utils.pdf import get_pdf
from frappe.www.printview import get_html_and_style
from webshop.webshop.shopping_cart.cart import get_party


@frappe.whitelist()
def download_invoice(sales_order):
	# Ownership check first, same pattern as kirana_console.reorder: even
	# though Sales Order now has a Custom DocPerm (read/print) for the
	# Customer role, that alone would let one customer read ANY sales
	# order unless every portal user also has a matching User Permission
	# scoping them to their own Customer (see
	# sync/create_user_permissions.py) - this check is the belt to that
	# braces.
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in to download your invoice"), frappe.PermissionError)

	party = get_party()
	customer = frappe.db.get_value("Sales Order", sales_order, "customer")
	if not party or customer != party.name:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	# frappe.get_print(as_pdf=True) re-enters the full /printview request
	# pipeline internally, which errors with a bare OSError when called
	# from inside another whitelisted method's request context. Render
	# the print HTML directly instead and hand it to the PDF generator
	# ourselves - same building blocks, without that nested-request path.
	print_format = frappe.db.get_value(
		"Property Setter",
		{"property": "default_print_format", "doc_type": "Sales Order"},
		"value",
	)
	# no_letterhead=1: the default letterhead template reliably crashes
	# wkhtmltopdf with a bare OSError when rendered from inside a live
	# request (reproduces even via console only when a request context is
	# present; renders fine as plain HTML and fine as a PDF once the
	# letterhead is skipped). Not worth chasing further for a v1 invoice -
	# the letterhead is cosmetic branding, not part of the invoice data.
	result = get_html_and_style("Sales Order", sales_order, print_format, no_letterhead=1)
	pdf = get_pdf(result["html"], {"page-size": "A4"})

	frappe.local.response.filename = "Invoice-{0}.pdf".format(sales_order.replace(" ", "-").replace("/", "-"))
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "pdf"
