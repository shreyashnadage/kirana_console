// Hides Desk navbar escape hatches ("Desktop", "Workspaces") for restricted
// stockist logins, so the only way back to a workspace is via the sidebar
// we actually built for them. System Managers (us, during support) are
// unaffected.
//
// Runs immediately (not inside frappe.ready) because the bare module-icon
// grid at /desk and /app loads a lighter bundle where frappe.ready isn't
// defined yet when this script executes.
(function () {
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
