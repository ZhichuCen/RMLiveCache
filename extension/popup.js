fetch("http://192.168.8.2/health", { cache: "no-store" })
  .then(function (response) { if (!response.ok) throw new Error(); return response.json(); })
  .then(function () { var node = document.getElementById("state"); node.className = "state ok"; node.textContent = "720P 本地缓存在线，官方视频请求将自动转发。"; })
  .catch(function () { var node = document.getElementById("state"); node.className = "state error"; node.textContent = "无法访问局域网缓存；请连接比赛局域网并允许本地网络访问。"; });
