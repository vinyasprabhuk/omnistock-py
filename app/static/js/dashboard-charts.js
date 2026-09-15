(function () {
  function ensureTooltip() {
    var tip = document.querySelector('.js-chart-tooltip');
    if (tip) return tip;
    tip = document.createElement('div');
    tip.className = 'js-chart-tooltip';
    tip.style.cssText = 'position:fixed;pointer-events:none;z-index:1000;display:none;' +
      'background:var(--foreground);color:var(--card);padding:6px 10px;border-radius:6px;' +
      'font-size:0.78rem;line-height:1.4;box-shadow:var(--shadow-md);white-space:nowrap;';
    document.body.appendChild(tip);
    return tip;
  }

  function showTooltip(tip, x, y, html) {
    tip.innerHTML = html;
    tip.style.display = 'block';
    var pad = 14;
    var left = x + pad, top = y + pad;
    var rect = tip.getBoundingClientRect();
    if (left + rect.width > window.innerWidth) left = x - rect.width - pad;
    if (top + rect.height > window.innerHeight) top = y - rect.height - pad;
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }

  function hideTooltip(tip) {
    tip.style.display = 'none';
  }

  document.addEventListener('DOMContentLoaded', function () {
    var tip = ensureTooltip();

    document.querySelectorAll('.js-bar-chart').forEach(function (chart) {
      chart.addEventListener('mousemove', function (e) {
        var bar = e.target.closest('.js-chart-bar');
        if (!bar) { hideTooltip(tip); return; }
        showTooltip(tip, e.clientX, e.clientY,
          '<strong>' + bar.dataset.label + '</strong><br>' + bar.dataset.valueFmt);
      });
      chart.addEventListener('mouseleave', function () { hideTooltip(tip); });
    });

    document.querySelectorAll('.js-trend-chart').forEach(function (wrap) {
      var svg = wrap.querySelector('svg');
      var dataEl = wrap.querySelector('.js-trend-data');
      if (!svg || !dataEl) return;
      var points;
      try { points = JSON.parse(dataEl.textContent); } catch (err) { return; }
      if (!points.length) return;
      var viewBox = svg.viewBox.baseVal;
      var step = points.length > 1 ? viewBox.width / (points.length - 1) : 0;

      svg.addEventListener('mousemove', function (e) {
        var rect = svg.getBoundingClientRect();
        var relX = (e.clientX - rect.left) / rect.width * viewBox.width;
        var idx = step ? Math.round(relX / step) : 0;
        idx = Math.max(0, Math.min(points.length - 1, idx));
        var p = points[idx];
        showTooltip(tip, e.clientX, e.clientY,
          '<strong>' + p.dayLabel + '</strong><br>Produced: ' + p.produced + ' L<br>' +
          'Sold: ' + p.sold + ' L<br>Wasted: ' + p.wasted + ' L<br>' +
          '<strong>Variance: ' + p.variance + ' L</strong>' +
          (p.salesAvailable ? '' : '<br><span style="opacity:0.75;">(no sales report)</span>'));
      });
      svg.addEventListener('mouseleave', function () { hideTooltip(tip); });
    });
  });
})();
