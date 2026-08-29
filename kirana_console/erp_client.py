"""
Client for the legacy PHP ERP (LogiBit Software). Logs in via loginProc.php
(sets a PHP session cookie) then hits the same ajaxFiles/*.php endpoints the
Angular admin UI uses, to pull product and customer data for a given tenant.

Credentials are read per-site from Kirana Console Settings (encrypted at
rest via the Password fieldtype), not from a shared .env file - each
stockist's site has its own legacy ERP login.
"""
import frappe
import requests


class ERPClientError(Exception):
	pass


def get_client() -> tuple[requests.Session, str]:
	"""Returns (logged-in session, base_url) for the current site's configured legacy ERP."""
	settings = frappe.get_single("Kirana Console Settings")
	base_url = (settings.erp_base_url or "").rstrip("/")
	username = settings.erp_username
	password = settings.get_password("erp_password", raise_exception=False)

	if not (base_url and username and password):
		raise ERPClientError(
			"Legacy ERP connection is not configured. Set it up under Kirana Console Settings."
		)

	session = requests.Session()
	resp = session.post(
		f"{base_url}/loginProc.php",
		json={"username": username, "password": password},
		timeout=30,
	)
	resp.raise_for_status()
	data = resp.json()
	if data.get("Status") != "Success":
		raise ERPClientError(f"Legacy ERP login failed: {data}")

	return session, base_url


def fetch_products(session: requests.Session, base_url: str) -> list:
	resp = session.post(
		f"{base_url}/project/ADMIN/ajaxFiles/fetchProdList.php",
		json={"prod_id": "", "campName": "All", "prodType": "", "brndNm": "All"},
		timeout=60,
	)
	resp.raise_for_status()
	return resp.json()["info"]


def fetch_customers(session: requests.Session, base_url: str) -> list:
	resp = session.post(
		f"{base_url}/project/ADMIN/ajaxFiles/fetchCustList.php",
		json={"CUST_ID": "", "routename": "All", "cityName": "All"},
		timeout=60,
	)
	resp.raise_for_status()
	return resp.json()["info"]
