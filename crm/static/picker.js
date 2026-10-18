/* Type-to-search for long <select> lists (donors, cases, needs, sponsorships, researchers).
 *
 * Any <select data-search> becomes a text box: type part of a name, national ID or phone,
 * then pick with the mouse or the arrow keys + Enter. The original <select> stays in the
 * form (hidden) and keeps the chosen value, so the server sees exactly what it saw before.
 * Matching ignores common Arabic spelling differences (أ/إ/آ/ا, ة/ه, ى/ي, ؤ/و, ئ/ي),
 * diacritics, tatweel and Arabic-Indic digits. No internet or external library needed.
 */
(function () {
  "use strict";
  var MAX_SHOWN = 50;

  function normalize(text) {
    return (text || "")
      .toLowerCase()
      .replace(/[ً-ْٰـ]/g, "")          // diacritics, tatweel
      .replace(/[أإآٱ]/g, "ا")    // أ إ آ ٱ -> ا
      .replace(/ة/g, "ه")                         // ة -> ه
      .replace(/ى/g, "ي")                         // ى -> ي
      .replace(/ؤ/g, "و")                         // ؤ -> و
      .replace(/ئ/g, "ي")                         // ئ -> ي
      .replace(/[٠-٩]/g, function (d) { return String(d.charCodeAt(0) - 0x0660); })
      .replace(/[۰-۹]/g, function (d) { return String(d.charCodeAt(0) - 0x06F0); })
      .replace(/\s+/g, " ")
      .trim();
  }

  function enhance(select, index) {
    var options = Array.prototype.slice.call(select.options).map(function (o) {
      return { value: o.value, label: o.text.trim(), key: normalize(o.text) };
    });
    var placeholder = (options.find(function (o) { return o.value === ""; }) || {}).label || "";
    var choices = options.filter(function (o) { return o.value !== ""; });

    var wrap = document.createElement("div");
    wrap.className = "picker";
    var input = document.createElement("input");
    input.type = "text";
    input.className = "picker-input";
    input.autocomplete = "off";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    var listId = "picker-list-" + index;
    input.setAttribute("aria-controls", listId);
    input.placeholder = select.getAttribute("data-placeholder") || "اكتب للبحث: الاسم أو الرقم القومي أو الهاتف…";
    var list = document.createElement("ul");
    list.className = "picker-list";
    list.id = listId;
    list.setAttribute("role", "listbox");
    list.hidden = true;

    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(input);
    wrap.appendChild(list);
    wrap.appendChild(select);
    select.classList.add("picker-native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    var shown = [];
    var active = -1;

    function currentLabel() {
      var opt = select.options[select.selectedIndex];
      return opt && opt.value !== "" ? opt.text.trim() : "";
    }

    function render(query) {
      var words = normalize(query).split(" ").filter(Boolean);
      shown = choices.filter(function (o) {
        return words.every(function (w) { return o.key.indexOf(w) !== -1; });
      });
      var total = shown.length;
      shown = shown.slice(0, MAX_SHOWN);
      list.innerHTML = "";
      if (!total) {
        var empty = document.createElement("li");
        empty.className = "picker-empty";
        empty.textContent = "لا توجد نتائج";
        list.appendChild(empty);
      }
      shown.forEach(function (o, i) {
        var li = document.createElement("li");
        li.id = listId + "-" + i;
        li.setAttribute("role", "option");
        li.textContent = o.label;
        if (o.value === select.value) li.setAttribute("aria-selected", "true");
        li.addEventListener("mousedown", function (e) { e.preventDefault(); choose(o); });
        list.appendChild(li);
      });
      if (total > MAX_SHOWN) {
        var more = document.createElement("li");
        more.className = "picker-empty";
        more.textContent = "يوجد " + (total - MAX_SHOWN) + " نتيجة أخرى — اكتب أكثر لتضييق البحث";
        list.appendChild(more);
      }
      active = shown.length ? 0 : -1;
      highlight();
    }

    function highlight() {
      Array.prototype.forEach.call(list.querySelectorAll("[role=option]"), function (li, i) {
        li.classList.toggle("active", i === active);
        if (i === active) {
          input.setAttribute("aria-activedescendant", li.id);
          li.scrollIntoView({ block: "nearest" });
        }
      });
      if (active < 0) input.removeAttribute("aria-activedescendant");
    }

    function open() {
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }

    function close() {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      active = -1;
    }

    function choose(o) {
      var changed = select.value !== o.value;
      select.value = o.value;
      input.value = o.label;
      close();
      if (changed) select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    input.value = currentLabel();

    input.addEventListener("focus", function () {
      input.select();
      render("");
      open();
    });
    input.addEventListener("input", function () {
      render(input.value);
      open();
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (list.hidden) { render(input.value); open(); return; }
        if (!shown.length) return;
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
        highlight();
      } else if (e.key === "Enter") {
        if (!list.hidden && active >= 0) {
          e.preventDefault();               // pick, don't submit the form
          choose(shown[active]);
        }
      } else if (e.key === "Escape") {
        input.value = currentLabel();
        close();
      }
    });
    input.addEventListener("blur", function () {
      // Leaving the box empty clears an optional field; otherwise show the chosen value again.
      if (!input.value.trim() && placeholder !== "" && select.value !== "") {
        select.value = "";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
      input.value = currentLabel();
      close();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll("select[data-search]"), enhance);
  });
})();
