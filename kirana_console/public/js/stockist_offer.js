// "Share on WhatsApp" on the Stockist Offer form - generates a branded
// promo card from this offer's real data (name, tiers, validity) and sends
// it as a WhatsApp image, reusing the exact audience-picker pattern already
// proven on the video drop flow. The card is never cached - every share
// re-renders fresh from whatever the offer says right now, so an edited
// offer can never go out with stale terms.
frappe.ui.form.on("Stockist Offer", {
	refresh: function (frm) {
		if (frm.is_new()) {
			return;
		}
		var btn = frm.add_custom_button(__("Share on WhatsApp"), function () {
			show_share_dialog(frm);
		});
		btn.prepend(whatsapp_icon_svg_fallback());
	},
});

// whatsapp_connect.js (loaded on Kirana Console Settings) defines this
// helper already, but doctype_js only loads per-doctype, so it isn't
// guaranteed to be present here - a tiny local fallback avoids depending on
// load order between the two.
function whatsapp_icon_svg_fallback() {
	if (typeof whatsapp_icon_svg === "function") {
		return whatsapp_icon_svg(14, "vertical-align:-2px; margin-right:5px;");
	}
	return "";
}

function show_share_dialog(frm) {
	frappe.call({
		method: "kirana_console.video_drops.get_audience_stats",
		callback: function (r) {
			open_dialog(frm, r.message || { total_opted_in: 0, routes: [] });
		},
	});
}

function open_dialog(frm, stats) {
	var routes = stats.routes || [];
	var route_options = routes.map(function (row) {
		return { label: row.route + " (" + row.customer_count + ")", value: row.route };
	});
	var route_counts = {};
	routes.forEach(function (row) {
		route_counts[row.route] = row.customer_count;
	});

	var SEND_TO_ROUTES = __("Customers on selected routes");
	var SEND_TO_CUSTOMERS = __("Pick specific customers");

	var dialog = new frappe.ui.Dialog({
		title: __("Share \"{0}\" on WhatsApp", [frm.doc.offer_name]),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "card_preview",
				options: "<div style=\"text-align:center; padding: 10px 0;\">" +
					"<div class=\"text-muted\" style=\"font-size:12.5px;\">" + __("Generating preview...") + "</div></div>",
			},
			{ fieldtype: "Section Break" },
			{
				fieldtype: "Small Text",
				fieldname: "message",
				label: __("Caption"),
				reqd: 1,
				default: __("Check out our offer: {0}", [frm.doc.offer_name]),
			},
			{
				fieldtype: "Section Break",
				label: __("Who gets this"),
			},
			{
				fieldtype: "Select",
				fieldname: "send_to",
				label: __("Send to"),
				options: [__("Everyone opted in"), SEND_TO_ROUTES, SEND_TO_CUSTOMERS].join("\n"),
				default: __("Everyone opted in"),
				reqd: 1,
			},
			{
				fieldtype: "MultiCheck",
				fieldname: "routes",
				label: __("Routes"),
				options: route_options,
				columns: 2,
				depends_on: "eval:doc.send_to==\"" + SEND_TO_ROUTES + "\"",
			},
			{
				fieldtype: "MultiSelectList",
				fieldname: "customers",
				label: __("Customers"),
				get_data: function (txt) {
					return frappe.call({
						method: "kirana_console.video_drops.search_customers",
						args: { txt: txt },
					}).then(function (r) { return r.message || []; });
				},
				depends_on: "eval:doc.send_to==\"" + SEND_TO_CUSTOMERS + "\"",
			},
			{
				fieldtype: "HTML",
				fieldname: "audience_preview",
				options: "<div></div>",
			},
		],
		primary_action_label: __("Send"),
		primary_action: function (values) {
			var by_route = values.send_to === SEND_TO_ROUTES;
			var by_customer = values.send_to === SEND_TO_CUSTOMERS;
			var route_list = by_route ? values.routes || [] : [];
			var customer_list = by_customer ? values.customers || [] : [];

			if (by_route && !route_list.length) {
				frappe.msgprint(__("Pick at least one route, or choose \"Everyone opted in\" instead."));
				return;
			}
			if (by_customer && !customer_list.length) {
				frappe.msgprint(__("Pick at least one customer, or choose \"Everyone opted in\" instead."));
				return;
			}

			var count_note = by_customer
				? __("{0} selected customer(s)", [customer_list.length])
				: by_route
				? __("customers on {0} selected route(s)", [route_list.length])
				: __("every opted-in customer");

			frappe.confirm(
				__("This will send the promo card to {0}. This can't be undone. Continue?", [count_note]),
				function () {
					dialog.hide();
					frappe.call({
						method: "kirana_console.promo_cards.send_offer_card",
						args: {
							offer_name: frm.doc.name,
							message: values.message,
							routes: route_list.join(","),
							customers: customer_list,
						},
						freeze: true,
						freeze_message: __("Sending..."),
						callback: function (r) {
							var result = r.message || {};
							frappe.msgprint({
								title: __("Sent"),
								message: __("{0} sent, {1} failed, out of {2} total.", [
									result.sent, result.failed, result.total,
								]),
								indicator: result.failed ? "orange" : "green",
							});
						},
					});
				}
			);
		},
	});

	function update_preview() {
		var send_to = dialog.get_value("send_to");
		var count;
		if (send_to === SEND_TO_ROUTES) {
			var selected_routes = dialog.get_value("routes") || [];
			count = selected_routes.reduce(function (sum, route) { return sum + (route_counts[route] || 0); }, 0);
		} else if (send_to === SEND_TO_CUSTOMERS) {
			count = (dialog.get_value("customers") || []).length;
		} else {
			count = stats.total_opted_in || 0;
		}
		var label = count === 1 ? __("1 customer") : __("{0} customers", [count]);
		dialog.fields_dict.audience_preview.$wrapper.html(
			'<div style="font-size: 12.5px; color: var(--text-muted); margin-top: -8px;">' +
				"&#128172; " + __("This will reach approximately {0}.", [label]) +
				"</div>"
		);
	}

	var preview_timer = setInterval(update_preview, 400);
	dialog.$wrapper.on("hidden.bs.modal", function () {
		clearInterval(preview_timer);
	});

	dialog.show();
	update_preview();

	// The card render itself (headless Chrome screenshot) takes a moment -
	// fetched after the dialog is already visible so the rest of the form
	// isn't blocked waiting on it.
	frappe.call({
		method: "kirana_console.promo_cards.preview_offer_card",
		args: { offer_name: frm.doc.name },
		callback: function (r) {
			dialog.fields_dict.card_preview.$wrapper.html(
				'<img src="' + r.message + '" style="max-width:100%; max-height:340px; border-radius:10px; border:1px solid var(--border-color);" />'
			);
		},
	});
}
