// "Send to Customers" on the WhatsApp Video Drop form - the curate/send
// step of the video intake pipeline. This form is what Amol lands on when
// he taps the link in the WhatsApp confirmation reply after dropping a
// marketing video with a #tag. Deliberately simplified (see the Property
// Setters hiding internal/bookkeeping fields) so the only real decisions
// left are: what to say, and who gets it.
frappe.ui.form.on("WhatsApp Video Drop", {
	refresh: function (frm) {
		if (frm.doc.status === "Sent") {
			frm.dashboard.set_headline(
				__("Sent to {0} customers ({1} failed).", [frm.doc.sent_count || 0, frm.doc.failed_count || 0])
			);
			return;
		}
		frm.add_custom_button(__("Send to Customers"), function () {
			show_send_dialog(frm);
		}).addClass("btn-primary");
	},
});

function show_send_dialog(frm) {
	frappe.call({
		method: "kirana_console.video_drops.get_audience_stats",
		callback: function (r) {
			var stats = r.message || { total_opted_in: 0, routes: [] };
			open_dialog(frm, stats);
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
		title: __("Send \"{0}\" to Customers", [frm.doc.tag]),
		fields: [
			{
				fieldtype: "Small Text",
				fieldname: "message",
				label: __("Message"),
				reqd: 1,
				default: frm.doc.curated_message || frm.doc.raw_caption || "",
			},
			{
				fieldtype: "Section Break",
				fieldname: "audience_section",
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
				__("This will send the video to {0}. This can't be undone. Continue?", [count_note]),
				function () {
					dialog.hide();
					frappe.call({
						method: "kirana_console.video_drops.send_video_drop",
						args: {
							tag: frm.doc.tag,
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
							frm.reload_doc();
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

	// Neither per-field `onchange` nor a delegated DOM listener fires
	// reliably in sync with Frappe's own internal value updates across
	// Select/MultiCheck/MultiSelectList (raced and showed stale counts in
	// testing) - a cheap poll while the dialog is open sidesteps that
	// entirely instead of chasing each fieldtype's actual event timing.
	var preview_timer = setInterval(update_preview, 400);
	dialog.$wrapper.on("hidden.bs.modal", function () {
		clearInterval(preview_timer);
	});

	dialog.show();
	update_preview();
}
