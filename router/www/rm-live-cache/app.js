(function () {
  "use strict";

  var video = document.getElementById("rm-video");
  var playButton = document.getElementById("play-button");
  var playerState = document.getElementById("player-state");
  var hls = null;

  function setPlayerState(text, className) {
    playerState.textContent = text;
    playerState.className = "player-state" + (className ? " " + className : "");
  }

  function tryPlay() {
    var attempt = video.play();
    if (attempt && attempt.catch) {
      attempt.then(function () {
        playButton.hidden = true;
      });
      attempt.catch(function () {
        playButton.hidden = false;
        setPlayerState("直播已就绪，点击播放；浏览器会先静音播放", "ok");
      });
    }
  }

  function startPlayer() {
    if (window.Hls && Hls.isSupported()) {
      hls = new Hls({
        enableWorker: true,
        lowLatencyMode: false,
        liveSyncDurationCount: 3,
        liveMaxLatencyDurationCount: 8,
        maxBufferLength: 20,
        backBufferLength: 10
      });
      hls.attachMedia(video);
      hls.on(Hls.Events.MEDIA_ATTACHED, function () {
        hls.loadSource("/live.m3u8");
      });
      hls.on(Hls.Events.MANIFEST_PARSED, function () {
        setPlayerState("直播播放正常；点击音量按钮开启声音", "ok");
        tryPlay();
      });
      hls.on(Hls.Events.ERROR, function (_event, data) {
        if (!data.fatal) return;
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          setPlayerState("网络暂时中断，正在重新连接…", "error");
          hls.startLoad();
        } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          setPlayerState("播放器正在恢复视频解码…", "error");
          hls.recoverMediaError();
        } else {
          setPlayerState("播放器遇到不可恢复错误，请刷新页面", "error");
          hls.destroy();
        }
      });
      return;
    }

    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = "/live.m3u8";
      video.addEventListener("loadedmetadata", function () {
        setPlayerState("直播播放正常；点击音量按钮开启声音", "ok");
        tryPlay();
      });
      video.addEventListener("error", function () {
        setPlayerState("视频加载失败，正在等待直播源更新…", "error");
      });
      tryPlay();
      return;
    }

    setPlayerState("当前浏览器不支持 HLS 播放，请使用新版 Chrome、Edge 或 Safari", "error");
  }

  playButton.addEventListener("click", function () {
    video.muted = false;
    tryPlay();
  });
  video.addEventListener("playing", function () {
    playButton.hidden = true;
    setPlayerState("直播播放正常", "ok");
  });
  video.addEventListener("pause", function () {
    playButton.hidden = false;
  });

  function formatBytes(value) {
    if (!Number.isFinite(value)) return "—";
    var units = ["B", "KB", "MB", "GB"];
    var index = 0;
    while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
    return value.toFixed(index > 1 ? 1 : 0) + " " + units[index];
  }

  function setText(id, value) { document.getElementById(id).textContent = value; }

  function refreshStatus() {
    fetch("/api/status", { cache: "no-store" })
      .then(function (response) { if (!response.ok) throw new Error("HTTP " + response.status); return response.json(); })
      .then(function (status) {
        var health = document.getElementById("health");
        health.className = "badge " + (status.live_active ? "ok" : "pending");
        health.textContent = status.live_active ? "本地直播在线" : "直播暂未开始";
        setText("source", status.source_label || "等待直播源");
        setText("cache", formatBytes(status.cache_bytes) + " / " + formatBytes(status.cache_limit_bytes));
        setText("hits", String((status.stats && status.stats.cache_hits) || 0));
        setText("saved", formatBytes(status.estimated_wan_saved_bytes || 0));
      })
      .catch(function () {
        var health = document.getElementById("health");
        health.className = "badge error";
        health.textContent = "缓存服务离线";
      });
  }

  startPlayer();
  refreshStatus();
  setInterval(refreshStatus, 3000);
}());
