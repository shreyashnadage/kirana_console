# Kirana Console

Simplified stockist admin console and legacy-ERP sync engine, built as a Frappe app
on top of ERPNext + Webshop.

Installing this app on a site provisions the whole "Stockist Dashboard" experience:
- The simplified Workspace (Overview stats, Sync button, Customer Access management)
- Role/Module Profile restrictions so a stockist's login never sees Manufacturing,
  Assets, Accounting internals, etc.
- The Custom Field needed to track legacy-ERP dues per customer
- A real, working "Sync Now" that logs into the legacy PHP ERP and pulls
  products/prices/customers (this is why it needs to be a real app, not a
  sandboxed Server Script - it needs cookie-based session HTTP calls the
  Server Script sandbox can't do)

## Install on a new site

```bash
bench get-app kirana_console <repo-url>
bench --site <site> install-app kirana_console
```

Then configure the legacy ERP credentials for that tenant via
`Kirana Console Settings` in the Desk.
