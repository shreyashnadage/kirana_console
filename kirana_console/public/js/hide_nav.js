// Hides Desk navbar escape hatches ("Desktop", "Workspaces") for restricted
// stockist logins, so the only way back to a workspace is via the sidebar
// we actually built for them. System Managers (us, during support) are
// unaffected.
frappe.ready(function () {
	if (frappe.user_roles && frappe.user_roles.includes("System Manager")) {
		return;
	}

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
});
