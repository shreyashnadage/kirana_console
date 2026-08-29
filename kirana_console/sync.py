"""
The real sync engine: legacy PHP ERP -> ERPNext. This is what the
"Sync Now" button on the Stockist Dashboard actually calls. Runs as a
background job since a full catalog sync can take a while.

Ported from the standalone scripts used to validate this against the first
tenant (Amol Vadgaon Enterprises) - see D:/Kirana-app/sync/*.py in the
project history. Logic is unchanged; only the transport changed (direct
frappe.get_doc/frappe.db calls instead of the REST API, since this runs
inside the Frappe process now).
"""
import re
from collections import Counter, defaultdict

import frappe
from frappe.utils import now_datetime

from kirana_console.erp_client import get_client, fetch_products, fetch_customers

DEFAULT_ITEM_GROUP = "All Item Groups"
DEFAULT_CUSTOMER_GROUP = "Retail Shop"
DEFAULT_TERRITORY = "India"
DEFAULT_PRICE_LIST = "Standard Selling"
DEFAULT_CURRENCY = "INR"

CATEGORY_RULES = [
	("Edible Oil", r"\b(SOYA|SUNFLOWER|\bSF\b|PALM|\bPAM\b|GROUNDNUT|SHENGDANA|TIL\s*TEL|OIL)\b"),
	("Rice", r"\b(RICE|CHAWAL|TANDUL|BASMATI|IDLI\s*RICE)\b"),
	("Atta & Flour", r"\b(ATTA|MAIDA|GAHU|RAWA|RAVA|BESAN|PITH|SUJI|SOOJI)\b"),
	("Pulses & Dal", r"\b(DAL|DALL|HARBARDAL|HARBRDAL|CHANA|TUR|MOONG|MASOOR|MUG|UDID)\b"),
	("Sugar & Jaggery", r"\b(SUGAR|GUL|GOOD|GUR)\b"),
	("Spices & Masala", r"\b(MASALA|JIRA|MOHARI|HALAD|MIRCHI|DHNE|DHANE|GARAM\s*MASALA|KANDA\s*LASUN)\b"),
	("Soap & Detergent", r"\b(SABAN|SOPE|SOAP|DETERGENT|POWDER|PAVDER|WHEEL|AREAL|ARIAL|SHINE|SURF|RIN|TIDE|NIRMA)\b"),
	("Dishwash", r"\b(DISHWASH|DISH\s*BAR|DISH\s*GEL)\b"),
	("Snacks & Namkeen", r"\b(CHIVDA|SEV|FARSAN|BISCUIT|CHUTNEY|NAMKEEN|KURKURE|WAFER)\b"),
	("Stationery", r"\b(NOTE\s*BOOK|NOTEBOOK|PEN\b|PENCIL|BOOK\b)\b"),
	("Household & Utensils", r"\b(BARTAN|STEEL|PLASTIC\s*(BOX|MUG|BUCKET))\b"),
	("Tea & Beverages", r"\b(TEA\b|CHAHA|COFFEE|SARBAT|SYRUP)\b"),
	("Dairy & Ghee", r"\b(GHEE\b|TOOP|MILK|DUDH|PANEER)\b"),
]
_COMPILED_RULES = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in CATEGORY_RULES]


def categorize(name: str) -> str:
	for cat, pat in _COMPILED_RULES:
		if pat.search(name or ""):
			return cat
	return "Uncategorized"


def propagate_by_brand(products, cats, threshold=0.85, min_known=3):
	by_brand = defaultdict(list)
	for p, cat in zip(products, cats):
		brand = (p.get("BRAND_NM") or "").strip()
		if brand:
			by_brand[brand].append(cat)
	brand_category = {}
	for brand, brand_cats in by_brand.items():
		known = [c for c in brand_cats if c != "Uncategorized"]
		if len(known) < min_known:
			continue
		top_cat, top_n = Counter(known).most_common(1)[0]
		if top_n / len(known) >= threshold:
			brand_category[brand] = top_cat
	new_cats = []
	for p, cat in zip(products, cats):
		if cat == "Uncategorized":
			brand = (p.get("BRAND_NM") or "").strip()
			if brand in brand_category:
				cat = brand_category[brand]
		new_cats.append(cat)
	return new_cats


