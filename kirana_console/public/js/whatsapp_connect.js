// "Connect WhatsApp" dialog on Kirana Console Settings - self-serve pairing
// for the Neonize demo provider. Only shows up when whatsapp_provider is set
// to "Neonize (Dev Demo)", since Mock has nothing to connect and Meta Cloud
// API is a plain API key (no pairing session to visualize).

// Official WhatsApp glyph path (Simple Icons project, CC0) - filled with
// WhatsApp's own brand green rather than the monochrome Simple Icons intends,
// since that's the actual recognizable mark, not a generic message-bubble icon.
var WHATSAPP_GLYPH_PATH =
	"M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z";

function whatsapp_icon_svg(size, extra_style) {
	return (
		'<svg viewBox="0 0 24 24" width="' + size + '" height="' + size + '" ' +
		'xmlns="http://www.w3.org/2000/svg" style="' + (extra_style || "") + '">' +
		'<path fill="#25D366" d="' + WHATSAPP_GLYPH_PATH + '"/></svg>'
	);
}

frappe.ui.form.on("Kirana Console Settings", {
	refresh: function (frm) {
		if (frm.doc.whatsapp_provider !== "Neonize (Dev Demo)") {
			return;
		}
		var btn = frm.add_custom_button(__("Connect WhatsApp"), function () {
			show_connect_dialog();
		});
		btn.prepend(whatsapp_icon_svg(14, "vertical-align:-2px; margin-right:5px;"));
	},
});

