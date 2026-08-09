(function () {
  "use strict";
  var localSource = "http://192.168.8.2/live.m3u8";
  var attempts = 0;

  function enforceLocalSource() {
    attempts += 1;
    try {
      if (!window.videojs) return;
      var player = window.videojs.getPlayer && window.videojs.getPlayer("J_prismPlayer");
      if (!player && window.videojs.players) player = window.videojs.players.J_prismPlayer;
      if (!player || !player.src) return;
      var current = player.currentSource ? player.currentSource() : null;
      var source = current && current.src ? current.src : "";
      if (source.indexOf("http://192.168.8.2/") !== 0) {
        player.src({ src: localSource, type: "application/x-mpegURL" });
        var playResult = player.play();
        if (playResult && playResult.catch) playResult.catch(function () {});
      }
    } catch (_) {}
    if (attempts >= 120) clearInterval(timer);
  }

  var timer = setInterval(enforceLocalSource, 2000);
  enforceLocalSource();
}());
