// "My location" star for WeatherNext Explorer maps.
// Expects WNX_MAP (the Leaflet map) and WNX_STORMS (forecast data, see wnx/maps.py _add_my_location).
// The ZIP is looked up once via api.zippopotam.us; the result is remembered in this browser (localStorage),
// so later page loads need no network call. Distances appear in a tooltip when hovering the star.
(function (map, storms) {
  var KEY = "wnx-my-location";
  var MI_PER_KM = 0.621371;
  var RADII = [50, 100];  // miles, for "N of 64 forecasts pass within X mi"

  function load() { try { return JSON.parse(localStorage.getItem(KEY)); } catch (e) { return null; } }
  function save(v) { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) { /* private mode */ } }

  // ---- geometry -------------------------------------------------------------------------------
  function rad(d) { return d * Math.PI / 180; }
  function miles(a, b) {
    var dLat = rad(b[0] - a[0]), dLon = rad(b[1] - a[1]);
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * 6371 * Math.asin(Math.sqrt(h)) * MI_PER_KM;
  }
  function compass(from, to) {
    var y = Math.sin(rad(to[1] - from[1])) * Math.cos(rad(to[0]));
    var x = Math.cos(rad(from[0])) * Math.sin(rad(to[0])) -
            Math.sin(rad(from[0])) * Math.cos(rad(to[0])) * Math.cos(rad(to[1] - from[1]));
    var deg = (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
    var names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
    return names[Math.round(deg / 22.5) % 16];
  }
  // Closest approach of a track ([[lat, lon, ms], ...]) to point p, checking 20 steps along each 6-h segment.
  function closest(track, p) {
    var best = {d: Infinity, pt: null, t: null, i: 0};
    for (var i = 0; i < track.length; i++) {
      var a = track[i], b = track[Math.min(i + 1, track.length - 1)];
      var dLon = b[1] - a[1];
      if (dLon > 180) dLon -= 360; else if (dLon < -180) dLon += 360;  // date line
      for (var k = 0; k <= 20; k++) {
        var f = k / 20, q = [a[0] + (b[0] - a[0]) * f, a[1] + dLon * f];
        var d = miles(p, q);
        if (d < best.d) best = {d: d, pt: q, t: a[2] + (b[2] - a[2]) * f, i: i + f};
      }
      if (i + 1 >= track.length) break;
    }
    return best;
  }
  function when(ms) {
    return new Date(ms).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"});
  }
  function aroundHour(ms) {  // forecast pass times aren't minute-accurate
    var hour = 3600 * 1000;
    return new Date(Math.round(ms / hour) * hour).toLocaleString([], {weekday: "short", hour: "numeric"});
  }

  // ---- tooltip text ---------------------------------------------------------------------------
  function report(p) {
    var parts = [];
    var list = Object.keys(storms).map(function (id) {
      var s = storms[id], ref = s.now ? [s.now.lat, s.now.lon] : null;
      if (!ref) for (var m in s.means) { ref = s.means[m].track[0]; break; }
      return {id: id, s: s, dist: ref ? miles(p, ref) : Infinity};
    }).sort(function (a, b) { return a.dist - b.dist; }).slice(0, 3);   // nearest three storms

    list.forEach(function (item) {
      var s = item.s, lines = [];
      if (s.now) {
        lines.push("<b>" + s.name + " is " + Math.round(item.dist) + " mi " + compass(p, [s.now.lat, s.now.lon]) +
                   " of you</b> <span style='color:#777'>(NHC position, " + when(s.now.ms) + ")</span>");
      } else {
        lines.push("<b>" + s.name + " is about " + Math.round(item.dist) + " mi away</b>");
      }
      for (var model in s.means) {
        var mean = s.means[model], c = closest(mean.track, p);
        if (!c.pt) continue;
        var label = model === "WNV3" ? "WeatherNext 3" : model === "OPER" ? "Operational model" : model;
        if (c.i < 0.05) {
          lines.push(label + " average track: closest now. It moves away from you <span style='color:#777'>(run " +
                     mean.run + ")</span>");
        } else {
          lines.push(label + " average track passes <b>" + Math.round(c.d) + " mi " + compass(p, c.pt) +
                     "</b> of you around <b>" + aroundHour(c.t) + "</b> <span style='color:#777'>(run " + mean.run + ")</span>");
        }
      }
      if (s.members && s.members.tracks.length) {
        var n = s.members.tracks.length, mins = s.members.tracks.map(function (t) { return closest(t, p).d; });
        var hits = RADII.map(function (r) { return mins.filter(function (d) { return d <= r; }).length; });
        if (hits[hits.length - 1] > 0) {   // skip for far-away storms where every count is zero
          lines.push("Forecast versions bringing the center close: " + RADII.map(function (r, i) {
            return "<b>" + hits[i] + " of " + n + "</b> within " + r + " mi";
          }).join(" · "));
        }
      }
      parts.push(lines.join("<br>"));
    });
    if (!parts.length) parts.push("No storm forecasts on this map.");
    return parts.join("<hr style='margin:6px 0;border:0;border-top:1px solid #ddd'>") +
           "<div style='color:#777;font-size:11px;margin-top:6px'>Distances are to the storm's center; " +
           "damaging winds and rain extend well beyond it.</div>";
  }

  // ---- star marker ----------------------------------------------------------------------------
  var star = null;
  function place(loc) {
    if (star) map.removeLayer(star);
    star = L.marker([loc.lat, loc.lon], {
      icon: L.divIcon({className: "", iconSize: [30, 30], iconAnchor: [15, 15],
        html: "<div style='font-size:30px;line-height:30px;color:#f2c200;" +
              "text-shadow:0 0 2px #000,0 0 2px #000,0 0 3px #000;cursor:default'>&#9733;</div>"}),
      zIndexOffset: 1000, keyboard: false
    });
    star.bindTooltip("<div style='font-weight:700;margin-bottom:4px'>&#9733; " + loc.place + " (" + loc.zip + ")</div>" +
                     report([loc.lat, loc.lon]), {direction: "top", offset: [0, -14], opacity: 0.97});
    if (loc.visible !== false) star.addTo(map);
  }

  // ---- control box ----------------------------------------------------------------------------
  var Box = L.Control.extend({
    options: {position: "topleft"},
    onAdd: function () {
      var div = L.DomUtil.create("div", "leaflet-bar");
      div.style.cssText = "background:#fff;padding:6px 8px;font:12px system-ui,sans-serif;line-height:1.6";
      div.innerHTML =
        "<div style='font-weight:600'>&#9733; My location</div>" +
        "<input id='wnx-zip' inputmode='numeric' maxlength='5' placeholder='ZIP code' " +
        "style='width:72px;padding:2px 4px;font:12px system-ui'> " +
        "<button id='wnx-zip-go' style='font:12px system-ui;padding:2px 6px;cursor:pointer'>Show</button><br>" +
        "<label style='cursor:pointer'><input type='checkbox' id='wnx-star-on' checked> show star</label>" +
        "<div id='wnx-zip-msg' style='color:#777;max-width:150px'></div>";
      L.DomEvent.disableClickPropagation(div);
      L.DomEvent.disableScrollPropagation(div);
      return div;
    }
  });
  new Box().addTo(map);

  var input = document.getElementById("wnx-zip"), go = document.getElementById("wnx-zip-go");
  var toggle = document.getElementById("wnx-star-on"), msg = document.getElementById("wnx-zip-msg");

  function lookup() {
    var zip = (input.value || "").trim();
    if (!/^[0-9]{5}$/.test(zip)) { msg.textContent = "Enter a 5-digit US ZIP."; return; }
    msg.textContent = "Looking up...";
    fetch("https://api.zippopotam.us/us/" + zip).then(function (r) {
      if (!r.ok) throw new Error("not found");
      return r.json();
    }).then(function (j) {
      var pl = j.places[0];
      var loc = {zip: zip, lat: parseFloat(pl.latitude), lon: parseFloat(pl.longitude),
                 place: pl["place name"] + ", " + pl["state abbreviation"], visible: true};
      save(loc); toggle.checked = true; place(loc);
      msg.textContent = "Hover the star for distances.";
    }).catch(function () { msg.textContent = "Couldn't find ZIP " + zip + "."; });
  }
  go.onclick = lookup;
  input.onkeydown = function (e) { if (e.key === "Enter") lookup(); };
  toggle.onchange = function () {
    var loc = load();
    if (!loc) return;
    loc.visible = toggle.checked; save(loc);
    if (!star) return;
    if (toggle.checked) star.addTo(map); else map.removeLayer(star);
  };

  var saved = load();
  if (saved) {
    input.value = saved.zip; toggle.checked = saved.visible !== false;
    place(saved);
    msg.textContent = saved.place;
  }
})(WNX_MAP, WNX_STORMS);