function show_connect_dialog() {
	var dialog = new frappe.ui.Dialog({
		title: __("Connect WhatsApp (Demo)"),
		fields: [{ fieldtype: "HTML", fieldname: "status_html" }],
	});

	var poll_timer = null; // polls the server every 3s for ground truth
	var tick_timer = null; // ticks the visible countdown every 1s between polls
	var last_status = null;

	function stop_timers() {
		if (poll_timer) {
			clearInterval(poll_timer);
			poll_timer = null;
		}
		if (tick_timer) {
			clearInterval(tick_timer);
			tick_timer = null;
		}
	}

	function start_pairing() {
		frappe.call({
			method: "kirana_console.whatsapp.request_pair",
			callback: function () {
				refresh_state();
			},
		});
	}

	function confirm_repair() {
		frappe.confirm(
			__(
				"This disconnects the current WhatsApp number and asks for a new one. " +
					"Anything mid-send may fail. Continue?"
			),
			start_pairing
		);
	}

	function render_connected() {
		var wrapper = dialog.fields_dict.status_html.$wrapper;
		wrapper.html(
			'<div style="text-align:center; padding: 24px 8px;">' +
				'<div style="margin-bottom: 8px;">' + whatsapp_icon_svg(40) + "</div>" +
				'<div style="font-size: 22px; margin-bottom: 4px;">&#9989;</div>' +
				'<div style="font-weight: 600; font-size: 15px;">' + __("Connected") + "</div>" +
				'<div style="color: var(--text-muted); font-size: 12.5px; margin-top: 4px;">' +
				__("This demo WhatsApp session is live and ready to send.") +
				'</div><button class="btn btn-xs btn-danger" style="margin-top: 16px;" id="wa-repair-btn">' +
				__("Re-pair with a different number") +
				"</button></div>"
		);
		wrapper.find("#wa-repair-btn").on("click", confirm_repair);
	}

	function render_daemon_error() {
		var wrapper = dialog.fields_dict.status_html.$wrapper;
		wrapper.html(
			'<div style="text-align:center; padding: 24px 8px; color: var(--red-600);">' +
				__("Can't reach the WhatsApp demo daemon.") +
				"<br><span style=\"font-size:12px; color: var(--text-muted);\">" +
				__("Ask an admin to check it's running on the server.") +
				"</span></div>"
		);
	}

	function render_idle() {
		var wrapper = dialog.fields_dict.status_html.$wrapper;
		wrapper.html(
			'<div style="text-align:center; padding: 24px 8px;">' +
				'<div style="margin-bottom: 12px; opacity: 0.5;">' + whatsapp_icon_svg(36) + "</div>" +
				'<div style="color: var(--text-muted); font-size: 13px; margin-bottom: 14px;">' +
				__("Not connected yet.") +
				'</div><button class="btn btn-sm btn-primary" id="wa-start-btn">' +
				__("Generate QR") +
				"</button></div>"
		);
		wrapper.find("#wa-start-btn").on("click", start_pairing);
	}

	function render_pairing(status, qr_data_uri, seconds_left) {
		var wrapper = dialog.fields_dict.status_html.$wrapper;
		var expired = seconds_left <= 0;

		// The daemon reports "repairing" as soon as a pairing attempt
		// starts, but the QR itself only exists a moment later once the
		// client actually talks to WhatsApp - without this, the <img> tag
		// briefly points at an empty src and the browser flashes a broken-
		// image icon before the real QR arrives. Show a plain loading
		// placeholder of the same size instead of an <img> until there's
		// an actual QR to point it at.
		if (!qr_data_uri && !expired) {
			wrapper.html(
				'<div style="text-align:center; padding: 8px;">' +
					'<div style="margin-bottom: 10px;">' + whatsapp_icon_svg(28) + "</div>" +
					'<div style="width:220px; height:220px; margin: 0 auto; border-radius: 8px; ' +
					"border:1px solid var(--border-color); display:flex; align-items:center; justify-content:center;\">" +
					'<span class="text-muted" style="font-size:12.5px;">' + __("Generating QR...") + "</span>" +
					"</div>" +
					'<div style="margin-top: 12px; font-size: 13px; color: var(--text-muted);">' +
					__("Just a moment") +
					"</div></div>"
			);
			return;
		}

		// If it expired between the status poll and the QR fetch resolving,
		// the daemon may have already discarded the QR file - fall back to
		// the same plain placeholder box rather than an <img> with nothing
		// to point at.
		var qr_visual = qr_data_uri
			? '<img src="' + qr_data_uri + '" style="width:220px; height:220px; ' +
			  "border:1px solid var(--border-color); border-radius: 8px; transition: filter 0.4s, opacity 0.4s;" +
			  (expired ? " filter: blur(6px); opacity: 0.5;" : "") +
			  '" />'
			: '<div style="width:220px; height:220px; margin: 0 auto; border-radius: 8px; ' +
			  "border:1px solid var(--border-color); opacity: 0.5;\"></div>";

		wrapper.html(
			'<div style="text-align:center; padding: 8px;">' +
				'<div style="margin-bottom: 10px;">' + whatsapp_icon_svg(28) + "</div>" +
				qr_visual +
				'<div style="margin-top: 12px; font-size: 13px; color: var(--text-muted);">' +
				(expired
					? __("QR expired.")
					: __("Open WhatsApp on the demo number's phone") +
					  "<br>" +
					  __("Settings &rarr; Linked Devices &rarr; Link a Device") +
					  "<br>" +
					  __("Scan within") + ' <b id="wa-countdown">' + seconds_left + "s</b>") +
				"</div>" +
				(expired
					? '<button class="btn btn-sm btn-primary" style="margin-top: 12px;" id="wa-regen-btn">' +
					  __("Regenerate QR") +
					  "</button>"
					: "") +
				"</div>"
		);
		if (expired) {
			wrapper.find("#wa-regen-btn").on("click", start_pairing);
		}
	}

	function tick() {
		if (!last_status || !last_status.repairing || !last_status.pairing_deadline) {
			return;
		}
		// Ticks locally between polls using the server's own clock/deadline
		// (via the `now`/`pairing_deadline` pair from the last poll), not
		// the browser's clock, so a skewed device clock can't throw off
		// the countdown - only network latency since the last poll can.
		var elapsed_since_poll = (Date.now() - last_status._received_at) / 1000;
		var seconds_left = Math.max(0, Math.round(last_status.pairing_deadline - last_status.now - elapsed_since_poll));
		var el = dialog.fields_dict.status_html.$wrapper.find("#wa-countdown");
		if (el.length) {
			el.text(seconds_left + "s");
		} else if (seconds_left <= 0) {
			// crossed into expired between polls - re-render once to show the blur + button
			refresh_state();
		}
	}

	function refresh_state() {
		frappe.call({
			method: "kirana_console.whatsapp.get_connection_status",
			callback: function (r) {
				var status = r.message || {};
				status._received_at = Date.now();
				last_status = status;

				if (status.error) {
					render_daemon_error();
					return;
				}
				// repairing must win over connected: a re-pair in progress
				// deliberately leaves the OLD session connected until the
				// new one succeeds, so both flags are legitimately true at
				// once - showing "Connected" here would hide the QR the
				// user just asked for.
				if (status.repairing) {
					var seconds_left = Math.max(0, Math.round(status.pairing_deadline - status.now));
					frappe.call({
						method: "kirana_console.whatsapp.get_connection_qr",
						callback: function (qr_r) {
							render_pairing(status, qr_r.message, seconds_left);
						},
					});
					return;
				}
				if (status.connected) {
					render_connected();
					return;
				}
				render_idle();
			},
		});
	}

	dialog.$wrapper.on("hidden.bs.modal", stop_timers);

	dialog.show();
	dialog.$wrapper.find(".modal-title").prepend(whatsapp_icon_svg(18, "vertical-align:-4px; margin-right:8px;"));
	refresh_state();
	poll_timer = setInterval(refresh_state, 3000);
	tick_timer = setInterval(tick, 1000);
}
