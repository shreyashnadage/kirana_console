// Hides Desk navbar escape hatches ("Desktop", "Workspaces") for restricted
// stockist logins, so the only way back to a workspace is via the sidebar
// we actually built for them. System Managers (us, during support) are
// unaffected.
//
// Runs immediately (not inside frappe.ready) because the bare module-icon
// grid at /desk and /app loads a lighter bundle where frappe.ready isn't
// defined yet when this script executes.
(function () {
	// Brand the sidebar workspace-header icon (top-left, next to the
	// current workspace name) with Amol's logo instead of the generic
	// grey fallback glyph. Workspace.icon is a fixed icon-picker field,
	// not an arbitrary image, so there's no Settings field for this -
	// applies for every Desk user, System Manager included.
	var style = document.createElement("style");
	style.textContent =
		".header-logo .icon-container {" +
		"  background-image: url(/files/amol-vadgaon-logo.jpg);" +
		"  background-size: cover;" +
		"  background-position: center;" +
		"}" +
		".header-logo .icon-container svg { display: none; }" +

		/* Brand-color pass: Desk ships with a flat near-black primary color
		   (--primary) that every primary button, active nav state, link
		   focus ring, and progress indicator inherits from. Overriding just
		   these two tokens re-skins all of that consistently across every
		   Desk page for free, without touching any layout, list view, or
		   form behavior - the actual widgets stay 100% stock Frappe. */
		":root {" +
		"  --primary: #3E2417 !important;" +
		"  --primary-color: #3E2417 !important;" +
		"}" +
		".btn-primary, .btn-primary:hover, .btn-primary:focus {" +
		"  background-color: #3E2417 !important;" +
		"  border-color: #3E2417 !important;" +
		"}" +
		".btn-primary:hover { background-color: #2C1A10 !important; }" +
		"a, .text-primary { color: #3E2417; }" +
		".indicator-pill.orange, .indicator.orange { background: #EE8B1D; }" +

		/* Stock ERPNext's "Getting Started" onboarding checklist (Selling
		   Setup, Buying Setup, etc.) floats over list views promoting
		   generic ERPNext modules (Create Supplier, Review Buying
		   Settings...) nobody running this stockist app needs - pure
		   confusion for Amol, not actual onboarding for this app. */
		".getting-started, [class*=\"onboarding\"] { display: none !important; }";
	document.head.appendChild(style);

	// Sidebar completeness fix: the Stockist Dashboard workspace has 7
	// "Quick Links" shortcut cards, but Frappe's sidebar auto-builds its own
	// left-nav list from those shortcuts using a heuristic that only
	// understands DocType/Page/Report targets - it silently drops any
	// shortcut pointing at a custom app page (Customer Access, Marketing,
	// Sync Settings all route to /app/<page>, not a doctype), so 3 of the 7
	// never made it into the sidebar at all. The Workspace Link child table
	// that would normally control this doesn't support linking to another
	// Workspace or a raw URL either (only DocType/Page/Report), so there's
	// no clean server-side fix - inject the missing rows directly.
	function ensureSidebarLinks() {
		var labels = document.querySelectorAll(".sidebar-item-label");
		// Anchor was the "Reports" shortcut (renamed to "Invoices" -> Sales
		// Invoice, since "Reports" had always dead-ended at the Sales Order
		// doctype and never showed anything GST-relevant). Any real DocType
		// shortcut works as an anchor here - it just needs one that's
		// guaranteed to render natively in the sidebar to hang the injected
		// rows off of.
		var anchorItem = Array.prototype.find.call(labels, function (el) {
			return el.textContent.trim() === "Invoices";
		});
		if (!anchorItem) return;
		var reportsRow = anchorItem.closest(".standard-sidebar-item");
		var container = reportsRow && reportsRow.parentElement;
		if (!container || container.querySelector('[data-sk-extra="1"]')) return;

		function makeItem(label, href, icon) {
			var div = document.createElement("div");
			div.className = "standard-sidebar-item";
			div.setAttribute("data-sk-extra", "1");
			div.innerHTML =
				'<a href="' + href + '" class="item-anchor">' +
				'<span class="sidebar-item-icon text-ink-gray-7">' +
				'<svg class="icon text-ink-gray-7 current-color icon-sm" stroke="currentColor" aria-hidden="true">' +
				'<use href="#icon-' + icon + '"></use></svg>' +
				"</span>" +
				'<span class="sidebar-item-label">' + label + "</span>" +
				'<div class="sidebar-item-control"></div>' +
				"</a>";
			return div;
		}

		container.appendChild(makeItem("Marketing", "/app/marketing", "notification"));
		container.appendChild(makeItem("Sync Settings", "/app/kirana-console-settings", "setting"));

		var ordersItem = Array.prototype.find.call(labels, function (el) {
			return el.textContent.trim() === "Orders";
		});
		var ordersRow = ordersItem && ordersItem.closest(".standard-sidebar-item");
		// Each sidebar row turns out to sit in its own individual wrapper
		// (not one shared list container, despite how it looks visually),
		// so the insertion point's own parent has to be used directly -
		// using the "container" found via Reports above throws
		// NotFoundError here since it isn't actually an ancestor of Orders.
		if (ordersRow && ordersRow.parentElement) {
			ordersRow.parentElement.insertBefore(makeItem("Customer Access", "/app/customer-access", "contact"), ordersRow);
		}
	}
	new MutationObserver(ensureSidebarLinks).observe(document.body, { childList: true, subtree: true });
	ensureSidebarLinks();

	function isSystemManager() {
		try {
			if (window.frappe && frappe.user_roles) {
				return frappe.user_roles.includes("System Manager");
			}
			if (window.frappe && frappe.boot && frappe.boot.user && frappe.boot.user.roles) {
				return frappe.boot.user.roles.includes("System Manager");
			}
		} catch (e) {}
		return false;
	}

	if (isSystemManager()) {
		return;
	}

	// The generic module-icon grid ("Desktop") is confusing for a
	// non-tech-savvy user and lists ERPNext modules he has no business
	// touching directly. Any stray way of landing on it (bookmark, back
	// button, closing a dialog) should bounce straight to his own
	// dashboard instead.
	function redirectFromDesktop() {
		var path = window.location.pathname.replace(/\/+$/, "");
		if (path === "/app" || path === "/desk") {
			window.location.replace("/app/stockist-dashboard");
		}
	}

	redirectFromDesktop();

	function hideItems() {
		document.querySelectorAll(".menu-item-title").forEach(function (el) {
			var text = (el.textContent || "").trim();
			if (text === "Desktop" || text === "Workspaces") {
				var item = el.closest("a") || el.closest("li") || el;
				item.style.display = "none";
			}
		});
	}

	// The settings dropdown only renders its items when opened, so hook the
	// click that opens it rather than watching the whole (heavily-churning)
	// Desk DOM tree.
	document.addEventListener(
		"click",
		function () {
			setTimeout(hideItems, 30);
		},
		true // capture phase - fires even if the dropdown toggle stops bubble propagation
	);

	// Also catch client-side route changes (e.g. clicking a link that lands
	// back on the bare grid without a full page reload).
	document.addEventListener("click", function () {
		setTimeout(redirectFromDesktop, 50);
	}, true);
})();