def ensure_item_groups(categories):
	for cat in set(categories):
		if not frappe.db.exists("Item Group", cat):
			frappe.get_doc({
				"doctype": "Item Group", "item_group_name": cat,
				"parent_item_group": DEFAULT_ITEM_GROUP, "is_group": 0,
			}).insert(ignore_permissions=True)


def ensure_brands(products):
	brands = {(p.get("BRAND_NM") or "").strip() for p in products if p.get("BRAND_NM")}
	for b in brands:
		if not frappe.db.exists("Brand", b):
			frappe.get_doc({"doctype": "Brand", "brand": b}).insert(ignore_permissions=True)


def ensure_uoms(products):
	units = {p["PRIM_UNIT"] for p in products if p.get("PRIM_UNIT")}
	units |= {p["SEC_UNIT"] for p in products if p.get("SEC_UNIT")}
	for uom in units:
		if not frappe.db.exists("UOM", uom):
			frappe.get_doc({"doctype": "UOM", "uom_name": uom}).insert(ignore_permissions=True)


def sync_items(products: list) -> dict:
	ensure_uoms(products)
	cats = [categorize(p.get("PROD_NAME") or "") for p in products]
	cats = propagate_by_brand(products, cats)
	ensure_item_groups(cats)
	ensure_brands(products)

	wi_map = dict(frappe.db.sql("select item_code, name from `tabWebsite Item`"))

	ok, failed = 0, 0
	for p, cat in zip(products, cats):
		item_code = f"ERP-{p['PROD_ID']}"
		stock_uom = p.get("PRIM_UNIT") or "Nos"
		brand = (p.get("BRAND_NM") or "").strip() or None

		uoms = []
		sec_unit = p.get("SEC_UNIT")
		box_capacity = p.get("BOX_CAPACITY") or 0
		if sec_unit and sec_unit != stock_uom and box_capacity > 0:
			uoms.append({"uom": sec_unit, "conversion_factor": box_capacity})

		payload = {
			"item_group": cat,
			"brand": brand,
			"stock_uom": stock_uom,
			"is_stock_item": 1,
			"disabled": 0 if p.get("ACTIVE_FLAG") == 1 else 1,
			"gst_hsn_code": p.get("HSN_NO") or None,
			"standard_rate": p.get("RATE") or 0,
			"description": p.get("PROD_NAME_MAR") or p["PROD_NAME"],
		}
		try:
			if frappe.db.exists("Item", item_code):
				# Some Item fields (gst_hsn_code, etc.) aren't plain columns -
				# frappe.db.set_value's raw SQL breaks on them. Load+save
				# routes through Frappe's real field handling instead.
				item = frappe.get_doc("Item", item_code)
				item.update(payload)
				existing_uoms = {u.uom for u in item.uoms}
				for u in uoms:
					if u["uom"] not in existing_uoms:
						item.append("uoms", u)
				item.flags.ignore_permissions = True
				item.save(ignore_permissions=True)
			else:
				doc = {
					"doctype": "Item", "item_code": item_code,
					"item_name": p["PROD_NAME"][:140], "uoms": uoms, **payload,
				}
				frappe.get_doc(doc).insert(ignore_permissions=True)

			if item_code in wi_map:
				wi = frappe.get_doc("Website Item", wi_map[item_code])
				wi.item_group = cat
				wi.brand = brand
				wi.flags.ignore_permissions = True
				wi.save(ignore_permissions=True)
			ok += 1
		except Exception:
			failed += 1
			frappe.log_error(title=f"kirana_console sync_items: {item_code}")
	frappe.db.commit()
	return {"items_synced": ok, "items_failed": failed}


