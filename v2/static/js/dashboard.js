// Dashboard filters: a preset applies immediately; editing a date switches to "Custom range".
(function () {
  "use strict";
  var form = document.getElementById("filters");
  if (!form) return;
  var period = form.querySelector("select[name=period]");
  period.addEventListener("change", function () {
    if (period.value !== "custom") form.submit();
  });
  form.querySelectorAll("input[type=date]").forEach(function (input) {
    input.addEventListener("change", function () { period.value = "custom"; });
  });
})();