def sync_prices(products: list) -> dict:
	ok, failed = 0, 0
	for p in products:
		item_code = f"ERP-{p['PROD_ID']}"
		rate = p.get("RATE") or 0
		if rate <= 0:
			continue
		try:
			existing = frappe.db.get_value(
				"Item Price", {"item_code": item_code, "price_list": DEFAULT_PRICE_LIST}, "name"
			)
			payload = {
				"item_code": item_code, "price_list": DEFAULT_PRICE_LIST,
				"price_list_rate": rate, "currency": DEFAULT_CURRENCY, "selling": 1,
			}
			if existing:
				frappe.db.set_value("Item Price", existing, payload, update_modified=False)
			else:
				frappe.get_doc({"doctype": "Item Price", **payload}).insert(ignore_permissions=True)
			ok += 1
		except Exception:
			failed += 1
			frappe.log_error(title=f"kirana_console sync_prices: {item_code}")
	frappe.db.commit()
	return {"prices_synced": ok, "prices_failed": failed}


def sync_customers(customers: list) -> dict:
	# The document name needs the "[ERP-1301]" suffix to stay unique (two
	# shops can share a business name), but that suffix must never leak into
	# anything customer-facing (storefront greeting, admin lists) - it broke
	# exactly that way once already. So: insert/lookup by the suffixed name,
	# then force customer_name back to the clean display name immediately.
	ok, failed = 0, 0
	for c in customers:
		display_name = c["CUST_NAME"][:140]
		cust_name = f"{display_name} [ERP-{c['CUST_ID']}]"[:140]
		payload = {
			"customer_group": DEFAULT_CUSTOMER_GROUP, "territory": DEFAULT_TERRITORY,
			"customer_type": "Individual", "default_currency": DEFAULT_CURRENCY,
			"mobile_no": c.get("CUST_MOBILE") or None,
			"credit_limit": c.get("CREDIT_LIMIT") or 0,
			"legacy_due_amount": c.get("CUST_DUE") or 0,
		}
		try:
			if frappe.db.exists("Customer", cust_name):
				# credit_limit lives in a child table, not a plain column -
				# db.set_value's raw SQL breaks on it. Load+save instead.
				cust = frappe.get_doc("Customer", cust_name)
				cust.update(payload)
				cust.customer_name = display_name
				cust.flags.ignore_permissions = True
				cust.save(ignore_permissions=True)
			else:
				doc = frappe.get_doc({
					"doctype": "Customer", "customer_name": cust_name, **payload,
				})
				doc.insert(ignore_permissions=True)
				doc.customer_name = display_name
				doc.flags.ignore_permissions = True
				doc.save(ignore_permissions=True)
			ok += 1
		except Exception:
			failed += 1
			frappe.log_error(title=f"kirana_console sync_customers: {cust_name}")
	frappe.db.commit()
	return {"customers_synced": ok, "customers_failed": failed}


def _run_sync():
	session, base_url = get_client()
	products = fetch_products(session, base_url)
	customers = fetch_customers(session, base_url)

	result = {}
	result.update(sync_items(products))
	result.update(sync_prices(products))
	result.update(sync_customers(customers))

	summary = (
		f"Items: {result['items_synced']} synced, {result['items_failed']} failed. "
		f"Prices: {result['prices_synced']} synced. "
		f"Customers: {result['customers_synced']} synced, {result['customers_failed']} failed."
	)
	frappe.db.set_value(
		"Kirana Console Settings", None,
		{"last_synced": now_datetime(), "last_sync_summary": summary},
	)
	frappe.db.commit()
	return summary


@frappe.whitelist()
def sync_now():
	"""Called by the dashboard's Sync Now button. Runs in the background -
	a full catalog sync can take a while and shouldn't hold the request open."""
	frappe.enqueue(
		"kirana_console.sync.run_sync_job", queue="long", timeout=1800,
		job_name="kirana_console_sync",
	)
	return {"status": "started"}


def run_sync_job():
	try:
		summary = _run_sync()
		frappe.publish_realtime(
			"kirana_console_sync_done", {"status": "success", "summary": summary},
			user=frappe.session.user,
		)
	except Exception as e:
		frappe.log_error(title="kirana_console sync failed")
		frappe.publish_realtime(
			"kirana_console_sync_done", {"status": "error", "message": str(e)},
			user=frappe.session.user,
		)


def scheduled_sync():
	"""Runs automatically every 6 hours as a safety net, in addition to the
	manual Sync Now button."""
	settings = frappe.get_single("Kirana Console Settings")
	if not (settings.erp_base_url and settings.erp_username):
		return  # not configured for this tenant yet
	run_sync_job()
